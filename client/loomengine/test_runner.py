#!/usr/bin/env python
import argparse
from datetime import datetime
import os
import re
import subprocess
import sys
import time
import unittest


test_root = os.path.join(os.path.dirname(__file__), 'test')


class IntegrationTestFailure(Exception):
    pass


class TestRunner(object):

    def __init__(self, args=None, silent=False):
        # Parse arguments
        if args is None:
            args = _get_args()
        self.args = args
        self.silent = silent
        self._set_run_function()

    def _set_run_function(self):
        # Map user input command to method
        commands = {
            'smoke': self.smoke_test,
            'integration': self.integration_test,
            'unit': self.unit_tests,
        }
        self.run = commands[self.args.command]

    def smoke_test(self):
        if not self._is_server_running():
            raise SystemExit('ERROR! The client must be connected to a '
                             'running Loom server to run smoke tests. '
                             'Use "loom server start" to start a new server.')
        suite = unittest.TestLoader().discover(
            test_root, pattern='smoketest*.py')
        test_result = unittest.TextTestRunner().run(suite)
        if not test_result.wasSuccessful():
            raise SystemExit(1)

    def integration_test(self):
        if not self._is_server_running():
            raise SystemExit('ERROR! The client must be connected to a '
                             'running Loom server to run integration tests. '
                             'Use "loom server start" to start a new server.')
        suite = unittest.TestLoader().discover(
            test_root, pattern='integrationtest*.py')
        test_result = unittest.TextTestRunner().run(suite)
        if not test_result.wasSuccessful():
            raise SystemExit(1)

    def unit_tests(self):
        suite = unittest.TestLoader().discover(test_root, pattern='test*.py')
        test_result = unittest.TextTestRunner().run(suite)
        if not test_result.wasSuccessful():
            raise SystemExit(1)

    def _is_server_running(self):
        loom_executable = sys.argv[0]
        # No need for text output. Returncode tells us if server is running.
        with open('/dev/null', 'w') as devnull:
            returncode = subprocess.call([loom_executable, 'server', 'status'],
                                         env=os.environ,
                                         stdout=devnull, stderr=devnull)
        if returncode == 0:
            return True
        else:
            return False


def get_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser(__file__)

    subparsers = parser.add_subparsers(dest='command')

    unit_parser = subparsers.add_parser(
        'unit',
        help='run unit tests for the Loom client')

    smoke_parser = subparsers.add_parser(
        'smoke',
        help='run smoke tests (requires a running Loom server)')

    integration_parser = subparsers.add_parser(
        'integration',
        help='run integration tests (requires a running Loom server)')
    return parser


def _get_args():
    parser = get_parser()
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    TestRunner().run()
