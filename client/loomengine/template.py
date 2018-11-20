#!/usr/bin/env python
import argparse
import glob
import os
from requests.exceptions import HTTPError
import sys
import yaml

from loomengine import _render_time
from loomengine.common import verify_server_is_running, get_server_url, \
    verify_has_connection_settings, get_token
from loomengine.template_tag import TemplateTag
from loomengine.template_label import TemplateLabel
from loomengine_utils.exceptions import LoomengineUtilsError
from loomengine_utils.connection import Connection
from loomengine_utils.file_utils import FileSet, File
from loomengine_utils.import_manager import ImportManager
from loomengine_utils.export_manager import ExportManager


class AbstractTemplateSubcommand(object):

    def __init__(self, args, silent=False):
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
                self.connection,
                storage_settings=self.storage_settings, silent=silent)
            self.export_manager = ExportManager(
                self.connection,
                storage_settings=self.storage_settings, silent=silent)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to initialize client: '%s'" % e)

    def _print(self, text):
        if not self.silent:
            print text


class TemplateImport(AbstractTemplateSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'template',
            metavar='TEMPLATE_FILE',
            help='template to be imported, in YAML format',
            nargs='+')
        parser.add_argument(
            '-c', '--comments',
            metavar='COMMENTS',
            help='add comments to the template')
        parser.add_argument(
            '-k', '--link-files', action='store_true',
            default=False,
            help='link to existing files instead of copying to storage '
            'managed by Loom')
        parser.add_argument('-f', '--force-duplicates', action='store_true',
                            default=False,
                            help='force upload even if another template with '
                            'the same name and md5 exists')
        parser.add_argument('-r', '--retry', action='store_true',
                            default=False,
                            help='allow retries if there is a failure')
        parser.add_argument('-t', '--tag', metavar='TAG', action='append',
                            help='tag the template when it is created')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='label the template when it is created')
        return parser

    def run(self):
        imported_templates = []
        try:
            for template_file in FileSet(
                    self.args.template, self.storage_settings,
                    retry=self.args.retry):
                try:
                    template = self.import_manager.import_template(
                        template_file,
                        comments=self.args.comments,
                        force_duplicates=self.args.force_duplicates,
                        retry=self.args.retry,
                        link_files=self.args.link_files)
                except LoomengineUtilsError as e:
                    msg = str(e)
                    if not msg:
                        msg = e.__class__
                    raise SystemExit(
                        "ERROR! Failed to import template: '%s'" % msg)
                self._apply_tags(template)
                self._apply_labels(template)
                imported_templates.append(template)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! %s" % e)
        return imported_templates

    def _apply_tags(self, template):
        if not self.args.tag:
            return
        for tagname in self.args.tag:
            tag_data = {'tag': tagname}
            try:
                tag = self.connection.post_template_tag(
                    template.get('uuid'), tag_data)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to create tag: '%s'" % e)
            self._print('Template "%s@%s" has been tagged as "%s"' %
                        (template.get('name'),
                         template.get('uuid'),
                         tag.get('tag')))

    def _apply_labels(self, template):
        if not self.args.label:
            return
        for labelname in self.args.label:
            label_data = {'label': labelname}
            try:
                label = self.connection.post_template_label(
                    template.get('uuid'), label_data)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to create label: '%s'" % e)
            self._print('Template "%s@%s" has been labeled as "%s"' %
                        (template.get('name'),
                         template.get('uuid'),
                         label.get('label')))


