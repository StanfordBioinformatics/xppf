#!/usr/bin/env python
import argparse
import jsonschema
import os
import re
import requests.exceptions
import yaml

from loomengine import _render_time
from loomengine.common import get_server_url, \
    verify_has_connection_settings, verify_server_is_running, get_token
from loomengine.run_tag import RunTag
from loomengine.run_label import RunLabel
from loomengine_utils.exceptions import APIError, LoomengineUtilsError
from loomengine_utils.connection import Connection
from loomengine_utils.file_utils import FileSet
from loomengine_utils.import_manager import ImportManager
from loomengine_utils.export_manager import ExportManager


class AbstractRunSubcommand(object):

    def __init__(self, args=None, silent=False):
        self._validate_args(args)
        self.args = args
        self.silent = silent
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        token = get_token()
        self.connection = Connection(server_url, token=token)
        try:
            self.storage_settings = self.connection.get_storage_settings()
            self.import_manager = ImportManager(
                self.connection, storage_settings=self.storage_settings)
            self.export_manager = ExportManager(
                self.connection, storage_settings=self.storage_settings)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to initialize client: '%s'" % e)

    @classmethod
    def _validate_args(cls, args):
        pass

    def _print(self, text):
        if not self.silent:
            print text


class RunStart(AbstractRunSubcommand):
    """Run a template.
    """

    @classmethod
    def get_parser(cls, parser=None):
        if parser is None:
            parser = argparse.ArgumentParser(__file__)
        parser.add_argument(
            'template', metavar='TEMPLATE_ID', help='ID of template to run')
        parser.add_argument(
            'inputs', metavar='INPUT=DATA', nargs='*',
            help='pairs of [channel name]=[ID or value of data inputs]')
        parser.add_argument('-n', '--name', metavar='RUN_NAME',
                            help='run name (default is template name)')
        parser.add_argument(
            '-i', '--inputs-file', metavar='INPUTS_FILE',
            help='JSON file with inputs {"channel1": "value1",...}')
        parser.add_argument('-e', '--notify', action='append',
                            metavar='EMAIL/URL',
                            help='recipients of completed run notifications')
        parser.add_argument('-f', '--force-rerun',
                            action='store_true',
                            help='ignore any existing results')
        parser.add_argument('-t', '--tag', metavar='TAG', action='append',
                            help='tag the run when it is started')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='label the run when it is started')
        return parser

    @classmethod
    def _validate_args(cls, args):
        if not args.inputs:
            return
        for input in args.inputs:
            vals = input.split('=')
            if not len(vals) == 2 or vals[0] == '':
                raise SystemExit(
                    'ERROR! Invalid input key-value pair "%s". '
                    'Must be of the form key=value or '
                    'key=value1,value2,...' % input)

    def run(self):
        run_data = {
            'template': self.args.template,
            'user_inputs': self._get_inputs(),
            'notification_addresses': self.args.notify,
            'force_rerun': self.args.force_rerun,
        }
        if self.args.name:
            run_data['name'] = self.args.name
        try:
            run = self.connection.post_run(run_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to start run: '%s'" % e)

        self._print('Created run %s@%s' % (
            run['name'],
            run['uuid']))
        self._apply_tags(run)
        self._apply_labels(run)
        return run

    def _get_inputs(self):
        """Converts command line args into a list of template inputs
        """
        # Convert file inputs to a dict, to make it easier to override
        # them with commandline inputs
        file_inputs = self._get_file_inputs()
        try:
            jsonschema.validate(file_inputs, file_input_schema)
        except jsonschema.ValidationError:
            raise SystemExit("ERROR! Input file was invalid")
        input_dict = {}
        for (channel, input_id) in file_inputs.iteritems():
            input_dict[channel] = input_id

        if self.args.inputs:
            for kv_pair in self.args.inputs:
                (channel, input_id) = kv_pair.split('=')
                input_dict[channel] = self._parse_string_to_nested_lists(
                    input_id)

        inputs = []
        for (channel, contents) in input_dict.iteritems():
            inputs.append({
                'channel': channel,
                'data': {
                    'contents': contents
                }
            })
        return inputs

    def _get_file_inputs(self):
        if not self.args.inputs_file:
            return {}
        else:
            with open(self.args.inputs_file) as f:
                return yaml.load(f)

    def _apply_tags(self, run):
        if not self.args.tag:
            return
        for tagname in self.args.tag:
            tag_data = {'tag': tagname}
            try:
                tag = self.connection.post_run_tag(run.get('uuid'), tag_data)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to create tag: '%s'" % e)
            self._print('Run "%s@%s" has been tagged as "%s"' %
                        (run.get('name'),
                         run.get('uuid'),
                         tag.get('tag')))

    def _apply_labels(self, run):
        if not self.args.label:
            return
        for labelname in self.args.label:
            label_data = {'label': labelname}
            try:
                label = self.connection.post_run_label(
                    run.get('uuid'), label_data)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to create label: '%s'" % e)
            self._print('Run "%s@%s" has been labeled as "%s"' %
                        (run.get('name'),
                         run.get('uuid'),
                         label.get('label')))

    def _parse_string_to_nested_lists(self, value):
        """e.g., convert "[[a,b,c],[d,e],[f,g]]"
        into [["a","b","c"],["d","e"],["f","g"]]
        """
        if not re.match(r'\[.*\]', value.strip()):
            if '[' in value or ']' in value or ',' in value:
                raise Exception('Missing outer brace')
            elif len(value.strip()) == 0:
                raise Exception('Missing value')
            else:
                terms = value.split(',')
                terms = [term.strip() for term in terms]
                if len(terms) == 1:
                    return terms[0]
                else:
                    return terms

        # remove outer braces
        value = value[1:-1]
        terms = []
        depth = 0
        leftmost = 0
        first_open_brace = None
        break_on_commas = False
        for i in range(len(value)):
            if value[i] == ',' and depth == 0:
                terms.append(
                    self._parse_string_to_nested_lists(value[leftmost:i]))
                leftmost = i+1
            if value[i] == '[':
                if first_open_brace is None:
                    first_open_brace = i
                depth += 1
            if value[i] == ']':
                depth -= 1
                if depth < 0:
                    raise Exception('Unbalanced close brace')
            i += i
        if depth > 0:
            raise Exception('Expected "]"')
        terms.append(
            self._parse_string_to_nested_lists(value[leftmost:len(value)]))
        return terms


class RunRestart(RunStart):
    """Start a new run based on an existing run's template and inputs.
    """

    @classmethod
    def get_parser(cls, parser=None):
        if parser is None:
            parser = argparse.ArgumentParser(__file__)
        parser.add_argument(
            'run', metavar='RUN_ID', help='ID of run to restart')
        parser.add_argument('inputs', metavar='INPUT=DATA', nargs='*',
                            help='override inputs, pairs of '
                            '[channel name]=[ID or value of data inputs]')
        parser.add_argument('-n', '--name', metavar='RUN_NAME',
                            help='run name (default is template name)')
        parser.add_argument('-i', '--inputs-file', metavar='INPUTS_FILE',
                            help='JSON file with inputs '
                            '{"channel1": "value1",...}')
        parser.add_argument('-e', '--notify', action='append',
                            metavar='EMAIL/URL',
                            help='recipients of completed run notifications')
        parser.add_argument('-f', '--force-rerun',
                            action='store_true',
                            help='ignore any existing results')
        parser.add_argument('-t', '--tag', metavar='TAG', action='append',
                            help='tag the run when it is started')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='label the run when it is started')
        return parser

    def run(self):
        try:
            run = self.connection.get_run_index(
                query_string=self.args.run,
                min=0, max=1)[0]
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run list: '%s'" % e)
        try:
            run = self.connection.get_run(run.get('uuid'))
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run: '%s'" % e)
        run_data = {
            'template': run.get('template'),
            'user_inputs': self._get_inputs(run.get('inputs')),
            'notification_addresses': self.args.notify,
            'force_rerun': self.args.force_rerun,
        }
        if self.args.name:
            run_data['name'] = self.args.name
        try:
            run = self.connection.post_run(run_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to restart run: '%s'" % e)
        self._print('Created run %s@%s' % (
            run['name'],
            run['uuid']))
        self._apply_tags(run)
        self._apply_labels(run)

        return run

    def _get_inputs(self, old_inputs):
        """Converts command line args into a list of template inputs
        """
        # Convert inputs to dict to facilitate overriding by channel name
        # Also, drop DataNode ID and keep only contents.
        input_dict = {}
        for input in old_inputs:
            # Strip out DataNode UUID and URL
            input['data'] = {'contents': input['data']['contents']}
            input_dict[input['channel']] = input

        file_inputs = self._get_file_inputs()
        try:
            jsonschema.validate(file_inputs, file_input_schema)
        except jsonschema.ValidationError:
            raise SystemExit("ERROR! User inputs file is not valid")
        for (channel, input_id) in file_inputs.iteritems():
            input_dict[channel] = {
                'channel': channel,
                'data': {'contents': input_id}
            }
        # Override with cli user inputs if specified
        if self.args.inputs:
            for kv_pair in self.args.inputs:
                (channel, input_id) = kv_pair.split('=')
                input_dict[channel] = {
                    'channel': channel,
                    'data': {
                        'contents':
                        self._parse_string_to_nested_lists(input_id)}
                }
        return input_dict.values()


class RunImport(AbstractRunSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'run',
            metavar='RUN_FILE',
            help='run to be imported, in YAML format',
            nargs='+')
        parser.add_argument(
            '-k', '--link-files', action='store_true',
            default=False,
            help='link to existing files instead of copying to storage '
            'managed by Loom')
        parser.add_argument('-r', '--retry', action='store_true',
                            default=False,
                            help='allow retries if there is a failure '
                            'connecting to storage')
        parser.add_argument('-t', '--tag', metavar='TAG', action='append',
                            help='tag the run when it is imported')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='label the run when it is imported')
        return parser

    def run(self):
        imported_runs = []
        try:
            for run_file in FileSet(
                    self.args.run, self.storage_settings,
                    retry=self.args.retry):
                try:
                    run = self.import_manager.import_run(
                        run_file,
                        retry=self.args.retry,
                        link_files=self.args.link_files)
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to import run: '%s'" % e)
                self._apply_tags(run)
                self._apply_labels(run)
                imported_runs.append(run)
        except APIError as e:
            raise SystemExit(
                'ERROR! An external API failed. This may be transient. '
                'Try again, and consider using "--retry", especially '
                'if this step is automated. Original error: "%s"' % e)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! %s" % e.message)
        return imported_runs

    def _apply_tags(self, run):
        if not self.args.tag:
            return
        for tagname in self.args.tag:
            tag_data = {'tag': tagname}
            try:
                tag = self.connection.post_run_tag(run.get('uuid'), tag_data)
            except LoomengineUtilsError as e:
                raise SystemExit('ERROR! Failed to create tag: "%s"' % e)
            self._print('Run "%s@%s" has been tagged as "%s"' %
                        (run.get('name'),
                         run.get('uuid'),
                         tag.get('tag')))

    def _apply_labels(self, run):
        if not self.args.label:
            return
        for labelname in self.args.label:
            label_data = {'label': labelname}
            try:
                label = self.connection.post_run_label(
                    run.get('uuid'), label_data)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to create label: '%s'" % e)
            self._print('Run "%s@%s" has been labeled as "%s"' %
                        (run.get('name'),
                         run.get('uuid'),
                         label.get('label')))


