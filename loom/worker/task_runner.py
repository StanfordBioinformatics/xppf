#!/usr/bin/env python

import argparse
from datetime import datetime
import errno
import string
import logging
import os
import requests
import subprocess
import sys
import time
import uuid

from loom.common.filehandler import FileHandler
from loom.common.objecthandler import ObjectHandler
from loom.common.logger import StreamToLogger

class TaskRunner(object):

    def __init__(self, args=None):
        if args is None:
            args = self._get_args()
        self.settings = {
            'RUN_ID': args.run_id,
            'RUN_LOCATION_ID': args.run_location_id,
            'MASTER_URL': args.master_url
        }
        self.settings.update(self._get_additional_settings())
        self._prepare_working_directory(self.settings['WORKING_DIR'])
        self._add_logfiles()
        self._init_logger()
        self._init_filehandler()
        self._init_objecthandler()
        self._init_task_run()
        
    def run(self):

        self._download_inputs()
        
        with open(self.settings['STDOUT_LOGFILE'], 'w') as stdoutlog:
            with open(self.settings['STDERR_LOGFILE'], 'w') as stderrlog:
                process = self._execute(stdoutlog, stderrlog)
                self._wait_for_process(process)

        self._upload_outputs()
        self._upload_logfiles()

        # self._flag_run_as_complete(self.step_run)
        print "done"

    def _download_inputs(self):
        if self.task_run.get('task_run_inputs') is None:
            return
        data_object_ids = ['@'+task_run_input['task_definition_input']['data_object']['_id']
                            for task_run_input in self.task_run['task_run_inputs']]
        self.filehandler.download_files(data_object_ids, target_directory=self.settings['WORKING_DIR'])

    def _upload_outputs(self):
        for task_run_output in self.task_run['task_run_outputs']:
            path = task_run_output['task_definition_output']['path']
            task_run_output['data_object'] = self.filehandler.upload_step_output_from_local_path(path, self.task_run['workflow_run_datetime_created'], self.task_run['workflow_name'], self.task_run['step_name'], source_directory=self.settings['WORKING_DIR'])
        self.objecthandler.update_task_run(self.task_run)

    def _upload_logfiles(self):
        for logfile in (self.settings['STEP_LOGFILE'], self.settings['STDOUT_LOGFILE'], self.settings['STDERR_LOGFILE']):
            file_object = self.filehandler.upload_step_output_from_local_path(logfile, self.task_run['workflow_run_datetime_created'], self.task_run['workflow_name'], self.task_run['step_name'])
            task_run_log = {'logfile': file_object, 'logname': os.path.basename(logfile)}
            if 'logs' not in self.task_run:
                self.task_run['logs'] = []
            self.task_run['logs'].append(task_run_log)
        self.objecthandler.update_task_run(self.task_run)

    def _get_additional_settings(self):
        url = self.settings['MASTER_URL'] + '/api/workerinfo/'
        response = requests.get(url)
        response.raise_for_status()
        workerinfo = response.json()['workerinfo']
        # TODO generate this path on the server
        workerinfo.update({'WORKING_DIR': os.path.join(workerinfo['FILE_ROOT_FOR_WORKER'], uuid.uuid4().hex)})
        return workerinfo

    def _init_task_run(self):
        url = self.settings['MASTER_URL'] + '/api/task_runs/%s/' % self.settings['RUN_ID']
        response = requests.get(url)
        response.raise_for_status()
        self.task_run = response.json()
        self.logger.debug('Retrieved TaskRun %s' % self.task_run)

    def _get_task_run(self):
        print self.master_url

    def _prepare_working_directory(self, working_dir):
        print 'trying to create %s' % working_dir
        try:
            os.makedirs(working_dir)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(working_dir):
                pass
            else:
                raise

    def _execute(self, stdoutlog, stderrlog):
        task_definition = self.task_run.get('task_definition')
        environment = task_definition.get('environment')
        docker_image = environment.get('docker_image')
        user_command = task_definition.get('command')
        host_dir = self.settings['WORKING_DIR']
        container_dir = '/working_dir'
        
        full_command = [
            'docker',
            'run',
            '--rm',
            '-v',
            '%s:%s:rw' % (host_dir, container_dir),
            '-w',
            container_dir,
            docker_image,
            'sh',
            '-c',
            user_command,
            ]
        self.logger.debug(full_command)
        return subprocess.Popen(full_command, stdout=stdoutlog, stderr=stderrlog)

    def _wait_for_process(self, process, poll_interval_seconds=1, timeout_seconds=86400):
        start_time = datetime.now()
        while True:
            time_running = datetime.now() - start_time
            if time_running.seconds > timeout_seconds:
                raise Exception("Timeout")
            returncode = process.poll()
            if returncode is not None:
                break
            time.sleep(poll_interval_seconds)
        if returncode == 0:
            return
        else:
            err_message = 'Worker process failed with error %s. \nFor more '\
                          'information check the stderr log file at "%s"' \
                          % (str(returncode), self.settings.get('STDERR_LOGFILE'))
            self.logger.error(err_message)
            raise Exception(err_message)

    def _get_args(self):
        parser = self.get_parser()
        return parser.parse_args()

    @classmethod
    def get_parser(self):
        parser = argparse.ArgumentParser(__file__)
        parser.add_argument('--run_id',
                            '-i',
                            required=True,
                            help='ID of TaskRun to be executed')
        parser.add_argument('--run_location_id',
                            '-l',
                            required=True,
                            help='TaskRunLocation ID assigned to this'\
                            'particular run execution. If this doesn\'t'\
                            'match the active ID, results will be ignored.')
        parser.add_argument('--master_url',
                            '-u',
                            required=True,
                            help='URL of the Loom master server')
        return parser

    def _init_filehandler(self):
        self.filehandler = FileHandler(self.settings['MASTER_URL'], logger=self.logger)

    def _init_objecthandler(self):
        self.objecthandler = ObjectHandler(self.settings['MASTER_URL'])
        
    def _init_logger(self):
        self.logger = logging.getLogger("LoomWorker")
        self.logger.setLevel(self.settings['LOG_LEVEL'])
        self.logger.raiseExceptions = True
        formatter = logging.Formatter('%(levelname)s [%(asctime)s] %(message)s')
        handler = self._init_handler()
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        stdout_logger = StreamToLogger(self.logger, logging.INFO)
        sys.stdout = stdout_logger
        stderr_logger = StreamToLogger(self.logger, logging.ERROR)
        sys.stderr = stderr_logger
        
    def _init_handler(self):
        if self.settings.get('STEP_LOGFILE') is None:
            return logging.StreamHandler()
        else:
            if not os.path.exists(os.path.dirname(self.settings['STEP_LOGFILE'])):
                os.makedirs(os.path.dirname(self.settings['STEP_LOGFILE']))
            return logging.FileHandler(self.settings['STEP_LOGFILE'])

    def _add_logfiles(self):
        """Add logfiles for the worker, stdout, and stderr."""
        self.settings.update({'STEP_LOGFILE': os.path.join(self.settings['WORKING_DIR'], 'worker_log.txt')})
        self.settings.update({'STDOUT_LOGFILE': os.path.join(self.settings['WORKING_DIR'], 'stdout_log.txt')})
        self.settings.update({'STDERR_LOGFILE': os.path.join(self.settings['WORKING_DIR'], 'stderr_log.txt')})


# pip entrypoint requires a function with no arguments 
def main():
    TaskRunner().run()

if __name__=='__main__':
    main()
