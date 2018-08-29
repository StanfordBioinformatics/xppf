#!/usr/bin/env python
import argparse
import glob
import os
import sys

from loomengine import _render_time
from loomengine.common import verify_server_is_running, get_server_url, \
    verify_has_connection_settings, get_token
from loomengine.file_tag import FileTag
from loomengine.file_label import FileLabel
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import LoomengineUtilsError, APIError
from loomengine_utils.import_manager import ImportManager
from loomengine_utils.export_manager import ExportManager


class AbstractFileSubcommand(object):

    def __init__(self, args, silent=False):
        """Common init tasks for all File subcommands
        """
        self.args = args
        self.silent = silent
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        token = get_token()
        self.connection = Connection(server_url, token=token)
        try:
            self.export_manager = ExportManager(connection=self.connection)
            self.import_manager = ImportManager(connection=self.connection)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to initialize client: '%s'" % e)

    def _print(self, text):
        if not self.silent:
            print text


class FileImport(AbstractFileSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'files',
            metavar='FILE', nargs='+', help='file path or Google Storage URL '
            'of file(s) to be imported. Wildcards are allowed')
        parser.add_argument(
            '-c', '--comments',
            metavar='COMMENTS',
            help='add comments to file metadata')
        parser.add_argument(
            '-k', '--link', action='store_true',
            default=False,
            help='link to existing files instead of copying to storage '
            'managed by Loom')
        metadata_group = parser.add_mutually_exclusive_group(required=False)
        metadata_group.add_argument(
            '-m', '--from-metadata', action='store_true',
            default=False,
            help='import from link in metadata file')
        metadata_group.add_argument(
            '-i', '--ignore-metadata', action='store_true',
            default=False,
            help='ignore metadata if present')
        parser.add_argument('-f', '--force-duplicates', action='store_true',
                            default=False,
                            help='force upload even if another file with '
                            'the same name and md5 exists')
        parser.add_argument('-r', '--retry', action='store_true',
                            default=False,
                            help='allow retries if there is a failure')
        parser.add_argument('-t', '--tag', metavar='TAG', action='append',
                            help='tag the file when it is created')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='label the file when it is created')
        return parser

    def run(self):
        try:
            files_imported = self.import_manager.import_from_patterns(
                self.args.files,
                self.args.comments,
                link=self.args.link,
                ignore_metadata=self.args.ignore_metadata,
                from_metadata=self.args.from_metadata,
                force_duplicates=self.args.force_duplicates,
                retry=self.args.retry
            )
        except APIError as e:
            raise SystemExit(
                'ERROR! An external API failed. This may be transient. '
                'Try again, and consider using "--retry", especially '
                'if this step is automated. Original error: "%s"' % e)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to import files: '%s'" % e)
        self._apply_tags(files_imported)
        self._apply_labels(files_imported)
        return files_imported

    def _apply_tags(self, files_imported):
        if not self.args.tag:
            return
        if len(files_imported) > 1:
            print 'WARNING! No tags were applied, because tags '\
                'must be unique but multiple files were imported.'
            return
        else:
            for tagname in self.args.tag:
                tag_data = {'tag': tagname}
                try:
                    tag = self.connection.post_data_tag(
                        files_imported[0].get('uuid'), tag_data)
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to create tag: '%s'" % e)
                self._print('File "%s@%s" has been tagged as "%s"' %
                            (files_imported[0]['value'].get('filename'),
                             files_imported[0].get('uuid'),
                             tag.get('tag')))

    def _apply_labels(self, files_imported):
        if not self.args.label:
            return
        for labelname in self.args.label:
            for file_imported in files_imported:
                label_data = {'label': labelname}
                try:
                    label = self.connection.post_data_label(
                        file_imported.get('uuid'), label_data)
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to create label: '%s'" % e)
                self._print('File "%s@%s" has been labeled as "%s"' %
                            (file_imported['value'].get('filename'),
                             file_imported.get('uuid'),
                             label.get('label')))