class RunExport(AbstractRunSubcommand):
    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'run_ids',
            nargs='+',
            metavar='RUN_ID', help='ID of run to be exported')
        parser.add_argument(
            '-d', '--destination-directory',
            metavar='DESTINATION_DIRECTORY',
            help='destination directory')
        parser.add_argument(
            '-k', '--link-files', action='store_true',
            default=False,
            help='do not export file, just metadata with link '
            'to original file')
        parser.add_argument(
            '-r', '--retry', action='store_true',
            default=False,
            help='allow retries if there is a failure '
            'connecting to storage')
        return parser

    def run(self):
        runs = []
        run_uuids = set()
        for run_id in self.args.run_ids:
            found_at_least_one_match = False
            offset = 0
            limit = 10
            while True:
                try:
                    data = self.connection.get_run_index_with_limit(
                        limit=limit, offset=offset,
                        query_string=run_id)
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to get run list: '%s'" % e)
                for run in data['results']:
                    found_at_least_one_match = True
                    if run.get('uuid') not in run_uuids:
                        run_uuids.add(run.get('uuid'))
                        runs.append(run)
                if data.get('next'):
                    offset += limit
                else:
                    break
            if not found_at_least_one_match:
                raise SystemExit('ERROR! No runs matched %s"' % run_id)
        if len(runs) > 1:
            try:
                return self.export_manager.bulk_export_runs(
                    runs,
                    destination_directory=self.args.destination_directory,
                    retry=self.args.retry,
                    link_files=self.args.link_files
                )
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to export runs: '%s'" % e)
        else:
            try:
                return self.export_manager.export_run(
                    runs[0],
                    destination_directory=self.args.destination_directory,
                    retry=self.args.retry,
                    link_files=self.args.link_files,
                )
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to export run: '%s'" % e)


