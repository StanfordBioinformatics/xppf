import copy
import errno
import fnmatch
import glob
import google.cloud.storage
import google.cloud.exceptions
import logging
import os
import random
import re
from requests.exceptions import HTTPError
import shutil
import sys
import tempfile
import time
import urlparse
import warnings
import yaml

from . import execute_with_retries
from . import md5calc
from .exceptions import LoomengineUtilsError, APIError, FileUtilsError, \
    Md5ValidationError, UrlValidationError, InvalidYamlError, NoFileError
from .connection import Connection

# Google Storage JSON API imports
from oauth2client.client import HttpAccessTokenRefreshError
from oauth2client.client import ApplicationDefaultCredentialsError
import apiclient.discovery

logger = logging.getLogger(__name__)

def parse_as_yaml(text):
    try:
        data = yaml.load(text, Loader=yaml.SafeLoader)
    except yaml.parser.ParserError:
        raise InvalidYamlError('Text is not valid YAML format')
    except yaml.scanner.ScannerError as e:
        raise InvalidYamlError(e.message)
    return data

def read_as_yaml(file):
    try:
        with open(file) as f:
            text = f.read()
    except IOError:
        raise NoFileError(
            'Could not find or could not read file %s' % file)

    try:
        return parse_as_yaml(text)
    except InvalidYamlError:
        raise InvalidYamlError(
            'Input file "%s" is not valid YAML format' % file)

def _validate_url(url):
    if (url.scheme == 'file' or url.scheme == ''):
        if url.hostname is not None:
            raise UrlValidationError(
                'Cannot process URL %s. '\
                'Remote file hosts not supported.' % url.geturl())
    if url.scheme not in ['gs', 'file', '']:
        raise UrlValidationError('Cannot recognize file scheme in "%s". '\
                             'Make sure the pattern starts with a '\
                             'supported protocol like gs:// or file://'
                             % url.geturl())

def _urlparse(path):
    """Like urlparse except it assumes 'file://' if no scheme is specified
    """
    url = urlparse.urlparse(path)
    _validate_url(url)
    if not url.scheme or url.scheme == 'file://':
        # Normalize path, and set scheme to "file" if missing
        path = os.path.abspath(
            os.path.expanduser(path))
        url = urlparse.urlparse('file://'+path)
    return url


class FileSet:

    def __init__(self, patterns, settings, retry=False, trim_metadata_suffix=False, raise_if_missing=True):
        """Returns a list of unique Files matching the given patterns.
        """
        assert isinstance(patterns, list), 'patterns must be a list'
        self.settings = settings
        self.retry = retry
        self.raise_if_missing=raise_if_missing
        self.do_trim_metadata_suffix = trim_metadata_suffix
        self.files = []
        self.urls = set()
        self._parse_patterns(patterns)

    def _parse_patterns(self, patterns):
        for pattern in patterns:
            self._parse_pattern(pattern)

    def _parse_pattern(self, pattern):
        for file in FilePattern(
                pattern, self.settings, retry=self.retry,
                trim_metadata_suffix=self.do_trim_metadata_suffix,
                raise_if_missing=self.raise_if_missing):
            self._add_file(file)

    def _add_file(self, file):
        # Only add a file if it is unique
        if file.get_url() not in self.urls:
            self.urls.add(file.get_url())
            self.files.append(file)

    def __iter__(self):
        return self.files.__iter__()

    def __len__(self):
        return self.files.__len__()


def FilePattern(pattern, settings, **kwargs):
    """Factory method returns LocalFilePattern or GoogleStorageFilePattern
    """
    url = _urlparse(pattern)
    if url.scheme == 'gs':
        return GoogleStorageFilePattern(pattern, settings, **kwargs)
    else:
        assert url.scheme == 'file'
        return LocalFilePattern(pattern, settings, **kwargs)


class AbstractFilePattern:

    def _trim_metadata_suffix(self, all_matches):
        if not self.do_trim_metadata_suffix:
            return all_matches

        # For any file <filename>.metadata.yaml, return just <filename>
        return map(lambda path: path[:-len('.metadata.yaml')]
                   if path.endswith('.metadata.yaml')
                   else path,
                   all_matches)

    def _strip_file_scheme(self, path):
        return re.sub('^file://', '', path)

    def __iter__(self):
        return self.files.__iter__()