class TemplateExport(AbstractTemplateSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'template_ids',
            nargs='+',
            metavar='TEMPLATE_ID', help='template(s) to be exported')
        parser.add_argument(
            '-d', '--destination-directory',
            metavar='DESTINATION_DIRECTORY',
            help='destination directory')
        parser.add_argument(
            '-e', '--editable', action='store_true',
            default=False,
            help='exclude uuids so that you can edit the template '
            'and import a new version')
        parser.add_argument(
            '-k', '--link-files', action='store_true',
            default=False,
            help='do not export files, just metadata '
            'with link to original file')
        parser.add_argument(
            '-r', '--retry', action='store_true',
            default=False,
            help='allow retries if there is a failure')
        return parser

    def run(self):
        templates = []
        template_uuids = set()
        for template_id in self.args.template_ids:
            found_at_least_one_match = False
            offset = 0
            limit = 10
            while True:
                try:
                    data = self.connection.get_template_index_with_limit(
                        limit=limit, offset=offset,
                        query_string=template_id)
                except LoomengineUtilsError as e:
                    raise SystemExit(
                        "ERROR! Failed to get template list: '%s'" % e)
                for template in data['results']:
                    found_at_least_one_match = True
                    if template.get('uuid') not in template_uuids:
                        template_uuids.add(template.get('uuid'))
                        templates.append(template)
                if data.get('next'):
                    offset += limit
                else:
                    break
            if not found_at_least_one_match:
                raise SystemExit(
                    'ERROR! No templates matched "%s"' % template_id)
        if len(templates) > 1:
            try:
                return self.export_manager.bulk_export_templates(
                    templates,
                    destination_directory=self.args.destination_directory,
                    retry=self.args.retry,
                    link_files=self.args.link_files,
                    editable=self.args.editable
                )
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to export templates: '%s'" % e)
        else:
            try:
                return self.export_manager.export_template(
                    templates[0],
                    destination_directory=self.args.destination_directory,
                    retry=self.args.retry,
                    link_files=self.args.link_files,
                    editable=self.args.editable
                )
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to export template: '%s'" % e)


class TemplateList(AbstractTemplateSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'template_id',
            nargs='?',
            metavar='TEMPLATE_IDENTIFIER',
            help='Name or ID of template(s) to list.')
        parser.add_argument(
            '-d', '--detail',
            action='store_true',
            help='Show detailed view of templates')
        parser.add_argument(
            '-a', '--all',
            action='store_true',
            help='List all templates, including nested children. '
            '(ignored when TEMPLATE_IDENTIFIER is given)')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='Filter by label')
        return parser

    def run(self):
        if self.args.template_id:
            parent_only = False
        else:
            parent_only = not self.args.all
        offset = 0
        limit = 10
        while True:
            try:
                data = self.connection.get_template_index_with_limit(
                    labels=self.args.label,
                    limit=limit, offset=offset,
                    query_string=self.args.template_id,
                    parent_only=parent_only)
            except LoomengineUtilsError as e:
                raise SystemExit(
                    "ERROR! Failed to get template list: '%s'" % e)
            if offset == 0:
                self._print('[showing %s templates]' % data.get('count'))
            self._list_templates(data['results'])
            if data.get('next'):
                offset += limit
            else:
                break
        return data['results']

    def _list_templates(self, templates):
        for template in templates:
            self._print(self._render_template(template))

    def _render_template(self, template):
        template_identifier = '%s@%s' % (template['name'], template['uuid'])
        if self.args.detail:
            text = '---------------------------------------\n'
            text += 'Template: %s\n' % template_identifier
            text += '  - md5: %s\n' % template.get('md5')
            text += '  - Imported: %s\n' % \
                    _render_time(template['datetime_created'])
            if template.get('inputs'):
                text += '  - Inputs\n'
                for input in template['inputs']:
                    text += '    - %s\n' % input['channel']
            if template.get('outputs'):
                text += '  - Outputs\n'
                for output in template['outputs']:
                    text += '    - %s\n' % output['channel']
            if template.get('steps'):
                text += '  - Steps\n'
                for step in template['steps']:
                    text += '    - %s@%s\n' % (step['name'], step['uuid'])
            if template.get('command'):
                text += '  - Command: %s\n' % template['command']
        else:
            text = 'Template: %s' % template_identifier
        return text


