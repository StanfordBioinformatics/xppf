#!/usr/bin/env python

import argparse
import copy
from datetime import datetime
import docker
import errno
import json
import logging
import os
import requests
import string
import subprocess
import sys
import threading
import time
import uuid

import loomengine.utils
from loomengine.utils.filemanager import FileManager
from loomengine.utils.connection import Connection


class WorkerSettingsError(Exception):
    pass

class ContainerStartError(Exception):
    pass

class ContainerPullError(Exception):
    pass

class TaskAttemptNotFoundError(Exception):
    pass

class DockerDaemonNotFoundError(Exception):
    pass

class FileImportError(Exception):
    pass


class TaskRunner(object):

    DOCKER_SOCKET = 'unix://var/run/docker.sock'
    LOOM_RUN_SCRIPT_NAME = 'loom_run_script'

    def __init__(self, args=None, mock_connection=None, mock_filemanager=None):
        self.is_failed = False
        if args is None:
            args = self._get_args()
        self.settings = {
            'TASK_ATTEMPT_ID': args.task_attempt_id,
            'MASTER_URL': args.master_url,
            'LOG_LEVEL': args.log_level,
        }

        # Errors here can't be reported since there is no server connection
        # or logger

        self._init_loggers()

        # Errors here can be logged but not reported to server

        if mock_connection is not None:
            self.connection = mock_connection
        else:
            try:
                self.connection = Connection(self.settings['MASTER_URL'])
            except Exception as e:
                self.logger.error(
                    'Failed to initialize server connection: "%s"' % str(e))
                raise

        # Errors here can be both logged and reported to server

        try:
            self._timepoint('Initializing monitor')
            self._init_task_attempt()
            if mock_filemanager is not None:
                self.filemanager = mock_filemanager
            else:
                self.filemanager = FileManager(self.settings['MASTER_URL'])
                self.settings.update(self._get_worker_settings())
                self._init_docker_client()
                self._init_working_dir()
        except Exception as e:
            try:
                self._fail('Failed to initialize', detail=str(e))
            except:
                # Raise original error, not status change error
                pass
            raise

    def _init_loggers(self):
        log_level = self.settings['LOG_LEVEL']
        self.logger = get_stdout_logger(__name__, log_level)
        utils_logger = get_stdout_logger(loomengine.utils.__name__, log_level)

    def _init_task_attempt(self):
        self.task_attempt = self.connection.get_task_attempt(self.settings['TASK_ATTEMPT_ID'])
        if self.task_attempt is None:
            raise TaskAttemptNotFoundError('TaskAttempt ID "%s" not found' % self.settings['TASK_ATTEMPT_ID'])

    def _get_worker_settings(self):
        settings = self.connection.get_worker_settings(self.settings['TASK_ATTEMPT_ID'])
        if settings is None:
            raise WorkerSettingsError('Worker settings not found')
        return settings

    def _init_docker_client(self):
        self.docker_client = docker.Client(base_url=self.DOCKER_SOCKET)
        self._verify_docker()

    def _verify_docker(self):
        try:
            self.docker_client.info()
        except requests.exceptions.ConnectionError:
            raise DockerDaemonNotFoundError('Failed to connect to Docker daemon')

    def _init_working_dir(self):
        self.logger.info('Initializing working directory %s' %
                         self.settings['WORKING_DIR'])
        init_directory(self.settings['WORKING_DIR'], new=True)

    def run_with_heartbeats(self, function):
        heartbeat_interval = int(self.settings['HEARTBEAT_INTERVAL_SECONDS'])
        polling_interval = 1

        t = threading.Thread(target=function)
        t.start()

        self._send_heartbeat()
        last_heartbeat = datetime.now()

        while t.is_alive():
            time.sleep(polling_interval)
            if (datetime.now() - last_heartbeat).total_seconds() > heartbeat_interval:
                self._send_heartbeat()
                last_heartbeat = datetime.now()

    def main(self):
        run_error = None
        cleanup_error = None

        try:
            self._run()
        except Exception as e:
            run_error = e
        try:
            self._cleanup()
        except Exception as e:
            cleanup_error = e

        # Errors from initialization or run
        # take priority over errors from cleanup
        if run_error:
            raise run_error
        elif cleanup_error:
            raise cleanup_error

    def _run(self):
        try:
            self._try_to_copy_inputs()
            self._try_to_create_run_script()
            self._try_to_pull_image()
            self._try_to_create_container()
            self._try_to_run_container()
            self._try_to_get_returncode()
        except Exception as e:
            self.logger.error('Exiting run with error: %s' % str(e))
            raise

    def _cleanup(self):
        # Never raise errors, so cleanup can continue
        self._timepoint('Saving outputs')

        try:
            self._save_process_logs()
        except Exception as e:
            self._fail('Failed to save process logs', detail=str(e))

        try:
            self._save_outputs()
        except Exception as e:
            self._fail('Failed to save outputs', detail=str(e))

        try:
            self._finish()
            self.logger.info('Done.')
        except Exception as e:
            self._fail('Failed to set status to finished',
                       detail=str(e))

    def _try_to_copy_inputs(self):
        self.logger.info('Downloading input files')
        self._timepoint('Copying inputs')
        try:
            self._copy_inputs()
        except Exception as e:
            self._fail('Failed to copy inputs to workspace',
                       detail=str(e))
            raise

    def _copy_inputs(self):
        if self.task_attempt.get('inputs') is None:
            self.logger.info('No inputs.')
            return
        file_data_object_ids = []
        for input in self.task_attempt['inputs']:
            data_object = self.connection.get_data_object(input['data_object']['uuid'])
            if data_object['type'] == 'file':
                file_data_object_ids.append('@'+data_object['uuid'])
        self.logger.debug('Copying inputs %s to %s.' % ( file_data_object_ids,
                                                         self.settings['WORKING_DIR']))
        self.filemanager.export_files(
            file_data_object_ids,
            destination_url=self.settings['WORKING_DIR'])

    def _try_to_create_run_script(self):
        self.logger.info('Creating run script')
        self._timepoint('Creating run script')

        try:
            self._create_run_script()
        except Exception as e:
            self._fail('Failed to create run script', detail=str(e))
            raise

    def _create_run_script(self):
        user_command = self.task_attempt['rendered_command']
        with open(os.path.join(
                self.settings['WORKING_DIR'],
                self.LOOM_RUN_SCRIPT_NAME),
                  'w') as f:
            f.write(user_command + '\n')

    def _try_to_pull_image(self):
        self._timepoint('Fetching image')

        try:
            self._pull_image()
            image_id = self.docker_client.inspect_image(self._get_docker_image())['Id']
            self._set_image_id(image_id)
            self.logger.info(
                'Pulled image %s and received image id %s' % (
                    self._get_docker_image(), image_id))
        except Exception as e:
            self._fail(
                'Failed to fetch image for runtime environment',
                detail=str(e))
            raise


    def _pull_image(self):
        pull_data = self._parse_docker_output(
            self.docker_client.pull(self._get_docker_image()))
        if pull_data[-1].get('errorDetail'):
            raise ContainerPullError(pull_data[-1].get('errorDetail'))
        else:
            self.logger.debug(json.dumps(pull_data, indent=2, separators=(',', ': ')))

    def _get_docker_image(self):
        # Tag is required. Otherwise docker-py pull will download all tags.
        docker_image = self.task_attempt['environment']['docker_image']
        if not ':' in docker_image:
            docker_image = docker_image + ':latest'
        return docker_image

    def _parse_docker_output(self, data):
        return [json.loads(line) for line in data.strip().split('\r\n')]

    def _try_to_create_container(self):
        self._timepoint('Creating container')
        try:
            self._create_container()
            self._set_container_id(self.container['Id'])
        except Exception as e:
            self._fail(
                'Failed to create container for runtime environment',
                detail=str(e))
            raise

    def _create_container(self):
        docker_image = self._get_docker_image()
        interpreter = self.task_attempt['interpreter']
        host_dir = self.settings['WORKING_DIR']
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
        )

    def _try_to_run_container(self):
        self._timepoint('Starting analysis')
        try:
            self.docker_client.start(self.container)
            self._verify_container_started_running()
        except Exception as e:
            self._fail('Failed to start analysis', detail=str(e))
            raise

    def _verify_container_started_running(self):
        status = self.docker_client.inspect_container(
            self.container)['State'].get('Status')
        if status == 'running' or status == 'exited':
            return
        else:
            raise ContainerStartError('Unexpected container status "%s"' % status)

    def _try_to_get_returncode(self):
        self._timepoint('Running analysis')
        try:
            returncode = self._poll_for_returncode()
            if returncode == 0:
                return
            else:
                # bad returncode
                self._fail(
                    'Analysis finished with a bad returncode %s' % returncode,
                    detail='Returncode %s. Check stderr log for more information.' \
                    % returncode)
                # Do not raise error. Attempt to save log files.
        except Exception as e:
            self._fail(
                'An error prevented the analysis from finishing',
                detail=str(e))
            # Do not raise error. Attempt to save log files.

    def _poll_for_returncode(self, poll_interval_seconds=1):
        while True:
            try:
                container_data = self.docker_client.inspect_container(self.container)
            except Exception as e:
                raise Exception('Unable to inspect Docker container: "%s"' % str(e))

            if not container_data.get('State'):
                raise Exception(
                    'Could not parse container info from Docker: "%s"' % container_data)

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
        self.logger.debug('Saving process logs')
        try:
            self.container
        except AttributeError:
            self.logger.debug('No container, so no process logs to save.')
            return

        init_directory(
            os.path.dirname(os.path.abspath(self.settings['STDOUT_LOG_FILE'])))
        with open(self.settings['STDOUT_LOG_FILE'], 'w') as stdoutlog:
            stdoutlog.write(
                self.docker_client.logs(self.container, stderr=False, stdout=True)
            )
        init_directory(
            os.path.dirname(os.path.abspath(self.settings['STDERR_LOG_FILE'])))
        with open(self.settings['STDERR_LOG_FILE'], 'w') as stderrlog:
            stderrlog.write(
                self.docker_client.logs(self.container, stderr=True, stdout=False)
            )
        self._import_log_file(self.settings['STDOUT_LOG_FILE'])
        self._import_log_file(self.settings['STDERR_LOG_FILE'])

    def _import_log_file(self, filepath):
        try:
            self.filemanager.import_log_file(
                self.task_attempt,
                filepath,
            )
        except IOError:
            message = 'Failed to upload log file %s' % filepath
            self.logger.error(message)
            raise FileImportError(message)

    def _save_outputs(self):
        try:
            self.container
        except AttributeError:
            self.logger.debug('No container, so no outputs to save.')
            return # Never ran. No outputs to save

        self.logger.debug('Saving outputs')

        for output in self.task_attempt['outputs']:
            if output['type'] == 'file':
                filename = output['source']['filename']
                try:
                    data_object = self.filemanager.import_result_file(
                        output,
                        os.path.join(self.settings['WORKING_DIR'], filename)
                    )
                    self.logger.debug('Saved file output "%s"' % data_object['uuid'])
                except IOError as e:
                    self._fail(
                        'Failed to save output file %s' % filename,
                        detail=str(e))
                    raise
            else:
                if output['source'].get('filename'):
                    with open(
                            os.path.join(
                                self.settings['WORKING_DIR'],
                                output['source'].get('filename')),
                            'r') as f:
                        output_text = f.read()

                elif output['source'].get('stream'):
                    # Get result from stream
                    if output['source'].get('stream') == 'stdout':
                        output_text = self.docker_client.logs(
                            self.container, stderr=False, stdout=True)
                    elif output['source'].get('stream') == 'stderr':
                        output_text = self.docker_client.logs(
                            self.container, stderr=True, stdout=False)
                    else:
                        raise Exception(
                            'Could not save output "%s" because source is unknown stream type "%s"' %  (output['channel'], output['source']['stream']))
                else:
                    raise Exception(
                        'Could not save output "%s" because did not include a filename or a stream: "%s"' %  (output['channel'], output['source']))

                data_object = self._save_nonfile_output(output, output_text)
                self.logger.debug(
                    'Saved %s output "%s"' % (output['type'], data_object['id']))

    def _save_nonfile_output(self, output, output_text):
        data_type = output['type']
        data_object = {
            'type': data_type,
            'value': output_text
        }
        output.update({'data_object': data_object})
        return self.connection.update_task_attempt_output(output['id'], output)

    # Updates to TaskAttempt

    def _send_heartbeat(self):
        self.connection.update_task_attempt(
            self.settings['TASK_ATTEMPT_ID'],
            {}
        )

    def _set_container_id(self, container_id):
        self.connection.update_task_attempt(
            self.settings['TASK_ATTEMPT_ID'],
            {'container_id': container_id}
        )

    def _set_image_id(self, image_id):
        self.connection.update_task_attempt(
            self.settings['TASK_ATTEMPT_ID'],
            {'image_id': image_id}
        )

    def _timepoint(self, message, detail='', is_error=False):
        timepoint = {'message': message,
                     'detail': detail,
                     'is_error': is_error
        }
        if is_error:
            self.logger.error('Adding error %s' % timepoint)
        else:
            self.logger.debug('Adding timepoint %s' % timepoint)
        self.connection.post_task_attempt_timepoint(
            self.settings['TASK_ATTEMPT_ID'], timepoint)

    def _fail(self, message, detail=''):
        self.is_failed = True
        self.logger.error(message + ': ' + detail)
        self._timepoint(message, detail=detail, is_error=True)
        self.connection.post_task_attempt_fail(self.settings['TASK_ATTEMPT_ID'])

    def _finish(self):
        self.connection.post_task_attempt_finish(self.settings['TASK_ATTEMPT_ID'])

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
                            '--master_url',
                            required=True,
                            help='URL of the Loom master server')
        parser.add_argument('-l',
                            '--log_level',
                            required=False,
                            choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                            default='WARNING',
                            help='Log level')
        parser.add_argument('-f',
                            '--log_file',
                            required=False,
                            default=None,
                            help='Log file')
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
        raise Exception('Failed to create directory %s. %s' % (directory, e.strerror))

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

    tr = TaskRunner()
    tr.run_with_heartbeats(tr.main)


if __name__=='__main__':
    main()
