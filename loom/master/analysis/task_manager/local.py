
import logging
import os
import requests
import subprocess
import sys

from django.conf import settings


logger = logging.getLogger('LoomDaemon')

TASK_RUNNER_EXECUTABLE = os.path.abspath(
    os.path.join(
        settings.BASE_DIR,
        '../../worker/task_runner.py',
        ))


class LocalTaskManager:

    @classmethod
    def run(cls, task_run, run_location_id, resources):
        cmd = [sys.executable,
               TASK_RUNNER_EXECUTABLE,
               '--run_id',
               task_run._id,
               '--run_location_id',
               run_location_id,
               '--master_url',
               settings.MASTER_URL_FOR_WORKER]
        logger.debug(cmd)
        proc = subprocess.Popen(cmd, stderr=subprocess.STDOUT)
