#!/usr/bin/env python

import argparse
import copy
from datetime import datetime
from dateutil.parser import parse
import docker
import errno
import json
import logging
import os
import pytz
import requests
import shutil
import string
import sys
import threading
import traceback
import time
import uuid

from loomengine_utils import execute_with_retries
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import FileAlreadyExistsError
from loomengine_utils.export_manager import ExportManager
from loomengine_utils.import_manager import ImportManager
from loomengine_worker.outputs import TaskAttemptOutput
from loomengine_worker.inputs import TaskAttemptInputs


class TaskMonitor(object):

    DOCKER_SOCKET = 'unix://var/run/docker.sock'
    LOOM_RUN_SCRIPT_NAME = '.loom_run_script'

    def __init__(self, args=None, mock_connection=None,
                 mock_import_manager=None, mock_export_manager=None):
        if args is None:
            args = self._get_args()
        self.settings = {
            'TASK_ATTEMPT_ID': args.task_attempt_id,
            'SERVER_URL': args.server_url,
            'LOG_LEVEL': args.log_level,
        }
        self.is_failed = False

        self.logger = get_stdout_logger(
            __name__, self.settings['LOG_LEVEL'])

        if mock_connection is not None:
            self.connection = mock_connection
        else:
            try:
                self.connection = Connection(self.settings['SERVER_URL'],
                                             token=args.token)
            except Exception as e:
                error = self._get_error_text(e)
                self.logger.error(
                    'TaskMonitor for attempt %s failed to initialize server '
                    'connection. %s'
                    % (self.settings.get('TASK_ATTEMPT_ID'), error))
                raise

        self._event('Initializing TaskMonitor')
        self._init_task_attempt()

        # From here on errors can be reported to Loom

        if mock_import_manager is not None:
            self.import_manager = mock_import_manager
        else:
            try:
                self.storage_settings = self.connection.get_storage_settings()
                self.import_manager = ImportManager(
                    self.connection, storage_settings=self.storage_settings)
                self.export_manager = ExportManager(
                    self.connection, storage_settings=self.storage_settings)
                self.settings.update(self._get_settings())
                self._init_docker_client()
                self._init_working_dir()
            except Exception as e:
                error = self._get_error_text(e)
                self._report_system_error(
                    detail='Initializing TaskMonitor failed. %s'
                    % error)
                raise

    def _init_task_attempt(self):
        self.task_attempt = self.connection.get_task_attempt(
            self.settings['TASK_ATTEMPT_ID'])
        if self.task_attempt is None:
            raise Exception(
                'TaskAttempt ID "%s" not found'
                % self.settings['TASK_ATTEMPT_ID'])

    def _get_settings(self):
        settings = self.connection.get_task_attempt_settings(
            self.settings['TASK_ATTEMPT_ID'])
        if settings is None:
            raise Exception('Worker settings not found')
        return settings

    def _init_docker_client(self):
        self.docker_client = docker.Client(base_url=self.DOCKER_SOCKET)
        self._verify_docker()

    def _verify_docker(self):
        try:
            self.docker_client.info()
        except requests.exceptions.ConnectionError:
            raise Exception('Failed to connect to Docker daemon')

    def _init_working_dir(self):
        init_directory(self.settings['WORKING_DIR_ROOT'], new=True)
        self.working_dir = os.path.join(
            self.settings['WORKING_DIR_ROOT'], 'work')
        self.log_dir = os.path.join(self.settings['WORKING_DIR_ROOT'], 'logs')
        init_directory(self.working_dir, new=True)
        init_directory(self.log_dir, new=True)

    def _delete_working_dir(self):
        # Skip delete if blank or root!
        if self.settings['WORKING_DIR_ROOT'].strip('/'):
            shutil.rmtree(self.settings['WORKING_DIR_ROOT'])

    def run_with_heartbeats(self, function):
        heartbeat_interval = int(self.settings['HEARTBEAT_INTERVAL_SECONDS'])
        polling_interval = 1

        t = threading.Thread(target=function)
        t.start()

        last_heartbeat = self._send_heartbeat()

        while t.is_alive():
            time.sleep(polling_interval)
            if (datetime.utcnow().replace(tzinfo=pytz.utc) - last_heartbeat)\
               .total_seconds() > \
               (heartbeat_interval - polling_interval):
                last_heartbeat = self._send_heartbeat()

    def run(self):
        try:
            self._copy_inputs()
            self._create_run_script()
            self._create_container()
            self._run_container()
            self._stream_docker_logs()
            self._get_returncode()
            self._save_process_logs()
            if not self.is_failed:
                self._save_outputs()
                self._finish()
        finally:
            self._delete_working_dir()
            self._delete_container()

    def _copy_inputs(self):
        self._event('Copying inputs')
        if self.task_attempt.get('inputs') is None:
            return
        try:
            TaskAttemptInputs(self.task_attempt['inputs'], self).copy()
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Copying inputs failed. %s' % error)
            raise

    def _create_run_script(self):
        try:
            user_command = self.task_attempt['command']
            with open(os.path.join(
                    self.working_dir,
                    self.LOOM_RUN_SCRIPT_NAME),
                      'w') as f:
                f.write(user_command.encode('utf-8') + '\n')
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Creating run script failed. %s' % error)
            raise

    def _get_docker_image(self):
        docker_image = self.task_attempt['environment']['docker_image']
        # If no registry is specified, set to default.
        # If the first term contains "." or ends in ":", it is a registry.
        part1 = docker_image.split('/')[0]
        if '.' not in part1 and not part1.endswith(':'):
            default_registry = self.settings.get(
                'DEFAULT_DOCKER_REGISTRY', None)
            # Don't add default_registry without the owner.
            # Default ower is library
            if len(docker_image.split('/')) == 1:
                docker_image = 'library/' + docker_image
            if default_registry:
                docker_image = '%s/%s' % (default_registry, docker_image)
        # Tag is required. Otherwise docker-py pull will download all tags.
        if '@' not in docker_image and ':' not in docker_image:
            docker_image += ':latest'
        return docker_image

    def _parse_docker_output(self, data):
        return [json.loads(line) for line in data.strip().split('\r\n')]

    def _create_container(self):
        self._event('Creating container')
        try:
            docker_image = self._get_docker_image()
            interpreter = self.task_attempt['interpreter']
            host_dir = self.working_dir
            container_dir = '/loom_workspace'

            command = interpreter.split(' ')
            command.append(self.LOOM_RUN_SCRIPT_NAME)

            self.container = self.docker_client.create_container(
                image=docker_image,
                command=command,
                volumes=[container_dir],
                host_config=self.docker_client.create_host_config(
                    binds={host_dir: {
                        'bind': container_dir,
                        'mode': 'rw',
                    }}),
                working_dir=container_dir,
                name=self.settings['PROCESS_CONTAINER_NAME'],
            )
            self._set_container_id(self.container['Id'])
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Creating container failed. %s' % error)
            raise

    def _run_container(self):
        self._event('Starting analysis')
        try:
            self.docker_client.start(self.container)
            self._verify_container_started_running()
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Starting analysis failed. %s' % error)
            raise

    def _verify_container_started_running(self):
        status = self.docker_client.inspect_container(
            self.container)['State'].get('Status')
        if status == 'running' or status == 'exited':
            return
        else:
            raise Exception('Unexpected container status "%s"' % status)

    def _stream_docker_logs(self):
        """Stream stdout and stderr from the task container to this
        process's stdout and stderr, respectively.
        """
        thread = threading.Thread(target=self._stderr_stream_worker)
        thread.start()
        for line in self.docker_client.logs(self.container, stdout=True,
                                            stderr=False, stream=True):
            sys.stdout.write(line)
        thread.join()

    def _stderr_stream_worker(self):
        for line in self.docker_client.logs(self.container, stdout=False,
                                            stderr=True, stream=True):
            sys.stderr.write(line)

    def _get_returncode(self):
        self._event('Running analysis')
        try:
            returncode = self._poll_for_returncode()
            if returncode == 0:
                return
            else:
                # bad returncode
                self._report_analysis_error(
                    'Analysis finished with returncode %s. '
                    'Check stderr/stdout logs for errors.'
                    % returncode)
                # Do not raise error. Attempt to save log files.
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error('Failed to run analysis. %s' % error)
            # Do not raise error. Attempt to save log files.

    def _poll_for_returncode(self, poll_interval_seconds=1):
        while True:
            try:
                container_data = self.docker_client.inspect_container(
                    self.container)
            except Exception as e:
                raise Exception(
                    'Unable to inspect Docker container: "%s"' % str(e))

            if not container_data.get('State'):
                raise Exception(
                    'Could not parse container info from Docker: "%s"'
                    % container_data)

            if container_data['State'].get('Status') == 'exited':
                # Success
                return container_data['State'].get('ExitCode')
            elif container_data['State'].get('Status') == 'running':
                time.sleep(poll_interval_seconds)
            else:
                # Error -- process did not complete
                message = 'Docker container has unexpected status "%s"' % \
                          container_data['State'].get('Status')
                raise Exception(message)

    def _save_process_logs(self):
        self._event('Saving logfiles')
        try:
            stdout_file = os.path.join(self.log_dir, 'stdout.log')
            stderr_file = os.path.join(self.log_dir, 'stderr.log')
            init_directory(
                os.path.dirname(self.log_dir))
            with open(stdout_file, 'w') as stdoutlog:
                stdoutlog.write(self._get_stdout())
            with open(stderr_file, 'w') as stderrlog:
                stderrlog.write(self._get_stderr())
            self._import_log_file(stderr_file, retry=True)
            self._import_log_file(stdout_file, retry=True)
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Saving log files failed. %s' % error)
            raise

    def _get_stdout(self):
        return self.docker_client.logs(
            self.container, stderr=False, stdout=True)

    def _get_stderr(self):
        return self.docker_client.logs(
            self.container, stderr=True, stdout=False)

    def _import_log_file(self, filepath, retry=True):
        try:
            self.import_manager.import_log_file(
                self.task_attempt,
                filepath,
                retry=retry,
            )
        except IOError:
            message = 'Failed to upload log file %s' % filepath
            raise Exception(message)

    def _save_outputs(self):
        self._event('Saving outputs')
        try:
            for output in self.task_attempt['outputs']:
                TaskAttemptOutput(output, self).save()
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Saving outputs failed. %s' % error)
            raise

    def _finish(self):
        try:
            self._finish()
        except Exception as e:
            error = self._get_error_text(e)
            self._report_system_error(
                detail='Setting finished status failed. %s' % error)
            raise

    # Updates to TaskAttempt

    def _send_heartbeat(self):
        task_attempt = self.connection.update_task_attempt(
            self.settings['TASK_ATTEMPT_ID'],
            {}
        )
        return parse(task_attempt.get('last_heartbeat'))

    def _set_container_id(self, container_id):
        self.connection.update_task_attempt(
            self.settings['TASK_ATTEMPT_ID'],
            {'container_id': container_id}
        )

    def _save_environment_info(self, container_info):
        self.connection.update_task_attempt(
            self.settings['TASK_ATTEMPT_ID'],
            {'environment_info': container_info}
        )

    def _event(self, event, detail='', is_error=False):
        if is_error:
            self.logger.error("%s. %s" % (event, detail))
        else:
            self.logger.info("%s. %s" % (event, detail))
        self.connection.post_task_attempt_event(
            self.settings['TASK_ATTEMPT_ID'],
            {
                'event': event,
                'detail': detail,
                'is_error': is_error
            })

    def _report_system_error(self, detail=''):
        self.is_failed = True
        try:
            self._event(
                "TaskAttempt execution failed.", detail=detail, is_error=True)
            self.connection.post_task_attempt_system_error(
                self.settings['TASK_ATTEMPT_ID'])
        except Exception:
            # If there is an error reporting failure, don't raise it
            # because it will mask the root cause of failure
            pass

    def _report_analysis_error(self, detail=''):
        self.is_failed = True
        try:
            self._event(
                "TaskAttempt execution failed.", detail=detail, is_error=True)
            self.connection.post_task_attempt_analysis_error(
                self.settings['TASK_ATTEMPT_ID'])
        except Exception:
            # If there is an error reporting failure, don't raise it
            # because it will mask the root cause of failure
            pass

    def _finish(self):
        self.connection.finish_task_attempt(self.settings['TASK_ATTEMPT_ID'])

    def _delete_container(self):
        try:
            if not self.container:
                return
        except AttributeError:
            return
        if self.settings.get('PRESERVE_ALL'):
            return
        if self.is_failed and self.settings.get('PRESERVE_ON_FAILURE'):
            return
        self.docker_client.stop(self.container)
        self.docker_client.remove_container(self.container)

    def _get_error_text(self, e):
        if hasattr(self, 'settings') and self.settings.get('DEBUG'):
            return traceback.format_exc()
        else:
            return "%s.%s: %s" % (
                e.__class__.__module__, e.__class__.__name__, str(e))

    # Parser

    def _get_args(self):
        parser = self.get_parser()
        return parser.parse_args()

    @classmethod
    def get_parser(self):
        parser = argparse.ArgumentParser(__file__)
        parser.add_argument('-i',
                            '--task_attempt_id',
                            required=True,
                            help='ID of TaskAttempt to be processed')
        parser.add_argument('-u',
                            '--server_url',
                            required=True,
                            help='URL of the Loom server')
        parser.add_argument('-l',
                            '--log_level',
                            required=False,
                            choices=['DEBUG', 'INFO', 'WARNING',
                                     'ERROR', 'CRITICAL'],
                            default='WARNING',
                            help='Log level')
        parser.add_argument('-t',
                            '--token',
                            required=False,
                            default=None,
                            help='Authentication token')
        return parser


def init_directory(directory, new=False):
    if new and os.path.exists(directory):
        raise Exception('Directory %s already exists' % directory)
    if os.path.exists(directory) and not os.path.isdir(directory):
        raise Exception(
            'Cannot initialize directory %s since a file exists with that name'
            % directory)
    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
    except OSError as e:
        raise Exception(
            'Failed to create directory %s. %s' % (directory, e.strerror))


LOG_LEVELS = {
    'CRITICAL': logging.CRITICAL,
    'ERROR': logging.ERROR,
    'WARNING': logging.WARNING,
    'INFO': logging.INFO,
    'DEBUG': logging.DEBUG,
}


def get_stdout_logger(name, log_level_string):
    log_level = LOG_LEVELS[log_level_string.upper()]
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(log_level)
    logger.addHandler(stream_handler)
    return logger


# pip entrypoint requires a function with no arguments
def main():
    monitor = TaskMonitor()
    monitor.run_with_heartbeats(monitor.run)


if __name__ == '__main__':
    main()