class RunList(AbstractRunSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'run_id',
            nargs='?',
            metavar='RUN_ID',
            help='name or ID of run(s) to list.')
        parser.add_argument(
            '-d', '--detail',
            action='store_true',
            help='show detailed view of runs')
        parser.add_argument(
            '-a', '--all',
            action='store_true',
            help='list all runs, including nested children '
            '(ignored when RUN_ID is given)')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='filter by label')
        return parser

    def run(self):
        if self.args.run_id:
            parent_only = False
        else:
            parent_only = not self.args.all
        offset = 0
        limit = 10
        while True:
            try:
                data = self.connection.get_run_index_with_limit(
                    query_string=self.args.run_id,
                    limit=limit, offset=offset,
                    labels=self.args.label, parent_only=parent_only)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get run list: '%s'" % e)
            if offset == 0:
                self._print('[showing %s runs]' % data.get('count'))
            self._list_runs(data['results'])
            if data.get('next'):
                offset += limit
            else:
                break
        return data['results']

    def _list_runs(self, runs):
        for run in runs:
            self._print(self._render_run(run))

    def _render_run(self, run):
        run_identifier = '%s@%s' % (run['name'], run['uuid'])
        if self.args.detail:
            text = '---------------------------------------\n'
            text += 'Run: %s\n' % run_identifier
            text += '  - Created: %s\n' % _render_time(run['datetime_created'])
            text += '  - Status: %s\n' % run.get('status')
            if run.get('steps'):
                text += '  - Steps:\n'
                for step in run['steps']:
                    text += '    - %s@%s (%s)\n' % (
                        step['name'], step['uuid'], step.get('status'))
        else:
            text = "Run: %s (%s)" % (run_identifier, run.get('status'))
        return text


