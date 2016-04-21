#!/usr/bin/env python

import abc
from copy import copy
import datetime
import errno
import logging
import os
import shutil
import subprocess
import sys

import gcloud.storage
import requests

from loom.common import md5calc
from loom.common.exceptions import *
from loom.common.objecthandler import ObjectHandler
from loom.common.logger import StreamToLogger

# Google Storage JSON API imports
from apiclient.http import MediaIoBaseDownload
from oauth2client.client import GoogleCredentials
import apiclient.discovery


def FileHandler(master_url, *args, **kwargs):
    """Factory method that communicates with master server to retrieve settings 
    and determine which concrete subclass to instantiate.
    """
    settings = _get_settings(master_url)
    if settings['FILE_SERVER_TYPE'] == 'LOCAL':
        return LocalFileHandler(master_url, settings, *args, **kwargs)
    elif settings['FILE_SERVER_TYPE'] == 'REMOTE':
        return RemoteFileHandler(master_url, settings, *args, **kwargs)
    elif settings['FILE_SERVER_TYPE'] == 'GOOGLE_CLOUD':
        return GoogleCloudFileHandler(master_url, settings, *args, **kwargs)
    else:
        raise UnrecognizedFileServerTypeError(
            'Unrecognized file server type: %s' % settings['FILE_SERVER_TYPE'])

def _get_settings(master_url):
    url = master_url + '/api/filehandlerinfo/'
    try:
        response = requests.get(url)
    except requests.exceptions.ConnectionError:
        raise ServerConnectionError(
            'No response from server at %s. Do you need to run "loom server start"?' \
            % master_url)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise BadResponseError("%s\n%s" % (e.message, response.text))
    settings = response.json()['filehandlerinfo']
    return settings


