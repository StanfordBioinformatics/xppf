#!/usr/bin/env python

import argparse
import glob
import json
import os
import re
import sys
import yaml
    
from loom.client import settings_manager
from loom.client.common import get_settings_manager
from loom.client.common import add_settings_options_to_parser
from loom.client.common import read_as_json_or_yaml
from loom.client.exceptions import *
from loom.common import filehandler
from loom.common import exceptions as common_exceptions
from loom.common.helper import get_stdout_logger
from loom.common.objecthandler import ObjectHandler


class AbstractUploader(object):
    """Common functions for the various subcommands under 'upload'
    """
    
    def __init__(self, args):
        """Common init tasks for all Uploader classes
        """
        self.args = args
        self.settings_manager = get_settings_manager(self.args)
        self.master_url = self.settings_manager.get_server_url_for_client()

    @classmethod
    def get_parser(cls, parser):
        parser = add_settings_options_to_parser(parser)
        return parser


class FileUploader(AbstractUploader):

    @classmethod
    def get_parser(cls, parser):
        parser = super(FileUploader, cls).get_parser(parser)
        parser.add_argument(
            'file_paths',
            metavar='FILE_PATHS', nargs='+', help='File(s) to be uploaded.')
        parser.add_argument(
            '--rename',
            nargs='+',
            metavar='NEW_FILE_NAMES',
            help='Rename the uploaded file(s). The number of names must be '\
            'equal to the number of files matched by FILE_PATHS. (File names '\
            'do not have to be unique since files will be given a unique ID.)')
        parser.add_argument(
            '--source_record',
            metavar='SOURCE_RECORD',
            help='Text file containing a complete description of the data '\
            'source. Provide enough detail to ensure traceability.')
        parser.add_argument(
            '--skip_source_record',
            help='Do not prompt for source record.',
            action='store_true')
        return parser

    def run(self):
        self._get_local_paths()
        self._get_file_names()
        self._get_filehandler()
        self._get_source_record_text()
        self._upload_files()

    def _get_local_paths(self):
        """Get all local file paths that match glob patterns
        given by the user.
        """
        paths = []
        for pattern in self.args.file_paths:
            paths.extend(glob.glob(
                os.path.expanduser(pattern)))
        self.local_paths = self._remove_dirs(paths)
        if len(self.local_paths) == 0:
            raise NoFilesFoundError("No files found for upload")
        
    def _remove_dirs(self, paths):
        """Verify that paths are for existing files
        """
        paths_minus_dirs = []
        for path in paths:
            if os.path.isdir(path):
                print "Skipping directory %s" % path
            else:
                paths_minus_dirs.append(path)
        return paths_minus_dirs

    def _get_file_names(self):
        """If --rename is used, process the list of file names. Otherwise use
        current file names.
        """
        if self.args.rename is None:
            self.file_names = None
        else:
            self.file_names = self.args.rename
        self._validate_file_names()

    def _validate_file_names(self):
        if self.file_names is None:
            return
        for name in self.file_names:
            if not re.match(r'^[0-9a-zA-Z_\.]+[0-9a-zA-Z_\-\.]*$', name):
                raise InvalidFileNameError(
                    'The file name "%s" is not valid. Filenames must contain '\
                    ' only alphanumerics, ".", "-", or "_", and may not start '\
                    'with "-".' % name)

    def _get_filehandler(self):
        self.filehandler = filehandler.FileHandler(self.master_url, logger=get_stdout_logger())

    def _get_source_record_text(self):
        if self.args.skip_source_record:
            if self.args.source_record:
                raise ArgumentError(
                    'Setting both --source_record and --skip_source_record is not allowed')
            else:
                self.source_record_text = ''
                return
        if self.args.source_record is not None:
            source_record_file = self.args.source_record
            if not os.path.isfile(source_record_file):
                raise NotAFileError(
                    '"%s" is not a file. A source record must be a text file.' \
                    % source_record_file)
            with open(source_record_file) as f:
                self.source_record_text = f.read()
        else:
            self.source_record_text = self.prompt_for_source_record_text()

    @classmethod
    def prompt_for_source_record_text(cls, source_name=None):
        if source_name:
            text = '\nEnter a complete description of the data source "%s". '\
                   'Provide enough detail to ensure traceability.\n'\
                   'Press [enter] to skip.\n> ' % source_name
        else:
            text = '\nEnter a complete description of the data source. '\
                   'Provide enough detail to ensure traceability.\n'\
                   'Press [enter] to skip.\n> '
        return raw_input(text)

    def _upload_files(self):
        self.filehandler.upload_files_from_local_paths(
            self.local_paths,
            file_names=self.file_names,
            source_record=self.source_record_text
        )