class FileExport(AbstractFileSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'file_ids',
            nargs='+',
            metavar='FILE_ID',
            help='file or list of files to be exported')
        parser.add_argument(
            '-d', '--destination-directory',
            metavar='DESTINATION_DIRECTORY',
            help='destination directory')
        metadata_group = parser.add_mutually_exclusive_group(required=False)
        metadata_group.add_argument(
            '-n', '--no-metadata',
            default=False,
            action='store_true',
            help='export raw file without metadata')
        metadata_group.add_argument(
            '-k', '--link',
            default=False,
            action='store_true',
            help='do not export files, '
            'just metadata with link to original files')
        parser.add_argument(
            '-r', '--retry', action='store_true',
            default=False,
            help='allow retries if there is a failure')
        return parser

    def run(self):
        files = []
        file_uuids = set()
        for file_id in self.args.file_ids:
            found_at_least_one_match = False
            offset = 0
            limit = 10
            while True:
                try:
                    data = self.connection.get_data_object_index_with_limit(
                        limit=limit, offset=offset,
                        query_string=file_id, type='file')
                except LoomengineUtilsError as e:
                    raise SystemExit(
                        "ERROR! Failed to get data object list: '%s'" % e)
                for data_object in data['results']:
                    found_at_least_one_match = True
                    if data_object.get('uuid') not in file_uuids:
                        file_uuids.add(data_object.get('uuid'))
                        files.append(data_object)
                if data.get('next'):
                    offset += limit
                else:
                    break
            if not found_at_least_one_match:
                raise SystemExit('ERROR! No files matched "%s"' % file_id)
        try:
            if len(files) > 1:
                try:
                    self.export_manager.bulk_export_files(
                        files,
                        destination_directory=self.args.destination_directory,
                        retry=self.args.retry,
                        export_metadata=not self.args.no_metadata,
                        link_files=self.args.link,
                    )
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to export files: '%s'" % e)
            else:
                try:
                    self.export_manager.export_file(
                        files[0],
                        destination_directory=self.args.destination_directory,
                        retry=self.args.retry,
                        export_metadata=not self.args.no_metadata,
                        export_raw_file=not self.args.link,
                    )
                except LoomengineUtilsError as e:
                    raise SystemExit("ERROR! Failed to export files: '%s'" % e)
        except APIError as e:
            raise SystemExit(
                'ERROR! An external API failed. This may be transient. '
                'Try again, and consider using "--retry", especially '
                'if this step is automated. Original error: "%s"' % e)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! %s" % e.message)


class FileList(AbstractFileSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'file_id',
            nargs='?',
            metavar='FILE_IDENTIFIER',
            help='Name or ID of file(s) to list.')
        parser.add_argument(
            '-d', '--detail',
            action='store_true',
            help='Show detailed view of files')
        parser.add_argument(
            '-t', '--type',
            choices=['imported', 'result', 'log', 'all'],
            default='imported',
            help='List only files of the specified type. '
            '(ignored when FILE_IDENTIFIER is given)')
        parser.add_argument('-l', '--label', metavar='LABEL', action='append',
                            help='Filter by label')

        return parser

    def run(self):
        if self.args.file_id:
            source_type = None
        else:
            source_type = self.args.type
        offset = 0
        limit = 10
        while True:
            try:
                data = self.connection.get_data_object_index_with_limit(
                    limit=limit, offset=offset,
                    query_string=self.args.file_id, source_type=source_type,
                    labels=self.args.label, type='file')
            except LoomengineUtilsError as e:
                raise SystemExit(
                    "ERROR! Failed to get data object list: '%s'" % e)
            if offset == 0:
                self._print('[showing %s files]' % data.get('count'))
            self._list_files(data['results'])
            if data.get('next'):
                offset += limit
            else:
                break
        return data['results']

    def _list_files(self, files):
        for file_data_object in files:
            text = self._render_file(file_data_object)
            if text is not None:
                self._print(text)

    def _render_file(self, file_data_object):
        try:
            file_identifier = '%s@%s' % (
                file_data_object['value'].get('filename'),
                file_data_object['uuid'])
        except TypeError:
            file_identifier = '@%s' % file_data_object['uuid']

        status = file_data_object['value'].get('upload_status')
        status_note = ''
        if status != 'complete':
            status_note = ' (%s)' % status

        if self.args.detail:
            text = '---------------------------------------\n'
            text += 'File: %s%s\n' % (file_identifier, status_note)
            try:
                text += '  - Imported: %s\n' % \
                        _render_time(file_data_object['datetime_created'])
                text += '  - md5: %s\n' % file_data_object['value'].get('md5')
                if file_data_object['value'].get('imported_from_url'):
                    text += '  - Source URL: %s\n' % \
                            file_data_object['value'].get('imported_from_url')
                if file_data_object['value'].get('import_comments'):
                    text += '  - Import note: %s\n' % \
                            file_data_object['value']['import_comments']
            except TypeError:
                pass
        else:
            text = 'File: %s%s' % (file_identifier, status_note)
        return text


