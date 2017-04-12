from django.db import models
from django.utils import timezone
import jsonfield
import os

from .base import BaseModel
from api import get_setting
from api.models import uuidstr
from api.exceptions import NoFileMatchError, MultipleFileMatchesError


class TypeMismatchError(Exception):
    pass
class NestedArraysError(Exception):
    pass
class NonArrayError(Exception):
    pass
class InvalidFileServerTypeError(Exception):
    pass
class RelativePathError(Exception):
    pass
class RelativeFileRootError(Exception):
    pass
class InvalidSourceTypeError(Exception):
    pass


class AbstractDataObjectManager():

    def __init__(self, model):
        self.model = model


class BooleanDataObjectManager(AbstractDataObjectManager):

    @classmethod
    def get_by_value(cls, value):
        return BooleanDataObject.objects.create(value=value, type='boolean')

    def get_substitution_value(self):
        return self.model.booleandataobject.value

    def is_ready(self):
        return True


class FileDataObjectManager(AbstractDataObjectManager):

    @classmethod
    def get_by_value(cls, value):
        matches = FileDataObject.filter_by_name_or_id_or_hash(value)
        if matches.count() == 0:
            raise NoFileMatchError(
                'ERROR! No file found that matches value "%s"' % value)
        elif matches.count() > 1:
            match_id_list = ['%s@%s' % (match.filename, match.uuid)
                             for match in matches]
            match_id_string = ('", "'.join(match_id_list))
            raise MultipleFileMatchesError(
                'ERROR! Multiple files were found matching value "%s": "%s". '\
                'Use a more precise identifier to select just one file.' % (
                    value, match_id_string))
        return matches.first()

    def get_substitution_value(self):
        return self.model.filedataobject.filename

    def is_ready(self):
        resource = self.model.filedataobject.file_resource
        return resource is not None and resource.is_ready()


class FloatDataObjectManager(AbstractDataObjectManager):

    @classmethod
    def get_by_value(cls, value):
        return FloatDataObject.objects.create(value=value, type='float')

    def get_substitution_value(self):
        return self.model.floatdataobject.value

    def is_ready(self):
        return True


class IntegerDataObjectManager(AbstractDataObjectManager):

    @classmethod
    def get_by_value(cls, value):
        return IntegerDataObject.objects.create(value=value, type='integer')

    def get_substitution_value(self):
        return self.model.integerdataobject.value

    def is_ready(self):
        return True


class StringDataObjectManager(AbstractDataObjectManager):

    @classmethod
    def get_by_value(cls, value):
        return StringDataObject.objects.create(value=value, type='string')

    def get_substitution_value(self):
        return self.model.stringdataobject.value

    def is_ready(self):
        return True


class ArrayDataObjectManager(AbstractDataObjectManager):

    def get_substitution_value(self):
        return [member.substitution_value
                for member in self.model.members]

    def is_ready(self):
        return all([member.is_ready()
                    for member in self.model.members])


class DataObject(BaseModel):

    _MANAGER_CLASSES = {
        'boolean': BooleanDataObjectManager,
        'float': FloatDataObjectManager,
        'file': FileDataObjectManager,
        'integer': IntegerDataObjectManager,
        'string': StringDataObjectManager,
    }

    _ARRAY_MANAGER_CLASS = ArrayDataObjectManager

    DATA_TYPE_CHOICES = (
        ('boolean', 'Boolean'),
        ('file', 'File'),
        ('float', 'Float'),
        ('integer', 'Integer'),
        ('string', 'String'),
    )

    uuid = models.CharField(default=uuidstr,
                            unique=True, max_length=255)
    type = models.CharField(
        max_length=255,
        choices=DATA_TYPE_CHOICES)
    is_array = models.BooleanField(
        default=False)
    datetime_created = models.DateTimeField(
        default=timezone.now)

    @classmethod
    def _get_manager_class(cls, type):
        return cls._MANAGER_CLASSES[type]
        
    def _get_manager(self):
        if self.is_array:
            return self._ARRAY_MANAGER_CLASS(self)
        else:
            return self._get_manager_class(self.type)(self)

    @classmethod
    def get_by_value(cls, value, type):
        return cls._MANAGER_CLASSES[type].get_by_value(value)
 
    @property
    def substitution_value(self):
        return self._get_manager().get_substitution_value()

    def add_to_array(self, array):
        if not array.is_array:
            raise NonArrayError('Cannot add members when is_array=False')
        if self.is_array:
            raise NestedArraysError('Cannot nest ArrayDataObjects')
        ArrayMembership.objects.create(
            array=array, member=self, order=array.prefetch_members.count())

    def is_ready(self):
        return self._get_manager().is_ready()


