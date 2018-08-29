from datetime import datetime
import os
import requests
import shutil
import tempfile
import time
import unittest
import uuid
import loomengine.run
import loomengine.file_client
import loomengine.template
import loomengine.example


class TestExamples(unittest.TestCase):

    examples = [
        'hello_world',
        'join_two_words',
        'capitalize_words',
        'join_array_of_words',
        'split_words_into_array',
        'add_then_multiply',
        'building_blocks',
        'search_file',
        'word_combinations',
        'sentence_scoring',
    ]

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.file_tags = set()
        self.template_tags = set()
        self.run_tags = set()
        self.file_uuids = set()
        self.example_parser = loomengine.example.Example.get_parser()
        self.template_parser = loomengine.template.Template.get_parser()
        self.run_parser = loomengine.run.RunClient.get_parser()
        self.file_parser = loomengine.file_client.FileClient.get_parser()

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        for run_tag in self.run_tags:
            args = self.run_parser.parse_args(
                ['delete', '-y', ':%s' % run_tag])
            run_client = loomengine.run.RunClient(args, silent=True)
            try:
                run_client.run()
            except SystemExit:
                pass
            args = self.run_parser.parse_args(['list', ':%s' % run_tag])
            run_list_client = loomengine.run.RunClient(args, silent=True)
            self._poll_for_n(run_list_client, n=0,
                             error_message='Failed to delete run')

        for template_tag in self.template_tags:
            args = self.template_parser.parse_args(
                ['delete', '-y', ':%s' % template_tag])
            template_client = loomengine.template.Template(args, silent=True)
            try:
                template_client.run()
            except SystemExit:
                pass
            args = self.template_parser.parse_args(
                ['list', ':%s' % template_tag])
            template_list_client = loomengine.template.Template(
                args, silent=True)
            self._poll_for_n(template_list_client, n=0,
                             error_message='Failed to delete template')

    def testExamples(self):
        # self._check_examples_list()
        run_tags = []
        for example in self.examples:
            self._export_example_to_tempdir(example)
            template_tag = self._import_template(example)
            run_tags.append(self._start_run(example, template_tag))
        self._wait_for_runs_to_succeed()

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

    def _check_examples_list(self):
        # Verify that examples in this test match those listed by the client.
        args = self.example_parser.parse_args(['list'])
        example_list_client = loomengine.example.Example(args, silent=True)
        result = example_list_client.run()
        examples_from_client = set([item[0] for item in result])
        examples_from_test = set(self.examples)
        self.assertEqual(examples_from_client, examples_from_test)

    def _export_example_to_tempdir(self, example):
        args = self.example_parser.parse_args(
            ['export', example, '-d', self.tempdir])
        example_client = loomengine.example.Example(args, silent=True)
        example_client.run()

    def _import_template(self, example):
        template_tag = 'integration-test-%s' % uuid.uuid4()
        template_path = os.path.join(
            self.tempdir, example, example+'.yaml')
        args = self.template_parser.parse_args(
            ['import', template_path, '-f', '-r', '-t', template_tag])
        template_import_client = loomengine.template.Template(
            args, silent=True)
        template_import_client.run()
        args = self.template_parser.parse_args(['list', ':%s' % template_tag])
        template_list_client = loomengine.template.Template(args, silent=True)
        result = self._poll_for_n(template_list_client, n=1,
                                  error_message='Failed to import template')
        template = requests.get(result[0]['url']).json()
        self._get_files_from_template(template)
        self.template_tags.add(template_tag)
        return template_tag

    def _start_run(self, example, template_tag):
        run_tag = 'integration-test-%s' % uuid.uuid4()
        args = self.run_parser.parse_args(
            ['start', ':%s' % template_tag, '-t', run_tag, '-f'])
        run_client = loomengine.run.RunClient(args, silent=True)
        run_client.run()

        args = self.run_parser.parse_args(['list', ':%s' % run_tag])
        run_list_client = loomengine.run.RunClient(args, silent=True)
        self._poll_for_n(run_list_client, n=1,
                         error_message='Failed to start run')
        self.run_tags.add(run_tag)
        return run_tag

    def _wait_for_runs_to_succeed(self):
        for run_tag in self.run_tags:
            self._wait_for_run_to_succeed(run_tag)

    def _wait_for_run_to_succeed(self, run_tag):
        args = self.run_parser.parse_args(['list', ':%s' % run_tag])
        run_list_client = loomengine.run.RunClient(args, silent=True)
        self._poll_for_run_success(run_list_client,
                                   error_message='Run failed')

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
                elif result[0].get('status') == 'Waiting':
                    pass
                elif result[0].get('status') == 'Running':
                    pass
                else:
                    raise Exception(
                        'Unknown run status "%s"' % result[0].get('status'))
            except SystemExit:
                pass
            if (datetime.now() - start).total_seconds() < timeout_seconds:
                time.sleep(sleep_seconds)
                continue
            else:
                raise Exception(error_message)

    def _get_files_from_template(self, template):
        self._get_files_from_inputs(template)
        for step in template.get('steps', []):
            self._get_files_from_template(step)

    def _get_files_from_inputs(self, template):
        for input in template.get('inputs', []):
            if input.get('type') == 'file' and input.get('data'):
                self._get_files_from_data_contents(input['data']['contents'])

    def _get_files_from_data_contents(self, contents):
        if contents is None:
            return
        if isinstance(contents, list):
            for item in contents:
                self._get_files_from_data_contents(item)
        else:
            self.file_uuids.add(contents['uuid'])


if __name__ == '__main__':
    unittest.main()