class AbstractFileHandler:
    """Abstract base class for filehandlers.
    Public interface and required overrides. Perform file transfer or create 
    locations differently depending on fileserver type.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, master_url, settings, logger=None):
        self.objecthandler = ObjectHandler(master_url)
        self.settings = settings
        self.logger = logger
        stdout_logger = StreamToLogger(self.logger, logging.INFO)
        sys.stdout = stdout_logger
        stderr_logger = StreamToLogger(self.logger, logging.ERROR)
        sys.stderr = stderr_logger

    @abc.abstractmethod
    def upload(self, local_path, destination_location):
        pass

    @abc.abstractmethod
    def download(self, source_location, local_path):
        pass

    @abc.abstractmethod
    def get_step_output_location(self, local_path, workflowrun_timestamp, workflow_name, step_name, file_object=None):
        pass

    @abc.abstractmethod
    def get_import_location(self, file_object, timestamp):
        pass

    def _get_import_path(self, file_object, timestamp):
        """Imported files are placed in IMPORT_DIR and named with timestamp, 
        file ID, and filename.
        """
        file_id = file_object.get('_id')
        if file_id is None:
            raise UndefinedFileIDError("File ID must be defined")
        return os.path.join(
            self.settings['FILE_ROOT'],
            self.settings['IMPORT_DIR'],
            "%s_%s_%s" % (timestamp, file_id[0:10], file_object['file_name']),
        )

    def download_by_file_id(self, file_id, local_path):
        storage_locations = self.objecthandler.get_file_storage_locations_by_file(file_id)
        # Attempt to download from each location
        for location in storage_locations:
            if os.path.exists(local_path):
                raise FileAlreadyExistsError('File "%s" already exists' % local_path)
            self.download(location, local_path)
            # TODO handle download failures
            break
    
    def _get_step_output_path(self, local_path, workflowrun_timestamp, workflow_name, step_name):
        """Step outputs are placed in $FILE_ROOT/runs/$workflowrun_timestamp_$workflow_name/$step_name,
        and named with the same file name.
        """
        filename = os.path.basename(local_path)
        return os.path.join(
            self.settings['FILE_ROOT'],
            'runs',
            '_'.join([str(workflowrun_timestamp), workflow_name]),
            step_name,
            filename
        )

    @classmethod
    def create_file_data_object_from_local_path(cls, file_path):
        file_data_object = {
            'file_contents': {
                'hash_value': md5calc.calculate_md5sum(file_path),
                'hash_function': 'md5',
            },
            'file_name': os.path.basename(file_path)
        }
        return file_data_object

    def _log(self, message):
        if not self.logger:
            return
        self.logger.info(message)
    
    def import_files_from_local_paths(self, local_paths, source_record=None, source_directory=None):
        upload_request_time = self.objecthandler.get_server_time()
        file_objects = []
        destination_locations = []
        # Upload files, create FileDataObjects and StorageLocations
        for local_path in local_paths:
            file_objects.append(self.import_file_from_local_path(local_path, source_directory=source_directory, upload_request_time=upload_request_time))
        # Create source_record if one exists
        self._create_source_record(file_objects, source_record=source_record)
        return file_objects
            
    def import_file_from_local_path(self, local_path, source_directory=None, source_record=None, upload_request_time=None):
        """Upload files, create FileDataObjects and StorageLocations
        """
        local_path = self._add_directory(source_directory, local_path)
        
        if upload_request_time is None:
            upload_request_time = self.objecthandler.get_server_time()
        self._log("Uploading %s ..." % local_path)
        file_object = self.create_file_data_object_from_local_path(local_path)
        file_object = self.objecthandler.post_data_object(file_object)

        # Create source_record if called with one as an argument
        self._create_source_record([file_object], source_record=source_record)
        self._log("Created file source record %s@%s" % (file_object['file_name'], file_object['_id']))

        storage_locations = self.objecthandler.get_file_storage_locations_by_file(file_object['_id'])
        if len(storage_locations) == 0:
            destination_location = self.get_import_location(file_object, upload_request_time)
            self._log("Uploading to destination location %s" % destination_location)
            self.upload(local_path, destination_location)
            self.objecthandler.post_file_storage_location(destination_location)

        return file_object

    def upload_step_output_from_local_path(self, local_path, workflowrun_timestamp, workflow_name, step_name, source_directory=None, source_record=None, upload_request_time=None):
        """Upload files, create FileDataObjects and StorageLocations
        """
        local_path = self._add_directory(source_directory, local_path)
        
        if upload_request_time is None:
            upload_request_time = self.objecthandler.get_server_time()
        self._log("Uploading %s ..." % local_path)
        file_data_object = self.create_file_data_object_from_local_path(local_path)
        self._log("Posting file data object %s" % file_data_object)
        file_object = self.objecthandler.post_data_object(file_data_object)
        self._log("Created file object %s" % file_object)

        # Create source_record if called with one as an argument
        result = self._create_source_record([file_object], source_record=source_record)
        self._log("Result of creating source record: %s" % result)
        if result is not None:
            self._log("Created data source record %s@%s" % (file_object['file_name'], file_object['_id'])) 

        storage_locations = self.objecthandler.get_file_storage_locations_by_file(file_object['_id'])
        self._log("Got storage_locations %s" % storage_locations)

        if len(storage_locations) == 0:
            self._log("Trying to get a step output destination location with file object %s, workflowrun_timestamp %s, workflow_name %s, step_name %s, upload_request_time %s" % (file_object, workflowrun_timestamp, workflow_name, step_name, upload_request_time))
            destination_location = self.get_step_output_location(local_path, workflowrun_timestamp, workflow_name, step_name, file_object=file_object)
            self._log("Uploading to destination location %s" % destination_location)
            self.upload(local_path, destination_location)
            self.objecthandler.post_file_storage_location(destination_location)
        else:
            self._log("Not uploading because storage locations already exist: %s" % storage_locations)

        return file_object

    def _add_directory(self, root_directory, local_path):
        if root_directory is None:
            return local_path
        if local_path.startswith('/'):
            raise ValidationError('Cannot use absolute path %s with root directory %s' % (local_path, root_directory))
        return os.path.join(root_directory, local_path)
        
    def _create_source_record(self, data_objects, source_record=None):
        if source_record is not None:
            return self.objecthandler.post_data_source_record(
                {'data_objects': data_objects,
                 'source_description': source_record}
            )
        else:
            return None

    def download_files(self, file_ids, local_names=None, target_directory=None):
        if local_names is None:
            local_names = [None] * len(file_ids)
        if len(local_names) != len(file_ids):
            raise WrongNumberOfFileNamesError('Cannot process %s file_names for %s files. '\
                                              'The lengths must match.' % (len(local_names), len(file_ids)))

        for (file_id, local_name) in zip(file_ids, local_names):
            file = self.objecthandler.get_file_data_object_index(file_id, max=1, min=1)[0]
            # If no local name specified, use the file name from the object.
            if local_name is None:
                local_name = file['file_name']
                # Don't overwrite anyone's root directory based on a file path from the server.
                self._verify_not_absolute(local_name)
            if target_directory is not None:
                # We should never use target directory along with absolute paths.
                if self._is_absolute_path(local_name):
                    raise AbsolutePathInFileNameError('Cannot set download directory since the file name "%s" '\
                                                      'uses an absolute path.' % local_name)
                local_path = os.path.join(os.path.expanduser(target_directory), local_name)
            else:
                local_path = local_name
            self._log('Downloading file %s@%s to %s...' % (file['file_name'], file['_id'], local_path))
            self.download_by_file_id(file['_id'], local_path)
            self._log('...complete.')

    def _verify_not_absolute(self, file_name):
        if self._is_absolute_path(file_name):
            raise AbsolutePathInFileNameError('Refusing to download a file whose name is an absolute path.')

    def _is_absolute_path(self, file_names):
        return any([file_name.startswith('/') for file_name in file_names])


class AbstractPosixPathFileHandler(AbstractFileHandler):
    """Base class for filehandlers that deal with POSIX-style file paths."""
    __metaclass__ = abc.ABCMeta

    def get_step_output_location(self, local_path, workflowrun_timestamp, workflow_name, step_name, file_object=None):
        if file_object is None:
            file_object = create_file_data_object_from_local_path(local_path)
        location = {
            'file_contents': file_object['file_contents'],
            'file_path': self._get_step_output_path(local_path, workflowrun_timestamp, workflow_name, step_name),
            'host_url': self.settings['FILE_SERVER_FOR_WORKER']
            }
        return location

    def get_import_location(self, file_object, timestamp):
        location = {
            'file_contents': file_object['file_contents'],
            'file_path': self._get_import_path(file_object, timestamp),
            'host_url': self.settings['FILE_SERVER_FOR_WORKER']
            }
        return location


class LocalFileHandler(AbstractPosixPathFileHandler):
    """Subclass of FileHandler that uses cp or ln to 'copy' files.
    """
    def upload(self, local_path, destination_location):
        """For imports, create imports directory and copy file.
        For step outputs, don't need to do anything, because the working 
        directory is the destination.
        """
        destination_path = destination_location['file_path']
        if local_path != destination_path:
            try:
                os.makedirs(os.path.dirname(destination_path))
            except OSError as e:
                if e.errno == errno.EEXIST:
                    pass
                else:
                    raise e
            shutil.copyfile(local_path, destination_path)

    def download(self, source_location, local_path):
        """Save space by hardlinking file into the working dir instead of 
        copying. However, won't work if the two locations are on different 
        filesystems.
        """
        cmd = ['ln', source_location['file_path'], local_path]
        subprocess.check_call(cmd)

class RemoteFileHandler(AbstractPosixPathFileHandler):
    """Subclass of FileHandler that uses ssh and scp to copy files."""

    def upload(self, local_path, destination_location):
        destination_path = destination_location['file_path']
        subprocess.check_call(
            ['ssh',
             self.fileserver,
             'mkdir',
             '-p',
             os.path.dirname(destination_path)]
        )
        subprocess.check_call(
            ['scp',
             local_path,
             ':'.join([self.fileserver, destination_path])]
        )

    def download(self, source_location, local_path):
        subprocess.check_call(
            ['scp',
             ':'.join(
                 [source_location['host_url'],
                  source_location['file_path']]
             ),
             local_path]
        )

    def get_cluster_remote_path(self, username):
        if not hasattr(self,'_remote_path'):
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%Hh%Mm%Ss")
            self._remote_path = os.path.join(
                '/home',
                username,
                'working_dir',
                self.IMPORTED_FILES_DIR,
                "%s_%s_%s" % (timestamp, self.file_id[0:10], os.path.split(self.local_path)[1]),
            )
        return self._remote_path


class GoogleCloudFileHandler(AbstractFileHandler):
    """Subclass of FileHandler that uses the gcloud module to copy files to and from Google Storage."""

    def upload(self, local_path, destination_location):
        blob = self._get_blob(destination_location)
        blob.upload_from_filename(local_path)

    def download(self, source_location, local_path):
        blob = self._get_blob(source_location)
        blob.download_to_filename(local_path)

    def download_with_json_api(self, destination_location, local_path):
        """Download using Google Storage JSON API instead of gcloud-python."""
        blob_path = destination_location['blob_path']
        bucket_id = destination_location['bucket_id']
        credentials = GoogleCredentials.get_application_default()
        service = apiclient.discovery.build('storage', 'v1', credentials=credentials)
        file_request = service.objects().get_media(bucket=bucket_id, object=blob_path)
        with open(local_path, 'w') as local_file:
            downloader = MediaIoBaseDownload(local_file, file_request, chunksize=1024*1024)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    print 'Download %d%%.' % int(status.progress() * 100)
                print 'Download Complete!'

    def _get_blob(self, location):
        """Instantiate, configure, and return a gcloud blob."""
        blob_path = location['blob_path']
        project_id = location['project_id']
        bucket_id = location['bucket_id']
        client = gcloud.storage.client.Client(project_id)
        bucket = client.get_bucket(bucket_id)
        blob = bucket.get_blob(blob_path)
        if blob is None:
            blob = gcloud.storage.blob.Blob(blob_path, bucket)
        return blob

    def get_step_output_location(self, local_path, workflowrun_timestamp, workflow_name, step_name, file_object=None):
        if file_object is None:
            file_object = create_file_data_object_from_local_path(local_path)
        location = {
            'file_contents': file_object['file_contents'],
            'project_id': self.settings['PROJECT_ID'],
            'bucket_id': self.settings['BUCKET_ID'],
            'blob_path': self._get_step_output_path(local_path, workflowrun_timestamp, workflow_name, step_name),
            }
        return location

    def get_import_location(self, file_object, timestamp):
        location = {
            'file_contents': file_object['file_contents'],
            'project_id': self.settings['PROJECT_ID'],
            'bucket_id': self.settings['BUCKET_ID'],
            'blob_path': self._get_import_path(file_object, timestamp),
            }
        return location