class FileDelete(AbstractFileSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'file_id',
            metavar='FILE_IDENTIFIER',
            help='Name or ID of file to delete.')
        parser.add_argument('-y', '--yes', action='store_true',
                            default=False,
                            help='delete without prompting for confirmation')
        return parser

    def run(self):
        try:
            data = self.connection.get_data_object_index(
                query_string=self.args.file_id,
                type='file', min=1, max=1)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get data object list: '%s'" % e)
        self._delete_file(data[0])

    def _delete_file(self, file_data_object):
        file_id = "%s@%s" % (
            file_data_object.get('value')['filename'],
            file_data_object.get('uuid'))
        if not self.args.yes:
            user_input = raw_input(
                'Do you really want to permanently delete file "%s"?\n'
                '(y)es, (n)o: '
                % file_id)
            if user_input.lower() == 'n':
                raise SystemExit('ERROR! Operation canceled by user')
            elif user_input.lower() == 'y':
                pass
            else:
                raise SystemExit(
                    'ERROR! Unrecognized response "%s"' % user_input)
        try:
            dependencies = self.connection.get_data_object_dependencies(
                file_data_object['uuid'])
        except LoomengineUtilsError as e:
            raise SystemExit(
                "ERROR! Failed to get data object dependencies: '%s'" % e)
        if len(dependencies['runs']) == 0 \
           and len(dependencies['templates']) == 0:
            try:
                self.connection.delete_data_object(
                    file_data_object.get('uuid'))
            except LoomengineUtilsError as e:
                raise SystemExit(
                    "ERROR! Failed to delete data object: '%s'" % e)
            self._print("Deleted file %s" % file_id)
        else:
            raise SystemExit(
                "ERROR! You cannot delete file %s "
                "because it is still in use. "
                "You must delete the following objects "
                "before deleting this file:\n\n%s" % (
                    file_id, self._render_file_dependencies(dependencies)))

    def _render_file_dependencies(self, dependencies):
        text = ''
        for run in dependencies.get('runs', []):
            text += "  run %s@%s\n" % (run['name'], run['uuid'])
        for template in dependencies.get('templates', []):
            text += "  template %s@%s\n" % (template['name'], template['uuid'])
        if dependencies.get('truncated'):
            text += "  ...[results truncated]\n"
        return text


class FileClient(object):
    """Configures and executes subcommands under "file" on the main parser.
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
            'list', help='list files')
        FileList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubcommandClass=FileList)

        tag_subparser = subparsers.add_parser('tag', help='manage file tags')
        FileTag.get_parser(tag_subparser)
        tag_subparser.set_defaults(SubSubcommandClass=FileTag)

        label_subparser = subparsers.add_parser(
            'label', help='manage file labels')
        FileLabel.get_parser(label_subparser)
        label_subparser.set_defaults(SubSubcommandClass=FileLabel)

        import_subparser = subparsers.add_parser(
            'import', help='import files')
        FileImport.get_parser(import_subparser)
        import_subparser.set_defaults(SubSubcommandClass=FileImport)

        export_subparser = subparsers.add_parser(
            'export', help='export files')
        FileExport.get_parser(export_subparser)
        export_subparser.set_defaults(SubSubcommandClass=FileExport)

        delete_subparser = subparsers.add_parser('delete', help='delete file')
        FileDelete.get_parser(delete_subparser)
        delete_subparser.set_defaults(SubSubcommandClass=FileDelete)

        return parser

    def run(self):
        return self.args.SubSubcommandClass(
            self.args, silent=self.silent).run()


if __name__ == '__main__':
    response = FileClient().run()