class TemplateDelete(AbstractTemplateSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'template_id',
            metavar='TEMPLATE_IDENTIFIER',
            help='Name or ID of template to delete.')
        parser.add_argument('-y', '--yes', action='store_true',
                            default=False,
                            help='delete without prompting for confirmation')
        parser.add_argument('-c', '--keep-children', action='store_true',
                            default=False,
                            help='do not delete child templates')
        return parser

    def run(self):
        try:
            data = self.connection.get_template_index(
                query_string=self.args.template_id,
                min=1, max=1)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get template list: '%s'" % e)
        self._delete_template(data[0])

    def _delete_template(self, template):
        template_id = "%s@%s" % (
            template.get('name'),
            template.get('uuid'))
        template_children_to_delete = []
        if not self.args.keep_children and template.get('steps'):
            for step in template.get('steps'):
                try:
                    template_children_to_delete.append(
                        self.connection.get_template_index(
                            query_string='@%s' % step['uuid'],
                            min=1, max=1)[0]
                    )
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to get template: '%s'" % e)
        if not self.args.yes:
            user_input = raw_input(
                'Do you really want to permanently delete template "%s"?\n'
                '(y)es, (n)o: '
                % template_id)
            if user_input.lower() == 'n':
                raise SystemExit('Operation canceled by user')
            elif user_input.lower() == 'y':
                pass
            else:
                raise SystemExit('Unrecognized response "%s"' % user_input)
        try:
            dependencies = self.connection.get_template_dependencies(
                template.get('uuid'))
        except LoomengineUtilsError as e:
            raise SystemExit(
                "ERROR! Failed to get template dependencies: '%s'" % e)
        if len(dependencies['runs']) == 0 \
           and len(dependencies['templates']) == 0:
            try:
                self.connection.delete_template(template.get('uuid'))
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to delete template: '%s'" % e)
            self._print("Deleted template %s" % template_id)
        else:
            print "Cannot delete template %s because it is still in use. "\
                "You must delete the following objects "\
                "before deleting this template." % template_id
            self._print(self._render_dependencies(dependencies))
        for template in template_children_to_delete:
            self._delete_template(template)

    def _render_dependencies(self, dependencies):
        text = ''
        for run in dependencies.get('runs', []):
            text += "  run %s@%s\n" % (run['name'], run['uuid'])
        for template in dependencies.get('templates', []):
            text += "  template %s@%s\n" % (template['name'], template['uuid'])
        if dependencies.get('truncated'):
            text += "  ...[results truncated]\n"
        return text


class Template(object):
    """Configures and executes subcommands under "template" on the main parser.
    """

    def __init__(self, args=None, silent=False):
        # Args may be given as an input argument for testing purposes.
        # Otherwise get them from the parser.
        if args is None:
            args = self._get_args()
        self.args = args
        self.silent = silent

    def _get_args(self):
        parser = self.get_parser()
        return parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):

        # If called from main, a subparser should be provided.
        # Otherwise we create a top-level parser here.
        if parser is None:
            parser = argparse.ArgumentParser(__file__)

        subparsers = parser.add_subparsers()

        list_subparser = subparsers.add_parser(
            'list', help='list templates')
        TemplateList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubcommandClass=TemplateList)

        tag_subparser = subparsers.add_parser(
            'tag', help='manage template tags')
        TemplateTag.get_parser(tag_subparser)
        tag_subparser.set_defaults(SubSubcommandClass=TemplateTag)

        label_subparser = subparsers.add_parser(
            'label', help='manage template labels')
        TemplateLabel.get_parser(label_subparser)
        label_subparser.set_defaults(SubSubcommandClass=TemplateLabel)

        import_subparser = subparsers.add_parser(
            'import', help='import templates')
        TemplateImport.get_parser(import_subparser)
        import_subparser.set_defaults(SubSubcommandClass=TemplateImport)

        export_subparser = subparsers.add_parser(
            'export', help='export templates')
        TemplateExport.get_parser(export_subparser)
        export_subparser.set_defaults(SubSubcommandClass=TemplateExport)

        delete_subparser = subparsers.add_parser(
            'delete', help='delete template')
        TemplateDelete.get_parser(delete_subparser)
        delete_subparser.set_defaults(SubSubcommandClass=TemplateDelete)

        return parser

    def run(self):
        return self.args.SubSubcommandClass(
            self.args, silent=self.silent).run()


if __name__ == '__main__':
    response = Template().run()
