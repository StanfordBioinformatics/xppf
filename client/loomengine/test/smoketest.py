from datetime import datetime
import os
import shutil
import tempfile
import time
import unittest
import uuid
import loomengine.run
import loomengine.file_client
import loomengine.template
import loomengine.example


class SmokeTest(unittest.TestCase):

    def setUp(self):
        self.template_name = 'hello_world'
        self.run_name = self.template_name
        self.template_tag = 'smoke-test-%s' % uuid.uuid4()
        self.run_tag = 'smoke-test-%s' % uuid.uuid4()
        self.tempdir = tempfile.mkdtemp()
        parser = loomengine.example.Example.get_parser()
        args = parser.parse_args(
            ['export', self.template_name, '-d', self.tempdir])
        example_export_client = loomengine.example.Example(args, silent=True)
        example_export_client.run()
        self.template_path = os.path.join(
            self.tempdir, self.template_name, self.template_name+'.yaml')

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        parser = loomengine.run.RunClient.get_parser()
        args = parser.parse_args(['delete', '-y', ':%s' % self.run_tag])
        run_client = loomengine.run.RunClient(args, silent=True)
        try:
            run_client.run()
        except SystemExit:
            pass

        args = parser.parse_args(['list', ':%s' % self.run_tag])
        run_list_client = loomengine.run.RunClient(args, silent=True)
        self._poll_for_n(run_list_client, n=0,
                         error_message='Failed to delete run')

        parser = loomengine.template.Template.get_parser()
        args = parser.parse_args(['delete', '-y', ':%s' % self.template_tag])
        template_client = loomengine.template.Template(args, silent=True)
        try:
            template_client.run()
        except SystemExit:
            pass

        args = parser.parse_args(['list', ':%s' % self.template_tag])
        template_list_client = loomengine.template.Template(args, silent=True)
        self._poll_for_n(template_list_client, n=0,
                         error_message='Failed to delete template')

    def testExample(self):
        parser = loomengine.template.Template.get_parser()
        args = parser.parse_args(['import', self.template_path,
                                  '-f', '-r', '-t', self.template_tag])
        template_import_client = loomengine.template.Template(
            args, silent=True)
        template_import_client.run()

        args = parser.parse_args(['list', ':%s' % self.template_tag])
        template_list_client = loomengine.template.Template(args, silent=True)
        self._poll_for_n(template_list_client, n=1,
                         error_message='Failed to import template')

        parser = loomengine.run.RunClient.get_parser()
        args = parser.parse_args(['start', ':%s' % self.template_tag, '-t',
                                  self.run_tag, '-f'])

        run_client = loomengine.run.RunClient(args, silent=True)
        run_client.run()

        args = parser.parse_args(['list', ':%s' % self.run_tag])
        run_list_client = loomengine.run.RunClient(args, silent=True)
        self._poll_for_n(run_list_client, n=1,
                         error_message='Failed to start run')
        self._poll_for_run_success(run_list_client,
                                   error_message='Run failed')

    def _poll_for_n(self, client, n=1, timeout_seconds=30,
                    error_message='ERROR! Timed out'):
        start = datetime.now()
        while True:
            try:
                result = client.run()
                if len(result) == n:
                    return result
            except SystemExit:
                pass
            if (datetime.now() - start).total_seconds() < timeout_seconds:
                time.sleep(timeout_seconds/10)
                continue
            else:
                raise Exception(error_message)

    def _poll_for_run_success(
            self, client, timeout_seconds=1800, sleep_seconds=20,
            error_message='ERROR! Timed out'):
        start = datetime.now()
        while True:
            try:
                result = client.run()
                assert len(result) == 1, \
                    'Expected 1 run, found %s' % len(result)
                if result[0].get('status') == 'Finished':
                    return result[0]
                elif result[0].get('status') == 'Failed':
                    raise Exception("Run failed")
                elif result[0].get('status') == 'Killed':
                    raise Exception("Run was killed")
                elif result[0].get('status') == 'Running':
                    pass
                elif result[0].get('status') != 'Waiting':
                    raise Exception(
                        'Unknown run status "%s"' % result[0].get('status'))
            except SystemExit:
                pass
            if (datetime.now() - start).total_seconds() < timeout_seconds:
                time.sleep(sleep_seconds)
                continue
            else:
                raise Exception(error_message)


if __name__ == '__main__':
    unittest.main()