class LocalFilePattern(AbstractFilePattern):
    """Creates an iterable set of Files that match the given pattern.
    Pattern may include wildcards.
    """

    """A set of Files for files on local storage
    """

    def __init__(self, pattern, settings, retry=False, trim_metadata_suffix=False, raise_if_missing=True):
        # retry has no effect
        self.do_trim_metadata_suffix = trim_metadata_suffix
        self.raise_if_missing = raise_if_missing

        self.files = [
            LocalFile(path, settings, retry=retry)
            for path in self._get_matching_paths(pattern)]

    def _get_matching_paths(self, pattern):
        matches = glob.glob(self._strip_file_scheme(pattern))
        matches = self._remove_directories(matches)
        matches = self._trim_metadata_suffix(matches)
        if self.raise_if_missing and len(matches) == 0:
            raise NoFileError('No files found for pattern "%s"' % pattern)
        return matches

    def _remove_directories(self, all_matches):
        return filter(lambda path: os.path.isfile(path), all_matches)


class GoogleStorageClient:

    # CHUNK_SIZE must be multiple of 256.
    # 2016-08-30: With default 1024*1024, download is 20x slower than gsutil.
    CHUNK_SIZE = 1024*1024*100 

    def get_client(self):
        try:
            if self.retry:
                self.client = execute_with_retries(
                    lambda: google.cloud.storage.client.Client(
                        self.settings['GCE_PROJECT']),
                    (Exception,),
                    logger,
                    'Get client')
            else:
                self.client = google.cloud.storage.client.Client(
                    self.settings['GCE_PROJECT'])
        except ApplicationDefaultCredentialsError as e:
            raise SystemExit(
                'ERROR! '\
                'Google Cloud application default credentials are not set. '\
                'Please run "gcloud auth application-default login"')

    def get_bucket(self, bucket_id):
        try:
            if self.retry:
                self.bucket = execute_with_retries(
                    lambda: self.client.get_bucket(bucket_id),
                    (Exception,),
                    logger,
                    'Get bucket',
                    nonretryable_errors=(google.cloud.exceptions.Forbidden,),
                )
            else:
                self.bucket = self.client.get_bucket(bucket_id)
        except HttpAccessTokenRefreshError:
            raise FileUtilsError(
                'Failed to access bucket "%s". Are you logged in? '\
                'Try "gcloud auth login"' % bucket_id)
        
    def get_blob(self, blob_id, must_exist=False):
        if self.retry:
            self.blob = execute_with_retries(
                lambda: self.bucket.get_blob(blob_id),
                (Exception,),
                logger,
                'Get blob',
                nonretryable_errors=(google.cloud.exceptions.Forbidden,),
            )
        else:
            self.blob = self.bucket.get_blob(blob_id)

        if self.blob is None:
            if must_exist and not blob_id.endswith('/'):
                raise FileUtilsError('Blob not found: "%s"' % blob_id)
            self.blob = google.cloud.storage.blob.Blob(
                self.blob_id, self.bucket, chunk_size=self.CHUNK_SIZE)
        if self.blob.size > self.CHUNK_SIZE:
            self.blob.chunk_size = self.CHUNK_SIZE


class GoogleStorageFilePattern(AbstractFilePattern, GoogleStorageClient):
    """A set of Files for files on Google Storage
    """

    def __init__(self, pattern, settings, retry=False, trim_metadata_suffix=False, raise_if_missing=True):
        # retry has no effect
        self.do_trim_metadata_suffix = trim_metadata_suffix
        self.raise_if_missing = raise_if_missing
        self.settings = settings
        self.url = _urlparse(pattern)
        self.retry = retry
        assert self.url.scheme == 'gs'
        self.bucket_id = self.url.hostname
        self.blob_pattern = self.url.path.lstrip('/')
        if not self.bucket_id:
            raise FileUtilsError(
                'Could not parse bucket ID in url "%s". '\
                'Be sure to use the format "gs://bucket/blob_id".' % url)
        try:
            self.get_client()
            self.get_bucket(self.bucket_id)
            self._get_matching_blobs(self.blob_pattern)

            self.files = [
                GoogleStorageFile('gs://%s/%s' % (self.bucket_id, blob_id),
                                  settings, retry=retry)
                for blob_id in self._get_matching_blobs(self.blob_pattern)]
        except google.cloud.exceptions.InternalServerError as e:
            raise APIError(
                "%s.%s: %s" %
                (e.__class__.__module__, e.__class__.__name__, e))


    def _get_matching_blobs(self, blob_pattern):
        # Google doesn't support wildcards, so we need to get
        # a list of possible blobs and then use fnmatch.filter
        # to filter by wildcard pattern.
        # But bucket.list_blobs is slow if there are a lot of blobs, so
        # we use the only filter available: prefix. Whatever blob_pattern
        # text comes before the first wildcard gives our prefix.
        prefix = re.match('(^[^\*\?]*)', blob_pattern).group()
        blobs = self.bucket.list_blobs(prefix=prefix)
        blob_ids = [b.name for b in blobs]
        matches = fnmatch.filter(blob_ids, blob_pattern)
        matches = self._trim_metadata_suffix(matches)
        return matches

    def __iter__(self):
        return self.files.__iter__()


