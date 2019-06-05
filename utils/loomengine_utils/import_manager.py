import logging
import os
import re
from requests.exceptions import HTTPError
import yaml

from .exceptions import ImportManagerError, FileDuplicateError
from .file_utils import File, FileSet, parse_as_yaml
from .connection import ServerConnectionError
from oauth2client.client import ApplicationDefaultCredentialsError

logger = logging.getLogger(__name__)


class DependencyNode(object):
    """This class helps keep track of file dependencies for a
    template. It maintains a tree of dependencies so that when references to 
    a file or template (e.g. "step1$8cd1938abdd12dff4d38a0c8dabd7f07") are
    resolved, we can search the current branch first and then work our way
    up the tree. This corresponds to searching files/ and steps/ folders
    at the current level, then searching up the directory tree to find a match.
    """

    def __init__(self, parent=None):
        self.file_data_objects = []
        self.parent = parent

class ImportManager(object):

    def __init__(self, connection, storage_settings=None, silent=False):
        self.connection = connection
        self.silent = silent
        if storage_settings is None:
            storage_settings = connection.get_storage_settings()
	self.storage_settings = storage_settings

    def _print(self, text):
        if not self.silent:
            print text

    def bulk_import(self, directory, link_files=False,
                    retry=False):
        self._bulk_import_files(
            os.path.join(directory, 'files'),
            link_files=link_files, retry=retry)
        self._bulk_import_templates(
            os.path.join(directory, 'templates'),
            link_files=link_files, retry=retry)
        self._bulk_import_runs(
            os.path.join(directory, 'runs'),
            link_files=link_files, retry=retry)

    def _bulk_import_files(self, directory, link_files=False, retry=False,
                           force_duplicates=False):
        # import all files directory/* and directory/*/*, with metadata if present
        files_to_import = FileSet(
            [os.path.join(directory, '*'), os.path.join(directory, '*/*')],
            self.storage_settings, retry=retry,
            trim_metadata_suffix=True, raise_if_missing=False)
        imported_files = []
        for file_to_import in files_to_import:
            imported_files.append(
                self.import_file(
                    file_to_import.get_url(), '', link=link_files, retry=retry,
                    force_duplicates=force_duplicates)
            )
        return imported_files

    def _bulk_import_templates(self, directory, link_files=False, retry=False,
                               force_duplicates=False):
        templates_to_import = FileSet(
            [os.path.join(directory, '*'), os.path.join(directory, '*/*')],
            self.storage_settings, retry=retry, raise_if_missing=False)
        imported_templates = []
        for template_to_import in templates_to_import:
            imported_templates.append(
                self.import_template(
                    template_to_import, link_files=link_files, retry=retry,
                    force_duplicates=force_duplicates)
            )
        return imported_templates

    def _bulk_import_runs(self, directory, link_files=False, retry=False):
        runs_to_import = FileSet(
            [os.path.join(directory, '*'), os.path.join(directory, '*/*')],
            self.storage_settings, retry=retry, raise_if_missing=False)
        imported_runs = []
        for run_to_import in runs_to_import:
            imported_runs.append(
                self.import_run(
                    run_to_import, link_files=link_files, retry=retry)
            )
        return imported_runs

    def import_from_patterns(self, patterns, comments, link=False,
                            ignore_metadata=False, force_duplicates=False,
                            from_metadata=False, retry=False):
        files = []
        for source in FileSet(patterns, self.storage_settings, retry=retry,
                              trim_metadata_suffix=True):
            files.append(self.import_file(
                source.get_url(),
                comments,
                link=link,
                ignore_metadata=ignore_metadata,
                force_duplicates=force_duplicates,
                retry=retry))
        return files

    def _get_file_metadata(self, metadata_url, retry=False, ignore_metadata=False):
        if ignore_metadata:
            return None

        try:
            raw_metadata = File(
                metadata_url,
                self.storage_settings, retry=retry).read()
        except:
            return None

        if not raw_metadata:
            return None

        try:
            return yaml.load(raw_metadata, Loader=yaml.SafeLoader)
        except yaml.parser.ParserError:
            raise ImportManagerError(
                'Metadata is not valid YAML format: "%s"' % metadata_url)
        except yaml.scanner.ScannerError as e:
            raise ImportManagerError(
                'Metadata is not valid YAML format: "%s"' % metadata_url)

    def import_file(self, requested_source_url, comments, link=False,
                    ignore_metadata=False, force_duplicates=False,
                    retry=False):
        # A file "mydata.txt" may have a corresponding metadata file
        # "mydata.txt.metadata.yaml". We use the naming convention to determine
        # whether requested_source_url points to the raw file or the metadata,
        # and get the names for the file-metadata pair.
        source_file_url, metadata_url = self._get_file_and_metadata_urls(
            requested_source_url)

        # Attempt to read metadata from the metadata file, if it exists.
        metadata = self._get_file_metadata(
            metadata_url, retry=retry, ignore_metadata=ignore_metadata)
        source_file = self._get_source_file(source_file_url, metadata, retry=retry)

        return self._import_file_and_metadata(
            source_file, metadata, comments, link=link,
            force_duplicates=force_duplicates, retry=retry)

    def _get_file_and_metadata_urls(self, requested_source_url):
        if requested_source_url.endswith('.metadata.yaml'):
            source_file_url = requested_source_url[:-len('.metadata.yaml')]
            metadata_url = requested_source_url
        else:
            source_file_url = requested_source_url
            metadata_url = source_file_url + '.metadata.yaml'
        return source_file_url, metadata_url

    def _get_source_file(self, source_url, metadata, retry=False):
        source = File(source_url, self.storage_settings, retry=retry)
        if not source.exists() or source.is_dir():
            source = self._get_source_file_from_metadata(
                source_url, metadata, retry=retry)
        return source
        
    def _get_source_file_from_metadata(
            self, original_source_url, metadata, retry=False):
        try:
            source_url = metadata['value']['file_url']
        except KeyError:
            raise ImportManagerError(
                'Could not find file "%s", and could not find alternative '\
                'file_url in the metadata file.' % original_source_url)
        return File(source_url, self.storage_settings, retry=retry)

    def _import_file_and_metadata(self, source, metadata, comments, link=False,
                             force_duplicates=False, retry=False):
        try:
            data_object = self._render_file_data_object_dict(
                source, comments, metadata=metadata, link=link)
            try:
                data_object = self._check_for_file_duplicates(
                    data_object, force_duplicates=force_duplicates)
            except FileDuplicateError:
                return
            try:
                data_object = self.connection.post_data_object(data_object)
            except ServerConnectionError as e:
                raise ImportManagerError(
                    "Failed to POST DataObject: '%s'. %s"
                    % (data_object, e.message))
            data_object = self._execute_file_import(
                data_object, source, retry=retry)
            return data_object
        except HTTPError as e:
            if e.response.status_code==400:
                errors = e.response.json()
                raise SystemExit(
                    "ERROR! %s" % errors)
            else:
                raise

    def _check_for_file_duplicates(self, data_object, force_duplicates=False):
        # If UUID matches existing object, no duplicate can be created
        if data_object.get('uuid'):
            existing_file = self.connection.get_data_object(data_object.get('uuid'))
            if existing_file:
                # No need to import, but do not raise warning. This will cause
                # duplicate warnings when importing templates that reference
                # the file multiple times.
                return data_object
        # No check if "force_duplicates" is set
        if force_duplicates:
            return data_object
        filename = data_object['value']['filename']
        md5= data_object['value']['md5']
        if data_object.get('uuid') is None:
            # Skip import if no UUID provided and duplicate is found.
            files = self._get_file_duplicates(filename, md5)
            if len(files) > 0:
                logger.warn(
                    'Found existing file that matches name and md5 hash "%s$%s". '\
                    'Using existing file and skipping new file import.'
                    % (filename, md5))
                raise FileDuplicateError
            else:
                # No UUID, no match. Create new data object
                return data_object
        else:
            # UUID is new to database. Create new data object
            return data_object

    def _get_file_duplicates(self, filename, md5):
        files = self.connection.get_data_object_index(
            query_string='%s$%s' % (filename, md5), type='file')
        return files

    def _render_file_data_object_dict(
            self, source, comments, metadata=None, link=False):
        if metadata is None:
            metadata = {}
        metadata_file_resource = metadata.get('value', {})
        if metadata:
            assert not comments, \
                'New comments are not allowed if metadata is used'
            comments = metadata_file_resource.get('import_comments', '')
        filename = metadata_file_resource.get('filename', source.get_filename())
        file_relative_path = metadata_file_resource.get('file_relative_path', None)
        logger.info('Calculating md5 on file "%s"...' % source.get_url())
        md5 = source.calculate_md5()
        metadata_md5 = metadata_file_resource.get('md5')
        imported_from_url = metadata_file_resource.get(
            'imported_from_url', source.get_url())
        source_type = metadata_file_resource.get('source_type', 'imported')
        if metadata_md5 and md5 != metadata_md5:
            raise ImportManagerError(
                'md5 of file "%s" does not match value in its metadata '\
                'file. The file may have been corrupted. If it was changed '\
                'intentionally, you should not use the old metadata.'
                % source.get_url())
        file_data_object = {
            'type': 'file',
            'value':{
                'filename': filename,
                'md5': md5,
                'imported_from_url': imported_from_url,
                'source_type': source_type,
                'link': False,
            }
        }
        if link:
            file_data_object['value'].update({
                'file_url': source.get_url(),
                'upload_status': 'complete',
                'link': True,
            })
        if file_relative_path:
            file_data_object['value']['file_relative_path'] = file_relative_path
        if comments:
            file_data_object['value']['import_comments'] = comments
        if metadata.get('uuid'):
            file_data_object['uuid'] = metadata.get('uuid')
        if metadata.get('datetime_created'):
            file_data_object['datetime_created'] = metadata.get('datetime_created')
        return file_data_object

    def import_result_file(self, task_attempt_output, source_url, retry=False):
        logger.info('Calculating md5 on file "%s"...' % source_url)
        source = File(source_url, self.storage_settings, retry=retry)
        md5 = source.calculate_md5()
        task_attempt_output = self._create_task_attempt_output_file(
            task_attempt_output, md5, source.get_filename())
        data_object = task_attempt_output['data']['contents']
        return self._execute_file_import(data_object, source, retry=retry)

    def _create_task_attempt_output_file(
            self, task_attempt_output, md5, filename):
        return self.connection.update_task_attempt_output(
            task_attempt_output['uuid'],
            {
                'data': {
                    'type': 'file',
                    'contents': {
                        'type': 'file',
                        'value': {
                            'filename': filename,
                            'source_type': 'result',
                            'md5': md5,
                        }}}})

    def import_result_file_list(self, task_attempt_output, source_url_list,
                                retry=False):
        md5_list = []
        filename_list = []
        for source_url in source_url_list:
            logger.info('Calculating md5 on file "%s"...' % source_url)
            source = File(source_url, self.storage_settings, retry=retry)
            md5_list.append(source.calculate_md5())
            filename_list.append(source.get_filename())
        task_attempt_output = self._create_task_attempt_output_file_array(
            task_attempt_output, md5_list, filename_list)
        data_object_array = task_attempt_output['data']['contents']
        imported_data_objects = []
        for (source_url, data_object) in zip(source_url_list, data_object_array):
            source = File(source_url, self.storage_settings, retry=retry)
            imported_data_objects.append(
                self._execute_file_import(data_object, source, retry=retry))
        return imported_data_objects

    def _create_task_attempt_output_file_array(
            self, task_attempt_output, md5_array, filename_array):
        contents = []
        for md5, filename in zip(md5_array, filename_array):
            contents.append({
                'type': 'file',
                'value': {
                    'filename': filename,
                    'source_type': 'result',
                    'md5': md5,
                }})
        return self.connection.update_task_attempt_output(
            task_attempt_output['uuid'],
            {
                'data': {
                    'type': 'file',
                    'contents': contents
                }})

    def import_log_file(self, task_attempt, source_url, retry=False):
        log_name = os.path.basename(source_url)
        log_file = self.connection.post_task_attempt_log_file(
            task_attempt['uuid'], {'log_name': log_name})

        logger.info('Calculating md5 on file "%s"...' % source_url)
        source = File(source_url, self.storage_settings, retry=retry)
        md5 = source.calculate_md5()

        data_object = self.\
                      connection.post_task_attempt_log_file_data_object(
                          log_file['uuid'],
                          {
                              'type': 'file',
                              'value': {
                                  'filename': log_name,
                                  'source_type': 'log',
                                  'md5': md5,
                }})
        
        return self._execute_file_import(data_object, source, retry=retry)

    def _execute_file_import(self, file_data_object, source, retry=False):
        logger.info('Importing file from %s...' % source.get_url())
        if file_data_object['value'].get('upload_status') == 'complete':
            logger.info(
                '   Skipping upload because server already has the file %s@%s.' % (
                    file_data_object['value'].get('filename'),
                    file_data_object.get('uuid')))
            return file_data_object
        try:
            destination = File(
                file_data_object['value']['file_url'],
                self.storage_settings,
                retry=retry)
            logger.info(
                '   copying to destination %s ...' % destination.get_url())
            source.copy_to(destination)
        except ApplicationDefaultCredentialsError as e:
            self._set_upload_status(file_data_object, 'failed')
            raise SystemExit(
                'ERROR! '\
                'Google Cloud application default credentials are not set. '\
                'Please run "gcloud auth application-default login"')
        except Exception as e:
            self._set_upload_status(file_data_object, 'failed')
            raise

        # Signal that the upload completed successfully
        file_data_object = self._set_upload_status(
            file_data_object, 'complete')
        logger.info('   imported file %s@%s' % (
            file_data_object['value']['filename'],
            file_data_object['uuid']))
        return file_data_object

    def _set_upload_status(self, file_data_object, upload_status):
        """ Set file_data_object.file_resource.upload_status
        """
        uuid = file_data_object['uuid']
        return self.connection.update_data_object(
            uuid,
            {'uuid': uuid, 'value': { 'upload_status': upload_status}}
        )

    def import_template(self, template_file, comments=None,
                        force_duplicates=False,
                        retry=False, link_files=False):
        self._print('Importing template from "%s".' % template_file.get_url())
        template = self._get_template(template_file)
        importable_template = self._recursive_import_template(
            template, template_file.get_url(),
            force_duplicates=force_duplicates,
            retry=retry, link_files=link_files)

        if importable_template is None:
            self._print('  Skipping import because template already exists.')
            return

        if not importable_template.get('comments'):
            if comments:
                importable_template.update({'import_comments': comments})
        if not importable_template.get('imported_from_url'):
            importable_template.update({'imported_from_url': template_file.get_url()})

        try:
            imported_template = self.connection.post_template(importable_template)
        except HTTPError as e:
            if e.response.status_code==400:
                errors = e.response.json()
                raise SystemExit(
                    "ERROR! %s" % errors)
            else:
                raise

        self._print('Imported template "%s@%s".' % (
            imported_template['name'],
            imported_template['uuid']))
        return imported_template

    def import_run(self, run_file,
                   force_duplicates=False,
                   retry=False, link_files=False):
        self._print('Importing run from "%s".' % run_file.get_url())
        run = self._get_run(run_file)
        dependencies_dir = run_file.get_url()+'.dependencies'
        files_dir = os.path.join(dependencies_dir, 'files')
        templates_dir = os.path.join(dependencies_dir, 'templates')
        self._bulk_import_files(
            files_dir, force_duplicates=force_duplicates,
            retry=retry, link_files=link_files)
        self._bulk_import_templates(
            templates_dir, force_duplicates=force_duplicates,
            retry=retry, link_files=link_files)
        try:
            imported_run = self.connection.post_run(run)
        except HTTPError as e:
            if e.response.status_code==400:
                errors = e.response.json()
                raise SystemExit(
                    "ERROR! %s" % errors)
            else:
                raise

        self._print('Imported run "%s@%s".' % (
            run['name'],
            run['uuid']))
        return run

    def _recursive_import_template(
            self, template, template_url, force_duplicates=False, retry=False,
            parent_file_dependency_node=None, link_files=False):

        # If UUID matches existing object, no duplicate can be created
        if template.get('uuid'):
            existing_template = self.connection.get_template(template.get('uuid'))
            if existing_template:
                # No need to import
                logger.warn(
                    'Found existing template that matches name and uuid '\
                    '"%s@%s". Using existing template and skipping new '\
                    'template import.' \
                    % (existing_template['name'], existing_template['uuid']))
                return existing_template
        elif not force_duplicates:
            # If no UUID and force_duplicates==False,
            # check for duplicates based on hash
                duplicate = self._get_template_duplicate(template)
                if duplicate:
                    logger.warn(
                        'Found existing template that matches name and md5 hash '\
                        '"%s$%s". Using existing template and skipping new '\
                        'template import.' % (duplicate['name'], duplicate['md5']))
                    return duplicate
        file_dependency_node = self._import_file_dependencies(
            template_url, force_duplicates=force_duplicates,
            retry=retry, link_files=link_files,
            parent_file_dependency_node=parent_file_dependency_node)
        self._substitute_file_uuids_throughout_template(template, file_dependency_node)
        template_dependency_files = self._get_template_dependencies(
            template_url, force_duplicates=force_duplicates, retry=retry)
        for template_dependency_file in template_dependency_files:
            template_dependency = self._get_template(template_dependency_file)
            imported_template_dependency = self._recursive_import_template(
                template_dependency, template_dependency_file.get_url(),
                force_duplicates=force_duplicates, retry=retry)
            self._replace_matching_step(template, imported_template_dependency)
        return template

    def _replace_matching_step(self, template, step_template):
        match = False
        for i in range(len(template.get('steps', []))):
            if not isinstance(template['steps'][i], str):
                match = True
                continue
            elif self._does_reference_match_template(
                    template['steps'][i], step_template):
                template['steps'][i] = step_template
                match = True
                continue
        if not match:
            logger.warn('WARNING! Template dependency "%s" was not used. '\
                        'Check "steps" in the parent template' \
                        % step_template.get('name'))

    def _does_reference_match_template(self, reference, template):
        assert isinstance(reference, str)
        name, uuid, tag, md5 = self._parse_reference_string(reference)
        template_name = template.get('name')
        template_uuid = template.get('uuid')
        template_md5 = template.get('md5')
        if uuid and uuid != template_uuid:
            return False
        if name and name != template_name:
            return False
        if md5 and md5 != template_md5:
            return False
        return True

    @classmethod
    def _get_template(self, template_file):
        md5 = template_file.calculate_md5()
        try:
            template_text = template_file.read()
        except Exception as e:
            raise SystemExit('ERROR! Unable to read file "%s". %s'
                             % (template_file.get_url(), str(e)))
        template = parse_as_yaml(template_text)
        try:
            template.update({'md5': md5})
        except AttributeError:
            raise SystemExit(
                'ERROR! Template at "%s" could not be parsed into a dict.'
                % template_file.get_url())
        return template

    @classmethod
    def _get_run(self, run_file):
        try:
            run_text = run_file.read()
        except Exception as e:
            raise SystemExit('ERROR! Unable to read file "%s". %s'
                             % (run_file.get_url(), str(e)))
        run = parse_as_yaml(run_text)
        return run

    def _get_template_duplicate(self, template):
	md5 = template.get('md5')
        name = template.get('name')
        templates = self.connection.get_template_index(
            query_string='%s$%s' % (name, md5))
        if len(templates) > 0:
            # Get detail view of last duplicate
            return self.connection.get_template(templates[-1]['uuid'])
        else:
            return None

    def _import_file_dependencies(
            self, file_url, force_duplicates=False,
            retry=False, link_files=False,
            parent_file_dependency_node=None):
        file_dependencies = DependencyNode(parent=parent_file_dependency_node)
        file_directory = os.path.join(file_url+'.dependencies', 'files')
        patterns = [os.path.join(file_directory, '*'),
                    os.path.join(file_directory, '*/*')]
        files_to_import = FileSet(
            patterns, self.storage_settings, trim_metadata_suffix=True, retry=retry,
            raise_if_missing=False)
        for file_to_import in files_to_import:
            file_data_object = self.import_file(
                file_to_import.get_url(), '', link=link_files, retry=retry,
                force_duplicates=force_duplicates)
            if file_data_object:
                file_dependencies.file_data_objects.append(file_data_object)
        return file_dependencies

    def _get_template_dependencies(
            self, template_url, force_duplicates=False, retry=False):
        step_dependencies = []
        pattern = os.path.join(template_url+'.dependencies', 'templates', '*')
        step_files = FileSet([pattern,], self.storage_settings, retry=retry,
                             raise_if_missing=False)
        return step_files

    def _substitute_file_uuids_throughout_template(self, template, file_dependencies):
        """Anywhere in "template" that refers to a data object but does not 
        give a specific UUID, if a matching file can be found in "file_dependencies",
        we will change the data object reference to use that UUID. That way templates
        have a preference to connect to files nested under their ".dependencies" over
        files that were previously imported to the server.
        """
        if not isinstance(template, dict):
            # Nothing to do if this is a reference to a previously imported template.
            return
        for input in template.get('inputs', []):
            self._substitute_file_uuids_in_input(input, file_dependencies)
        for step in template.get('steps', []):
            self._substitute_file_uuids_throughout_template(step, file_dependencies)

    def _substitute_file_uuids_in_input(self, input, file_dependencies):
        if input.get('data'):
            if input.get('type') != 'file':
                return input
            if input['data'].get('uuid'):
                return input
            elif input['data'].get('contents'):
                input['data']['contents'] \
                    = self._substitute_file_uuids_in_input_data_contents(
                        input['data']['contents'], file_dependencies)
        return input

    def _substitute_file_uuids_in_input_data_contents(
            self, contents, file_dependencies):
        if isinstance(contents, list):
            return [self._substitute_file_uuids_in_input_data_contents(
                item, file_dependencies)
                    for item in contents]
        elif isinstance(contents, str):
            name, uuid, tag, md5 = self._parse_reference_string(contents)
            if uuid or tag:
                # No need to do the substitution if it's a uuid or tag, since these
                # unique identifiers can only match one record
                return contents
        else:
            name = contents.get('name')
            md5 = contents.get('md5')
        matches = self._get_matches_from_file_dependencies(file_dependencies, name, md5)
        if len(matches) == 1:
            return matches[0]
        elif len(matches) == 0:
            return contents
        else:
            raise Exception('Multiple files match input: "%s$%s"' % (name, md5))

    def _get_matches_from_file_dependencies(self, file_dependencies, name, md5):
        file_data_objects = file_dependencies.file_data_objects
        if name and md5:
            return filter(lambda do, name=name, md5=md5:
                          do['value'].get('filename') == name and
                          do['value'].get('md5') == md5,
                          file_data_objects)
        elif name:
            return filter(lambda do, name=name,:
                          do['value'].get('filename') == name,
                          file_data_objects)
        elif md5:
            return filter(lambda do, md5=md5:
                          do['value'].get('md5') == md5,
                          file_data_objects)
        else:
            raise Exception('No name, md5, or uuid found for input')

    def _parse_reference_string(self, input_data_string):
        name = None
        uuid = None
        tag = None
        hash_value = None
        name_match = re.match('^(?!\$|@|:)(.+?)($|\$|@|:)', input_data_string)
        if name_match is not None:
            name = name_match.groups()[0]
        # id starts with @ and ends with $ or end of string
        uuid_match = re.match('^.*?@(.*?)($|\$|:)', input_data_string)
	if uuid_match is not None:
            uuid = uuid_match.groups()[0]
        # tag starts with $ and ends with @ or end of string
        tag_match = re.match('^.*?:(.*?)($|\$|@)', input_data_string)
        if tag_match is not None:
            tag = tag_match.groups()[0]
        # hash starts with $ and ends with @ or end of string
        hash_match = re.match('^.*?\$(.*?)($|@|:)', input_data_string)
        if hash_match is not None:
            hash_value = hash_match.groups()[0]
        return name, uuid, tag, hash_value