class WorkflowUploader(AbstractUploader):

    @classmethod
    def get_parser(cls, parser):
        parser = super(WorkflowUploader, cls).get_parser(parser)
        parser.add_argument(
            'workflow',
            metavar='WORKFLOW_FILE', help='Workflow to be uploaded, in YAML or JSON format.')
        parser.add_argument(
            '--rename',
            metavar='NEW_WORKFLOW_NAME',
            help='Rename the uploaded workflow. (Workflow names '\
            'do not have to be unique since workflows will be given a unique ID.)')
        return parser

    def run(self):
        self.workflow = self.get_workflow(self.args.workflow)
        self._set_workflow_name(self._get_workflow_name())
        self._get_objecthandler()
        self._expand_file_ids()
        return self._upload_workflow()

    @classmethod
    def get_workflow(cls, workflow_file):
        workflow = read_as_json_or_yaml(workflow_file)
        cls._validate_workflow(workflow)
        return workflow

    @classmethod
    def _validate_workflow(cls, workflow):
        if not isinstance(workflow, dict):
            raise ValidationError('This is not a valid workflow: "%s"' % workflow)

    def _set_workflow_name(self, workflow_name):
        self.workflow['workflow_name'] = workflow_name

    def _get_workflow_name(self):
        if self.args.rename is not None:
            return self.args.rename
        elif self.workflow.get('workflow_name') is not None:
            return self.workflow.get('workflow_name')
        else:
            return os.path.basename(self.args.workflow)

    def _get_objecthandler(self):
        self.objecthandler = ObjectHandler(self.master_url)

    def _expand_file_ids(self):
        """Wherever a workflow lists a file identifier as input, query
        the server to make sure exactly one match exists, and enter the full identifier in
        the workflow.
        """
        if self.workflow.get('workflow_inputs') is None:
            return
        else:
            for counter_i in range(len(self.workflow['workflow_inputs'])):
                workflow_input = self.workflow['workflow_inputs'][counter_i]
                if workflow_input.get('value') is None:
                    continue
                if workflow_input['type'] == 'file':
                    file_id = self._get_file_id(workflow_input['value'])
                    self.workflow['workflow_inputs'][counter_i]['value'] = file_id
                elif workflow_input['type'] == 'file_array':
                    if not isinstance(workflow_input['value'], list):
                        raise Exception
                    for counter_j in range(len(workflow_input['value'])):
                        file_id = self._get_file_id(workflow_input['value'][counter_j])
                        workflow_input['value'][counter_j] = file_id
            
    def _get_file_id(self, file_id):
        try:
            file_data_object = self.objecthandler.get_file_data_object_index(file_id, min=1, max=1)[0]
        except common_exceptions.IdMatchedTooFewFileDataObjectsError as e:
            raise IdMatchedTooFewFileDataObjectsError(
                "The file ID %s did not match any files on the server. "\
                "Upload the file before uploading the workflow."
            )
        except common_exceptions.IdMatchedTooManyFileDataObjectsError:
            raise IdMatchedTooManyFileDataObjectsError(
                "The file ID %s matched multiple files on the server. Try using an ID that is more precise."
            )
        return file_data_object['file_name'] + '@' + file_data_object['_id']
            
    def _upload_workflow(self):
        workflow_from_server = self.objecthandler.post_workflow(self.workflow)
        print 'Uploaded workflow "%s" with id %s' % \
            (workflow_from_server['workflow_name'], workflow_from_server['_id'])
        return workflow_from_server
    
class Uploader:
    """Sets up and executes commands under "upload" on the main parser.
    """

    def __init__(self, args=None):
        
        # Args may be given as an input argument for testing purposes.
        # Otherwise get them from the parser.
        if args is None:
            args = self._get_args()
        self.args = args

    def _get_args(self):
        parser = self.get_parser()
        return parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):

        # If called from main, use the subparser provided.
        # Otherwise create a top-level parser here.
        if parser is None:
            parser = argparse.ArgumentParser(__file__)

        subparsers = parser.add_subparsers(help='select a data type to upload')

        file_subparser = subparsers.add_parser('file', help='upload a file or list files')
        FileUploader.get_parser(file_subparser)
        file_subparser.set_defaults(SubSubcommandClass=FileUploader)

        workflow_subparser = subparsers.add_parser('workflow', help='upload a workflow')
        WorkflowUploader.get_parser(workflow_subparser)
        workflow_subparser.set_defaults(SubSubcommandClass=WorkflowUploader)

        return parser

    def run(self):
        self.args.SubSubcommandClass(self.args).run()


if __name__=='__main__':
    response = Uploader().run()