class BooleanDataObject(DataObject):

    value = models.BooleanField(null=False)


class FileDataObject(DataObject):

    NAME_FIELD = 'filename'
    HASH_FIELD = 'md5'

    FILE_SOURCE_TYPE_CHOICES = (('imported', 'Imported'),
                                ('result', 'Result'),
                                ('log', 'Log'))

    filename = models.CharField(max_length=1024)
    file_resource = models.ForeignKey('FileResource',
                                      null=True,
                                      related_name='file_data_objects',
                                      on_delete=models.PROTECT,
                                      blank=True)
    md5 = models.CharField(max_length=255, null=True, blank=True)
    source_type = models.CharField(
        max_length=255,
        choices=FILE_SOURCE_TYPE_CHOICES)
    file_import = jsonfield.JSONField(null=True, blank=True)

    def initialize_file_resource(self):
        # Based on settings, choose the path where the
        # file should be stored and create a FileResource
        # with upload_status=incomplete.
        #
        # If a file with identical content has already been uploaded,
        # re-use it if permitted by settings. 
        if not get_setting('KEEP_DUPLICATE_FILES'):
            matching_file_resources = FileResource.objects.filter(
                md5=self.md5,
                upload_status='complete')
            if matching_file_resources.count() > 0:
                # First match is as good as any
                file_resource = matching_file_resources.first()
                self.setattrs_and_save_with_retries({
                    'file_resource': file_resource})
                return self.file_resource
        # No existing file to use. Create a new resource for upload.
        file_resource  = FileResource\
                         .create_incomplete_resource_for_import(self)
        self.setattrs_and_save_with_retries({
            'file_resource': file_resource})
        return self.file_resource


class FloatDataObject(DataObject):

    value = models.FloatField()


class IntegerDataObject(DataObject):

    value = models.IntegerField()


class StringDataObject(DataObject):

    value = models.TextField(max_length=10000)


class ArrayDataObject(DataObject):

    @property
    def members(self):
        return [m.member for m in 
                self.has_array_members_membership.all().select_related('member')]

    prefetch_members = models.ManyToManyField('DataObject',
                                     through='ArrayMembership',
                                     through_fields=('array', 'member'),
                                     related_name='arrays')

    def add_members(self, data_object_list):
        for data_object in data_object_list:
            data_object.add_to_array(self)

    @classmethod
    def create_from_list(cls, data_object_list, type):
        cls._validate_list(data_object_list, type)
        array = ArrayDataObject.objects.create(is_array=True, type=type)
        for data_object in data_object_list:
            data_object.add_to_array(array)
        return array

    @classmethod
    def _validate_list(cls, data_object_list, type):
        for data_object in data_object_list:
            if not data_object.type == type:
                raise TypeMismatchError(
                    'Expected type "%s", but DataObject %s is type %s' \
                    % (type, data_object.uuid, data_object.type))
            if data_object.is_array:
                raise NestedArraysError('Cannot nest ArrayDataObjects')


class ArrayMembership(BaseModel):

    # ManyToMany relationship between arrays and their items
    array = models.ForeignKey('ArrayDataObject',
                              related_name='has_array_members_membership',
                              on_delete=models.CASCADE)
    member = models.ForeignKey('DataObject',
                               related_name='in_array_membership',
                               on_delete=models.CASCADE)
    order = models.IntegerField()

    class Meta:
        ordering = ['order',]


