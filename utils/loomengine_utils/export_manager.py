import copy
import datetime
import logging
import os
import yaml

from .exceptions import LoomengineUtilsError, ExportManagerError, \
    FileAlreadyExistsError
from .file_utils import File

logger = logging.getLogger(__name__)


class ExportManager(object):

    def __init__(self, connection, storage_settings=None, silent=False):
        self.connection = connection
        if storage_settings is None:
            storage_settings = connection.get_storage_settings()
        self.storage_settings = storage_settings
        self.silent = silent

    def _print(self, text):
        if not self.silent:
            print text

    def bulk_export_files(self, files, destination_directory=None,
                          retry=False, export_metadata=True,
                          link_files=False, editable=False):
        if destination_directory == None:
            destination_directory = self._get_default_bulk_export_directory()
        for file in files:
            if editable:
                subdir = 'md5_'+file['value'].get('md5')
            else:
                subdir = 'uuid_'+file.get('uuid')
            file_directory = os.path.join(
                destination_directory,
                'files',
                subdir)
            self.export_file(file,
                             destination_directory=file_directory,
                             retry=retry,
                             export_metadata=export_metadata,
                             export_raw_file=not link_files)

    def export_file(self, data_object, destination_directory=None,
                    destination_filename=None, retry=False,
                    export_metadata=False, export_raw_file=True):
        """Export a file from Loom to some file storage location.
        Default destination_directory is cwd. Default destination_filename is the 
        filename from the file data object associated with the given file_id.
        """
        if not destination_directory:
            destination_directory = os.getcwd()

        # We get filename from the dataobject
        if not destination_filename:
            destination_filename = data_object['value']['filename']

        destination_file_url = os.path.join(destination_directory,
                                            destination_filename)

        logger.info('Exporting file %s@%s ...' % (
            data_object['value']['filename'],
            data_object['uuid']))

        if export_raw_file:
            destination = File(
                destination_file_url, self.storage_settings, retry=retry)
            if destination.exists():
                raise FileAlreadyExistsError(
                    'File already exists at %s' % destination_file_url)
            logger.info('...copying file to %s' % (
                destination.get_url()))

            # Copy from the first file location
            file_resource = data_object.get('value')
            md5 = file_resource.get('md5')
            source_url = data_object['value']['file_url']
            File(source_url, self.storage_settings, retry=retry).copy_to(
                destination, expected_md5=md5)
            data_object['value'] = self._create_new_file_resource(
                data_object['value'], destination.get_url())
        else:
            logger.info('...skipping raw file')

        if export_metadata:
            data_object['value'].pop('link', None)
            data_object['value'].pop('upload_status', None)
            destination_metadata_url = os.path.join(
                destination_file_url + '.metadata.yaml')
            logger.info('...writing metadata to %s' % destination_metadata_url)
            metadata = yaml.safe_dump(data_object, default_flow_style=False)
            metadata_file = File(destination_metadata_url,
                                 self.storage_settings, retry=retry)
            metadata_file.write(metadata)
        else:
            logger.info('...skipping metadata')

        logger.info('...finished file export')

    def _create_new_file_resource(self, old_resource, new_file_url):
        # Most fields are the same as old_resource.
        new_resource = copy.deepcopy(old_resource)

        # "link" boolean affects how the server manages files
        # and is not meaningful after export
        new_resource.pop('link', None)
        new_resource.pop('upload_status', None)
        new_resource['file_url'] = new_file_url
        return new_resource

    def export_template(self, template, destination_directory=None,
                        file_destination_directory=None,
                        retry=False, link_files=False, editable=False,
                        save_files=True, file_dict=None):

        template_destination = self._get_template_destination(
            template, destination_directory=destination_directory)
        if not file_destination_directory:
            file_destination_directory = template_destination+'.dependencies'
        template = self._expand_template(template)

        if not file_dict:
            file_dict = {}
        if editable:
            file_id_field = 'md5'
        else:
            file_id_field = 'uuid'
        self._get_files_from_template(template, file_dict, file_id_field)

        if editable:
            # Must be AFTER _get_files_from_template since that edits file definitions
            template = self._convert_template_to_editable(template)

        # If template is editable, exclude file metadata with UUIDs
        export_file_metadata = not editable

        self.bulk_export_files(
            file_dict.values(), destination_directory=file_destination_directory,
            retry=retry, link_files=link_files, export_metadata=export_file_metadata)
        if editable:
            self._recursively_save_template_and_steps(
                template, template_destination, retry=retry)
        else:
            self._save_template(template, template_destination, retry=retry)

    def bulk_export_templates(self, templates,
                              destination_directory=None,
                              retry=False, link_files=False,
                              editable=False, save_files=True,
                              file_dict=None):
        if destination_directory is None:
            destination_directory = self._get_default_bulk_export_directory()

        expanded_templates = self._expand_templates(templates)

        if not file_dict:
            file_dict = {}
        if editable:
            file_id_field = 'md5'
        else:
            file_id_field = 'uuid'

        # If templates are editable, UUIDs will be stripped. But to avoid
        # file collisions, we save the UUIDs to use as a subdirectory that
        # makes each template's path unique
        template_uuids = [t['uuid'] for t in expanded_templates]

        if editable:
            templates = self._convert_templates_to_editable(expanded_templates)

        # If template is editable, exclude file metadata with UUIDs
        export_file_metadata = not editable

        if save_files:
            self._get_files_from_templates(expanded_templates, file_dict, file_id_field)
            self.bulk_export_files(file_dict.values(),
                                   destination_directory=destination_directory,
                                   retry=retry, link_files=link_files,
                                   export_metadata=export_file_metadata,
                                   editable=editable)
        for template in expanded_templates:
            if editable:
                subdir = 'md5_'+template.get('md5')
            else:
                subdir = 'uuid_'+template.get('uuid')
            template_destination = self._get_template_destination(
                template,
                destination_directory=os.path.join(
                    destination_directory, 'templates', subdir))
            if editable:
                self._recursively_save_template_and_steps(template, template_destination, retry=retry)
            else:
                self._save_template(template, template_destination, retry=retry)
        return templates

    def _recursively_save_template_and_steps(self, template, template_destination, retry=False):
        steps = template.pop('steps', [])
        for step in steps:
            step_labels = template.setdefault('steps', [])
            step_labels.append(step['name'])
        self._save_template(template, template_destination, retry=retry)
        for step in steps:
            self._recursively_save_template_and_steps(
                step,
                os.path.join(template_destination + '.dependencies', 'templates', '%s.yaml' % step['name']),
                retry=retry)

    def bulk_export_runs(self, runs,
                         destination_directory=None,
                         retry=False, link_files=False):
        if destination_directory is None:
            destination_directory = self._get_default_bulk_export_directory()

        expanded_runs = self._expand_runs(runs)
        templates = [run['template'] for run in expanded_runs]
        templates = [self.connection.get_template(template['uuid'])
                     for template in templates]
        expanded_templates = self._expand_templates(templates)

        file_dict = {}
        file_id_field = 'uuid'

        self._get_files_from_templates(expanded_templates, file_dict, file_id_field)
        self._get_files_from_runs(expanded_runs, file_dict, file_id_field)
        
        self.bulk_export_files(file_dict.values(),
                               destination_directory=destination_directory,
                               retry=retry, link_files=link_files)
        self.bulk_export_templates(templates,
                                   destination_directory=destination_directory,
                                   retry=retry, link_files=link_files,
                                   save_files=False)

        for run in expanded_runs:
            subdir = 'uuid_'+run.get('uuid')
            run_destination = self._get_run_destination(
                run,
                destination_directory=os.path.join(
                    destination_directory, 'runs', subdir))
            self._save_run(run, run_destination, retry=retry)
        return runs
            
    def export_run(self, run, destination_directory=None,
                   retry=False, link_files=False):
        # We are going to save the full template under templates/ subdir but leave the
        # abbreviated version in the run.
        #So we Take a copy of the template and expand it.
        run = self._expand_run(run)
        template = self.connection.get_template(run['template']['uuid'])
        template = self._expand_template(template)

        run_destination = self._get_run_destination(
            run, destination_directory=destination_directory)
        template_destination = self._get_template_destination(
            template, os.path.join(run_destination+'.dependencies', 'templates'))
        file_destination_directory = run_destination+'.dependencies'

        file_dict = {}
        file_id_field = 'uuid'
        self._get_files_from_template(template, file_dict, file_id_field)
        self._get_files_from_run(run, file_dict, file_id_field)
        
        self.bulk_export_files(
            file_dict.values(), destination_directory=file_destination_directory,
            retry=retry, link_files=link_files)
        self._save_template(template, template_destination, retry=retry)
        self._save_run(run, run_destination, retry=retry)

    def _get_run_destination(
            self, run, destination_directory=None):
        if destination_directory == None:
            destination_directory = os.getcwd()
        return os.path.join(destination_directory, run['name']+'.yaml')

    def _expand_runs(self, runs):
        return [self._expand_run(r) for r in runs]
        
    def _expand_run(self, run):
        return self.connection.get_run(run['uuid'], expand=True)

    def _save_run(self, run, destination, retry=False):
        self._print('Exporting run %s@%s to %s...' % (
            run.get('name'), run.get('uuid'), destination))
        self._save_yaml(run, destination, retry=retry)
        self._print('...finished exporting run')
        
    def _expand_template(self, template):
        return self.connection.get_template(template.get('uuid'), expand=True)

    def _expand_templates(self, templates):
        return [self._expand_template(t) for t in templates]

    def _convert_template_to_editable(self, template):
        # Delete data that is unique to the original instance. User can edit
        # and reimport this template with a new uuid, datetime_created, etc.
        template.pop('uuid', None)
        template.pop('url', None)
        template.pop('datetime_created', None)
        template.pop('imported_from_url', None)

        for input in template.get('inputs', []):
            if input['data']:
                input['data'] = self._convert_data_node_to_editable(input['data'])
        converted_steps = []
        for step in template.get('steps', []):
            converted_steps.append(self._convert_template_to_editable(step))
        if converted_steps:
            template['steps'] = converted_steps
        return template

    def _convert_templates_to_editable(self,templates):
        return [self._convert_template_to_editable(t) for t in templates]

    def _convert_data_node_to_editable(self, data_node):
        data_node.pop('uuid', None)
        data_node.pop('url', None)
        if data_node.get('contents'):
            data_node['contents'] = self._convert_data_contents_to_editable(
                data_node['contents'])
        return data_node

    def _convert_data_contents_to_editable(self, contents):
        if isinstance(contents, list):
            return [self._convert_data_contents_to_editable(item)
                    for item in contents]
        else:
            if contents.get('type') == 'file':
                new_contents = '%s$%s' % (
                    contents['value'].get('filename'), contents['value'].get('md5'))
            else:
                new_contents = contents.get('value')
            return new_contents

    def _get_files_from_run(self, run, file_dict, file_id_field):
        self._get_files_from_inputs_outputs(run, file_dict, file_id_field)
        for step in run.get('steps', []):
            self._get_files_from_run(step, file_dict, file_id_field)
        for task in run.get('tasks', []):
            self._get_files_from_task(task, file_dict, file_id_field)

    def _get_files_from_runs(self, runs, file_dict, file_id_field):
        for run in runs:
            self._get_files_from_template(run, file_dict, file_id_field)

    def _get_files_from_task(self, task, file_dict, file_id_field):
        self._get_files_from_inputs_outputs(task, file_dict, file_id_field)
        for task_attempt in task.get('all_task_attempts', []):
            self._get_files_from_task_attempt(task_attempt, file_dict, file_id_field)

    def _get_files_from_task_attempt(self, task_attempt, file_dict, file_id_field):
        self._get_files_from_inputs_outputs(task_attempt, file_dict, file_id_field)
        self._get_files_from_logs(task_attempt, file_dict, file_id_field)

    def _get_files_from_logs(self, task_attempt, file_dict, file_id_field):
        for log_file in task_attempt.get('log_files', []):
            self._add_file_if_unique(log_file.get('data_object'), file_dict, file_id_field)
            
    def _get_files_from_template(self, template, file_dict, file_id_field):
        self._get_files_from_inputs_outputs(template, file_dict, file_id_field)
        for step in template.get('steps', []):
            self._get_files_from_template(step, file_dict, file_id_field)

    def _get_files_from_templates(self, templates, file_dict, file_id_field):
        for template in templates:
            self._get_files_from_template(template, file_dict, file_id_field)

    def _get_template_destination(
            self, template, destination_directory=None):
        if destination_directory == None:
            destination_directory = os.getcwd()
        return os.path.join(destination_directory, template['name']+'.yaml')

    def _save_template(self, template, destination, retry=False):
        self._print('Exporting template %s@%s to %s...' % (
            template.get('name'), template.get('uuid'), destination))
        self._save_yaml(template, destination, retry=retry)
        self._print('...finished exporting template')

    def _save_yaml(self, data, destination, retry=False):
        text = yaml.safe_dump(data, default_flow_style=False)
        file = File(destination, self.storage_settings, retry=retry)
        file.write(text)

    def _get_default_bulk_export_directory(self):
        dirname = 'loom-bulk-export-%s' % \
                  datetime.datetime.now().strftime('%Y-%m-%dT%H.%M.%S.%f')
        return os.path.join(os.getcwd(), dirname)

    def _add_unique_files(self, new_files, file_dict, id_field):
        for new_file in new_files:
            self._add_file_if_unique(new_file, file_dict, id_field)
                
    def _add_file_if_unique(self, new_file, file_dict, id_field):
        if id_field == 'md5':
            file_id = new_file['value'].get('md5')
        else:
            file_id = new_file.get('uuid')
        if file_id not in file_dict:
            file_dict[file_id] = new_file

    def _get_files_from_data_contents(self, file_dict, file_id_field, contents):
        if contents is None:
            return
        if isinstance(contents, list):
            for item in contents:
                self._get_files_from_data_contents(file_dict, file_id_field, item)
        else:
            self._add_file_if_unique(contents, file_dict, file_id_field)

    def _get_files_from_inputs_outputs(self, data, file_dict, file_id_field):
        for input in data.get('inputs', []):
            if input.get('type') == 'file' and input.get('data'):
                self._get_files_from_data_contents(
                    file_dict,
                    file_id_field,
                    input['data']['contents'])
        for output in data.get('outputs', []):
            if output.get('type') == 'file' and output.get('data'):
                self._get_files_from_data_contents(
                    file_dict,
                    file_id_field,
                    output['data']['contents'])