class RunKill(AbstractRunSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'run_id',
            metavar='RUN_IDENTIFIER',
            help='name or ID of run to kill.')
        parser.add_argument('-y', '--yes', action='store_true',
                            default=False,
                            help='kill without prompting for confirmation')
        return parser

    def run(self):
        try:
            data = self.connection.get_run_index(
                query_string=self.args.run_id,
                min=1, max=1)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run list: '%s'" % e)
        run = data[0]
        run_id = "%s@%s" % (run['name'], run['uuid'])
        if not self.args.yes:
            user_input = raw_input(
                'Do you really want to permanently kill run "%s"?\n'
                '(y)es, (n)o: ' % run_id)
            if user_input.lower() == 'n':
                raise SystemExit("Skipping run")
            elif user_input.lower() == 'y':
                pass
            else:
                raise SystemExit(
                    'ERROR! Unrecognized response "%s"' % user_input)
        try:
            self.connection.kill_run(run['uuid'])
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to kill run: '%s'" % e)
        self._print("Killed run %s" % run_id)


class RunDelete(AbstractRunSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'run_id',
            metavar='RUN_IDENTIFIER',
            help='name or ID of run to kill.')
        parser.add_argument('-y', '--yes', action='store_true',
                            default=False,
                            help='delete without prompting for confirmation')
        parser.add_argument('-c', '--keep-children', action='store_true',
                            default=False,
                            help='do not delete child run')
        parser.add_argument('-r', '--keep-result-files', action='store_true',
                            default=False,
                            help='do not delete run result files')
        return parser

    def run(self):
        try:
            data = self.connection.get_run_index(
                query_string=self.args.run_id,
                min=1, max=1)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run list: '%s'" % e)
        self._delete_run(data[0])

    def _delete_run(self, run):
        run_id = "%s@%s" % (run['name'], run['uuid'])
        run_children_to_delete = []
        if not self.args.keep_children and run.get('steps'):
            for step in run.get('steps'):
                try:
                    run_children_to_delete.append(
                        self.connection.get_run_index(
                            query_string='@%s' % step['uuid'],
                            min=1, max=1)[0]
                    )
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to delete run: '%s'" % e)

        # Placing the list in reverse order makes it easier
        # to handle outputs produced by one step and used by
        # another where both steps are being deleted.
        run_children_to_delete = sorted(
            run_children_to_delete,
            key=lambda x: x['datetime_created'], reverse=True)
        run_outputs_to_delete = []
        # Only delete outputs on leaf nodes. Otherwise we will
        # try to delete them more than once. Non-leaf nodes pointing
        # to this output have to be deleted before we are allowed to
        # delete the leaf anyway, so outputs are always referenced by
        # at least the leaf leaf until the leaf is deleted.
        if run.get('is_leaf'):
            for output in run.get('outputs', []):
                if output.get('type') != 'file' \
                   or not self.args.keep_result_files:
                    try:
                        data_node = self.connection.get_data_node(
                            output['data']['uuid'], expand=True)
                    except LoomengineUtilsError as e:
                        raise SystemExit(
                            "ERROR! Failed to get data node: '%s'" % e)
                    run_outputs_to_delete.extend(
                        self._parse_data_objects_from_data_node_contents(
                            data_node.get('contents')))
            if not self.args.keep_result_files:
                for task in run.get('tasks', []):
                    try:
                        task = self.connection.get_task(task['uuid'])
                    except LoomengineUtilsError as e:
                        raise SystemExit("ERROR! Failed to get task: '%s'" % e)
                    for task_attempt in task.get('all_task_attempts', []):
                        try:
                            task_attempt = self.connection.get_task_attempt(
                                task_attempt['uuid'])
                        except LoomengineUtilsError as e:
                            raise SystemExit(
                                "ERROR! Failed to get task attempt: '%s'" % e)
                        for log_file in task_attempt.get('log_files', []):
                            if log_file.get('data_object'):
                                run_outputs_to_delete.append(
                                    log_file['data_object'])
        if not self.args.yes:
            user_input = raw_input(
                'Do you really want to permanently delete run "%s"?\n'
                '(y)es, (n)o: ' % run_id)
            if user_input.lower() == 'n':
                raise SystemExit("Skipping run")
            elif user_input.lower() == 'y':
                pass
            else:
                raise SystemExit('Unrecognized response "%s"' % user_input)
        try:
            dependencies = self.connection.get_run_dependencies(
                run.get('uuid'))
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run dependencies: '%s'" % e)

        if len(dependencies['runs']) == 0:
            try:
                self.connection.delete_run(run.get('uuid'))
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to delete run: '%s'" % e)
            self._print("Deleted run %s" % run_id)
            for run in run_children_to_delete:
                self._delete_run(run)
            for data_object in run_outputs_to_delete:
                self._delete_data_object(data_object)
        else:
            self._print(
                "Cannot delete run %s because it is contained by other "
                "run(s). You must delete the following runs before "
                "deleting this run." % run_id)
            for run in dependencies.get('runs', []):
                self._print("  run %s@%s" % (run['name'], run['uuid']))

    def _delete_data_object(self, data_object):
        try:
            dependencies = self.connection.get_data_object_dependencies(
                data_object['uuid'])
        except LoomengineUtilsError as e:
            raise SystemExit(
                "ERROR! Failed to get data object dependencies: '%s'" % e)
        if len(dependencies['runs']) == 0 \
           and len(dependencies['templates']) == 0:
            if data_object.get('type') == 'file':
                file_id = "%s@%s" % (
                    data_object['value']['filename'], data_object['uuid'])
                if not self.args.yes:
                    user_input = raw_input(
                        'Do you really want to delete result file "%s"?\n'
                        '(y)es, (n)o: ' % file_id)
                    if user_input.lower() == 'n':
                        raise SystemExit("Skipping file")
                    elif user_input.lower() == 'y':
                        pass
                    else:
                        raise SystemExit(
                            'Unrecognized response "%s"' % user_input)
                try:
                    self.connection.delete_data_object(data_object['uuid'])
                except LoomengineUtilsError as e:
                    raise SystemExit(
                        "ERROR! Failed to delete data object: '%s'" % e)
                self._print("Deleted file %s" % file_id)
            else:
                try:
                    self.connection.delete_data_object(data_object['uuid'])
                except LoomengineUtilsError as e:
                    raise SystemExit(
                        "ERROR! Failed to delete data object: '%s'" % e)
        else:
            if len(dependencies['runs']) > 0:
                self._print("Cannot delete file %s "
                            "because it is contained by other run(s). "
                            "You must delete the following runs "
                            "before deleting this file." % run_id)
                for run in dependencies.get('runs', []):
                    self._print("  run %s@%s" % (run['name'], run['uuid']))
            if len(dependencies['templates']) > 0:
                self._print("Cannot delete file %s "
                            "because it is contained by other template(s). "
                            "You must delete the following templates "
                            "before deleting this file." % run_id)
                for template in dependencies.get('templates', []):
                    self._print("  template %s@%s" % (
                        template['name'], template['uuid']))

    def _parse_data_objects_from_data_node_contents(self, contents):
        if not isinstance(contents, list):
            if not contents:
                return []
            else:
                return [contents]
        data_objects = []
        for child in contents:
            data_objects.extend(
                self._parse_data_objects_from_data_node_contents(child))
        return data_objects