def File(url, settings, retry=False):
    """Factory method
    """
    parsed_url = _urlparse(url)

    if parsed_url.scheme == 'gs':
        return GoogleStorageFile(url, settings, retry=retry)
    elif parsed_url.scheme == 'file':
        if parsed_url.hostname == 'localhost' or parsed_url.hostname is None:
            return LocalFile(url, settings, retry=retry)
        else:
            raise FileUtilsError(
                "Cannot process file url %s. Remote file hosts not supported."
                % url)
    else:
        raise FileUtilsError('Unsupported scheme "%s" in file "%s"'
                        % (parsed_url.scheme, url))


class AbstractFile:
    """A File represents a single file that to be copied to or from, 
    or otherwise manipulated.
    """

    def __init__(self, url, settings, retry=False):
        raise FileUtilsError('Child class must override this method')

    def copy_to(self, destination, expected_md5=None):
        if self.retry or destination.retry:
            tries_remaining = 2
        else:
            tries_remaining = 1

        while True:
            try:
                copier = Copier(self, destination)
                copier.copy()
                destination.verify_md5(expected_md5)
                break
            except Md5ValidationError as e:
                logger.info('Copied file did not have the expected md5. '\
                            '%s retries remaining' % tries_remaining)
                if tries_remaining == 0:
                    raise
                tries_remaining -= 1
                destination.delete()

    def verify_md5(self, expected_md5):
        if expected_md5:
            md5 = self.calculate_md5()
            if md5 != expected_md5:
                raise Md5ValidationError(
                    'Expected md5 "%s" for file "%s", but found md5 "%s"'
                    % (expected_md5, self.get_url(), md5))

    def get_path(self):
        return self.url.path

    def get_filename(self):
        return os.path.basename(self.get_path())

    def calculate_md5(self):
        raise FileUtilsError('Child class must override this method')
    def get_url(self):
        raise FileUtilsError('Child class must override this method')
    def exists(self):
        raise FileUtilsError('Child class must override this method')
    def is_dir(self):
        raise FileUtilsError('Child class must override this method')
    def read(self, content):
        raise FileUtilsError('Child class must override this method')
    def write(self, content, overwrite=False):
        raise FileUtilsError('Child class must override this method')
    def delete(self, pruneto=None):
        raise FileUtilsError('Child class must override this method')

class LocalFile(AbstractFile):
    """For files saved on local storage.
    """

    type = 'local'

    def __init__(self, url, settings, retry=False):
        self.url = _urlparse(url)
        self.retry = retry

    def calculate_md5(self):
        return md5calc.calculate_md5sum(self.get_path())

    def get_url(self):
        return self.url.geturl()

    def exists(self):
        return os.path.exists(self.get_path())

    def is_dir(self):
        return os.path.isdir(self.get_path())

    def read(self):
        try:
            with open(self.get_path()) as f:
                return f.read()
        except IOError as e:
            raise FileUtilsError(e.message)

    def write(self, content, overwrite=False):
        try:
            os.makedirs(os.path.dirname(self.get_path()))
        except OSError as e:
            # This error just means the dir already exists. Ok.
            if e.errno == errno.EEXIST:
                pass
            else:
                raise FileUtilsError(str(e))
        if not overwrite and self.exists():
            raise FileUtilsError(
                'Destination file already exists at "%s"' % self.get_path())
        with open(self.get_path(), 'w') as f:
            f.write(content)

    def delete(self, pruneto=None):
        os.remove(self.get_path())
        path = os.path.dirname(self.get_path())

        if pruneto is None:
            return

        # Delete any empty directories up to pruneto
        while os.path.dirname(path).startswith(pruneto):
            try:
                os.rmdir(path)
                path = os.path.dirname(path)
            except OSError:
                return


