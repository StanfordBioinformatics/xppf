#!/usr/bin/env python

from datetime import datetime
import json
import os
import requests
import shutil
import subprocess
import tempfile
import time
import unittest

from loom.common import fixtures
from loom.common.testserver import TestServer
from loom.worker.task_runner import TaskRunner

class TestTaskRunner(unittest.TestCase):
    pass

    """
    def setUp(self):
        self.test_server = TestServer()
        self.test_server.start()
        self._run_hello_world()

        r = requests.get(self.test_server.server_url+'/api/step_runs/')
        self.step1_run_id = r.json()['step_runs'][0].get('_id')

        self.file_root = tempfile.mkdtemp()

        parser = StepRunner._get_parser()
        args = parser.parse_args(['--run_id', self.step1_run_id, '--master_url', self.test_server.server_url])
        self.step_runner = StepRunner(args=args)
        self.step_runner.settings['WORKING_DIR'] = self.file_root
        
        self.stdout_filename = os.path.join(self.file_root, 'stdout.txt')
        self.stderr_filename = os.path.join(self.file_root, 'stderr.txt')

    def tearDown(self):
        shutil.rmtree(self.file_root)
        self.test_server.stop()

    def _run_hello_world(self):
        url = self.test_server.server_url+'/api/submitworkflow/'
        response = requests.post(url, data=json.dumps(fixtures.hello_world_workflow_struct))
        self.assertEqual(response.status_code, 201, 'Expected 201 but got %d trying to post to %s' % (response.status_code, url))
        self.test_server.dry_run_job_queues()

    # Given steprun ID, retrieve the steprun
    def test_get_step_run(self):
        step_run = self.step_runner.step_run
        self.assertEqual(step_run.get('_id'), self.step1_run_id)

    def test_execute(self):
        with open(self.stdout_filename, 'w') as stdoutlog:
            with open(self.stderr_filename, 'w') as stderrlog:
                process = self.step_runner._execute(stdoutlog, stderrlog)
        self.step_runner._wait_for_process(process)
   """
    
if __name__=='__main__':
    unittest.main()