class FileResource(BaseModel):

    FILE_RESOURCE_UPLOAD_STATUS_CHOICES = (('incomplete', 'Incomplete'),
                                           ('complete', 'Complete'),
                                           ('failed', 'Failed'))
    FILE_RESOURCE_UPLOAD_STATUS_DEFAULT = 'incomplete'
    
    uuid = models.CharField(default=uuidstr,
                            unique=True, max_length=255)
    datetime_created = models.DateTimeField(
        default=timezone.now)
    file_url = models.CharField(max_length=1000)
    md5 = models.CharField(max_length=255, null=True, blank=True)
    upload_status = models.CharField(
        max_length=255,
        default=FILE_RESOURCE_UPLOAD_STATUS_DEFAULT,
        choices=FILE_RESOURCE_UPLOAD_STATUS_CHOICES)

    def is_ready(self):
        return self.upload_status == 'complete'
    
    @classmethod
    def create_incomplete_resource_for_import(cls, file_data_object):

        # Get path from root
        path = cls._get_path_for_import(file_data_object)

        # Add url prefix
        file_url = cls._add_url_prefix(path)

        resource = cls.objects.create(file_url=file_url,
                                      upload_status='incomplete',
                                      md5=file_data_object.md5)
        
        return resource

    @classmethod
    def _get_file_root(cls):
        file_root = get_setting('LOOM_STORAGE_ROOT')
        # Allow '~/path' home dir notation on local file server
        if get_setting('LOOM_STORAGE_TYPE') == 'LOCAL':
            file_root = os.path.expanduser(file_root)
        if not file_root.startswith('/'):
            raise RelativeFileRootError(
                'LOOM_STORAGE_ROOT setting must be an absolute path. '\
                'Found "%s" instead.' % file_root)
        return file_root

    @classmethod
    def _get_path_for_import(cls, file_data_object):
        file_root = cls._get_file_root()
        if get_setting('KEEP_DUPLICATE_FILES') and get_setting('FORCE_RERUN'):
            # If both are True, we can organize the directory structure in
            # a human browsable way
            if file_data_object.source_type == 'imported':
                filename = cls._get_filename(file_data_object, timestamp=True,
                                             filename=True, uuid=True)
            elif file_data_object.source_type == 'log':
                filename = cls._get_filename(file_data_object, timestamp=False,
                                             filename=True, uuid=False)
            else: # result
                filename = cls._get_filename(file_data_object, timestamp=False,
                                             filename=True, uuid=True)
            return os.path.join(
                file_root,
                cls._get_browsable_path(file_data_object),
                filename)
        elif get_setting('KEEP_DUPLICATE_FILES'):
            # Separate dirs for imported, results, logs.
            # Within each dir use a flat directory structure but give
            # files with identical content distinctive names
            return os.path.join(
                file_root,
                cls._get_path_by_source_type(file_data_object),
                cls._get_filename(file_data_object, timestamp=True,
                                  filename=True, uuid=True))
        else:
            # Use a flat directory structure and use file names that
            # reflect content
            return os.path.join(
                file_root,
                '%s' % file_data_object.md5)

    @classmethod
    def _get_filename(cls, file_data_object, timestamp, filename, uuid):
        parts = []
        if timestamp:
            parts.append(timezone.now().strftime('%Y-%m-%dT%H.%M.%SZ'))
        if uuid:
            parts.append(str(file_data_object.uuid)[0:8])
        if filename:
            parts.append(file_data_object.filename)
        return '_'.join(parts)

    @classmethod
    def _get_browsable_path(cls, file_data_object):
        """Create a path for a given file, in such a way
        that files end up being organized and browsable by run
        """
        if file_data_object.source_type == 'imported':
            return 'imported'
        
        if file_data_object.source_type == 'log':
            subdir = 'logs'
            task_attempt \
                = file_data_object.task_attempt_log_file.task_attempt
        elif file_data_object.source_type == 'result':
            subdir = 'work'
            task_attempt \
                = file_data_object.task_attempt_output.task_attempt
        else:
            raise InvalidSourceTypeError('Invalid source_type %s'
                            % file_data_object.source_type)

        task = task_attempt.task
        step_run = task.step_run

        path = os.path.join(
            "%s-%s" % (
                str(step_run.uuid)[0:8],
                step_run.template.name,
            ),
            "task-%s" % str(task.uuid)[0:8],
            "attempt-%s" % str(task_attempt.uuid)[0:8],
        )
        while step_run.parent is not None:
            step_run = step_run.parent
            path = os.path.join(
                "%s-%s" % (
                    str(step_run.uuid)[0:8],
                    step_run.template.name
                ),
                path
            )
        path = "%s-%s" % (step_run.datetime_created.strftime(
            '%Y-%m-%dT%H.%M.%SZ'), path)
        return os.path.join('runs', path, subdir)

    @classmethod
    def _get_path_by_source_type(cls, file_data_object):
        source_type_to_path = {
            'imported': 'imported',
            'result': 'results',
            'log': 'logs'
        }
        return source_type_to_path[file_data_object.source_type]

    @classmethod
    def _add_url_prefix(cls, path):
        if not path.startswith('/'):
            raise RelativePathError(
                'Expected an absolute path but got path="%s"' % path)
        LOOM_STORAGE_TYPE = get_setting('LOOM_STORAGE_TYPE')
        if LOOM_STORAGE_TYPE == 'LOCAL':
            return 'file://' + path
        elif LOOM_STORAGE_TYPE == 'GOOGLE_STORAGE':
            return 'gs://' + get_setting('GOOGLE_STORAGE_BUCKET') + path
        else:
            raise InvalidFileServerTypeError(
                'Couldn\'t recognize value for setting LOOM_STORAGE_TYPE="%s"'\
                % LOOM_STORAGE_TYPE)