class GoogleStorageFile(AbstractFile, GoogleStorageClient):
    """For file saved on Google Storage
    """
    type = 'google_storage'

    def __init__(self, url, settings, retry=False, must_exist=False):
        self.settings = settings
        self.url = _urlparse(url)
        self.retry = retry
        assert self.url.scheme == 'gs'
        self.bucket_id = self.url.hostname
        self.blob_id = self.url.path.lstrip('/')
        if not self.bucket_id:
            raise FileUtilsError(
                'Could not parse bucket ID in url "%s". '\
                'Be sure to use the format "gs://bucket/blob_id".' % url)
        try:
            self.get_client()
            self.get_bucket(self.bucket_id)
            self.get_blob(self.blob_id, must_exist=must_exist)
        except google.cloud.exceptions.InternalServerError as e:
            raise APIError(
                "%s.%s: %s" %
                (e.__class__.__module__, e.__class__.__name__, e))

    def calculate_md5(self):
        md5_base64 = self.blob.md5_hash
        md5_hex = md5_base64.decode('base64').encode('hex').strip()
        return md5_hex

    def get_url(self):
        return self.url.geturl()

    def get_filename(self):
        return os.path.basename(self.blob_id)

    def exists(self):
        # Does not work on directories!
        return self.blob.exists()

    def is_dir(self):
        # No dirs in Google Storage, just blobs.
        # Call it a dir if it ends in /
        return self.url.geturl().endswith('/')

    def read(self):
        tempdir = tempfile.mkdtemp()
        dest_file = os.path.join(tempdir, self.get_filename())
        self.copy_to(File(dest_file, self.settings, retry=self.retry))
        with open(dest_file) as f:
            text = f.read()
        os.remove(dest_file)
        os.rmdir(tempdir)
        return text

    def write(self, content, overwrite=False):
        if not overwrite and self.exists():
            raise FileUtilsError(
                'Destination file already exists at "%s"' % path)
        with tempfile.NamedTemporaryFile('w') as f:
            f.write(content)
            f.flush()
            File(f.name, self.settings, retry=self.retry).copy_to(self)

    def delete(self, pruneto=None):
        # pruning is automating in Google Storage
        self.blob.delete()


def Copier(source, destination):
    """Factory method to select the right copier for a given source and destination.
    """

    if source.type == 'local' and destination.type == 'local':
        return LocalCopier(source, destination)
    elif source.type == 'local' and destination.type == 'google_storage':
        return Local2GoogleStorageCopier(source, destination)
    elif source.type == 'google_storage' and destination.type == 'local':
        return GoogleStorage2LocalCopier(source, destination)
    elif source.type == 'google_storage' and destination.type == 'google_storage':
        return GoogleStorageCopier(source, destination)
    else:
        raise FileUtilsError('Could not find method to copy from source '\
                        '"%s" to destination "%s".' % (source, destination))


class AbstractCopier:

    def __init__(self, source, destination, retry=False, expected_md5=None):
        self.source = source
        self.destination = destination
        self.expected_md5=expected_md5
        self.retry = self.source.retry or self.destination.retry
            
    def copy(self, path):
        raise FileUtilsError('Child class must override method')

class LocalCopier(AbstractCopier):

    def copy(self):
        # Retry has no effect in local copier
        try:
            os.makedirs(os.path.dirname(self.destination.get_path()))
        except OSError as e:
            # This error just means the dir already exists. Ok.
            if e.errno == errno.EEXIST:
                pass
            else:
                raise FileUtilsError(str(e))
        dest = os.open(self.destination.get_path(),
                       os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(dest, 'w') as f:
            with open(self.source.get_path()) as sf:
                shutil.copyfileobj(sf, f)


class GoogleStorageCopier(AbstractCopier):

    def copy(self):
        rewrite_token = None
        while True:
            if self.retry:
                rewrite_token, rewritten, size = execute_with_retries(
                    lambda: self.destination.blob.rewrite(
                        self.source.blob, token=rewrite_token),
                    (Exception,),
                    logger,
                    'File copy',
                    nonretryable_errors=(google.cloud.exceptions.Forbidden,),
                )
            else:
                rewrite_token, rewritten, size = self.destination.blob.rewrite(
                    self.source.blob, token=rewrite_token)
            logger.info("   copied %s of %s bytes ..." % (rewritten, size))
            if not rewrite_token:
                logger.info("   copy completed ...")
                break


class Local2GoogleStorageCopier(AbstractCopier):

    def copy(self):
        if self.retry:
            execute_with_retries(
                lambda: self.destination.blob.upload_from_filename(
                    self.source.get_path()),
                (Exception,),
                logger,
                'File upload',
                nonretryable_errors=(google.cloud.exceptions.Forbidden,),
            )
        else:
            self.destination.blob.upload_from_filename(self.source.get_path())


class GoogleStorage2LocalCopier(AbstractCopier):

    def copy(self):
        try:
            os.makedirs(os.path.dirname(self.destination.get_path()))
        except OSError as e:
            # This error just means the dir already exists. Ok.
            if e.errno == errno.EEXIST:
                pass
            else:
                raise FileUtilsError(str(e))
        if self.retry:
            execute_with_retries(
                lambda: self.source.blob.download_to_filename(
                    self.destination.get_path()),
                (Exception,),
                logger,
                'File download',
                nonretryable_errors=(google.cloud.exceptions.Forbidden,),
            )
        else:
            self.source.blob.download_to_filename(self.destination.get_path())