class RunClient(object):
    """Handles subcommands under "run" on the main parser
    """

    def __init__(self, args=None, silent=False):
        if args is None:
            args = self._get_args()
        self.args = args
        self.silent = silent

    def _get_args(self):
        parser = self.get_parser()
        return parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):
        if parser is None:
            parser = argparse.ArgumentParser(__file__)

        subparsers = parser.add_subparsers()

        start_subparser = subparsers.add_parser(
            'start', help='start a new run')
        RunStart.get_parser(start_subparser)
        start_subparser.set_defaults(SubSubcommandClass=RunStart)

        restart_subparser = subparsers.add_parser(
            'restart', help="start a new run, using an existing run's "
            "template and inputs")
        RunRestart.get_parser(restart_subparser)
        restart_subparser.set_defaults(SubSubcommandClass=RunRestart)

        kill_subparser = subparsers.add_parser(
            'kill', help='kill run')
        RunKill.get_parser(kill_subparser)
        kill_subparser.set_defaults(SubSubcommandClass=RunKill)

        list_subparser = subparsers.add_parser(
            'list', help='list runs')
        RunList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubcommandClass=RunList)

        tag_subparser = subparsers.add_parser('tag', help='manage run tags')
        RunTag.get_parser(tag_subparser)
        tag_subparser.set_defaults(SubSubcommandClass=RunTag)

        label_subparser = subparsers.add_parser(
            'label', help='manage run labels')
        RunLabel.get_parser(label_subparser)
        label_subparser.set_defaults(SubSubcommandClass=RunLabel)

        import_subparser = subparsers.add_parser(
            'import', help='import runs')
        RunImport.get_parser(import_subparser)
        import_subparser.set_defaults(SubSubcommandClass=RunImport)

        export_subparser = subparsers.add_parser(
            'export', help='export runs')
        RunExport.get_parser(export_subparser)
        export_subparser.set_defaults(SubSubcommandClass=RunExport)

        delete_subparser = subparsers.add_parser(
            'delete', help='delete run')
        RunDelete.get_parser(delete_subparser)
        delete_subparser.set_defaults(SubSubcommandClass=RunDelete)

        return parser

    def run(self):
        return self.args.SubSubcommandClass(
            self.args, silent=self.silent).run()


file_input_schema = {
    "type": "object",
    "additionalProperties": {
        "oneOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "array"},
        ],
    },
}


if __name__ == '__main__':
    RunClient().run()
