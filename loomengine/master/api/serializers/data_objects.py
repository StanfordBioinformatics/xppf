from django.db import models
from rest_framework import serializers

from .base import SuperclassModelSerializer, CreateWithParentModelSerializer
from api.models.data_objects import StringDataObject, BooleanDataObject, \
    IntegerDataObject, FloatDataObject, FileDataObject, DataObject, \
    FileResource, ArrayDataObject


class UpdateNotAllowedError(Exception):

    pass


class BooleanDataObjectSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-boolean-detail',
        lookup_field='uuid'
    )
    value = serializers.BooleanField(required=True)
    
    class Meta:
        model = BooleanDataObject
        fields = ('uuid', 'url', 'type', 'is_array', 'datetime_created', 'value')


class IntegerDataObjectSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-integer-detail',
        lookup_field='uuid'
    )
    
    class Meta:
        model = IntegerDataObject
        fields = ('uuid', 'url', 'type', 'is_array', 'datetime_created', 'value')


class FloatDataObjectSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-float-detail',
        lookup_field='uuid'
    )
    
    class Meta:
        model = FloatDataObject
        fields = ('uuid', 'url', 'type', 'is_array', 'datetime_created', 'value')


class StringDataObjectSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-string-detail',
        lookup_field='uuid'
    )
    
    class Meta:
        model = StringDataObject
        fields = ('uuid', 'url', 'type', 'is_array', 'datetime_created', 'value')


class FileResourceSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='file-resource-detail',
        lookup_field='uuid'
    )
    upload_status = serializers.ChoiceField(
        choices=FileResource.FILE_RESOURCE_UPLOAD_STATUS_CHOICES,
        required=True)

    class Meta:
        model = FileResource
        fields = ('uuid', 'url', 'datetime_created', 'file_url', 'md5', 'upload_status')


class FileDataObjectSerializer(serializers.ModelSerializer):

    uuid = serializers.CharField(required=False)
    file_resource = FileResourceSerializer(allow_null=True, required=False)
    file_import = serializers.JSONField(required=False, allow_null=True)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-file-detail',
        lookup_field='uuid'
    )
    datetime_created = serializers.CharField(required=False)
    source_type=serializers.ChoiceField(choices=FileDataObject.FILE_SOURCE_TYPE_CHOICES)

    class Meta:
        model = FileDataObject
        fields = ('uuid', 'url', 'file_resource', 'file_import', 'type',
                  'is_array', 'datetime_created', 'filename', 'md5', 'source_type')

    def create(self, validated_data):
        if self.initial_data.get('file_resource'):
            validated_data['file_resource'] = self._create_file_resource(
                self.initial_data.get('file_resource'))
        file_data_object = self.Meta.model.objects.create(**validated_data)
        return file_data_object

    def _create_file_resource(self, resource_data):
        if not resource_data:
            return None
        s = FileResourceSerializer(data=resource_data)
        s.is_valid()
        return s.save()

    def update(self, instance, validated_data):
        instance = instance.filedataobject # downcast
        if self.initial_data.get('file_resource'):
            if instance.file_resource:
                validated_data['file_resource'] = self._update_file_resource(
                    instance.file_resource,
                    self.initial_data.get('file_resource'))
            else:
                validated_data['file_resource'] = self._create_file_resource(
                    self.initial_data.get('file_resource'))
        instance = instance.setattrs_and_save_with_retries(validated_data)
        return instance

    def _update_file_resource(self, instance, resource_data):
        if not resource_data:
            return instance
        s = FileResourceSerializer(instance, data=resource_data)
        s.is_valid()
        return s.save()


class DataObjectSerializer(SuperclassModelSerializer):

    type = serializers.CharField(required=True)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-object-detail',
        lookup_field='uuid'
    )

    class Meta:
        model = DataObject
        exclude = ('_change',)

    subclass_serializers = {
        # array type handled separately to avoid circular dependency
        'string': StringDataObjectSerializer,
        'integer': IntegerDataObjectSerializer,
        'boolean': BooleanDataObjectSerializer,
        'float': FloatDataObjectSerializer,
        'file': FileDataObjectSerializer,
        }

    # These fields go from the base DataObject model to
    # its subclasses, to transform a base class instance
    # into the derived class
    subclass_fields = {
        'array': 'dataobjectarray',
        'string': 'stringdataobject',
        'integer': 'integerdataobject',
        'boolean': 'booleandataobject',
        'float': 'floatdataobject',
        'file': 'filedataobject',
        }

    def _get_subclass_serializer_class(self, type):
        # This has to be defined in a function due to circular dependency
        # ArrayDataObjectSerializer.members uses DataObjectSerializer.
        if type == 'array':
            return ArrayDataObjectSerializer
        elif not type:
            return DataObjectSerializer
        else:
            return self.subclass_serializers[type]

    def _get_subclass_field(self, type):
        try:
            return self.subclass_fields[type]
        except KeyError:
            return None

    def _get_type(self, data=None, instance=None):
        if instance:
            if instance.is_array:
                return 'array'
            else:
                return instance.type
        else:
#            assert data, 'either instance or data is required'
            if data.get('is_array'):
                return 'array'
            else:
                return data.get('type')


class DataObjectUuidSerializer(serializers.HyperlinkedModelSerializer):
    # This serializer is used for display only                                           
    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-object-detail',
        lookup_field='uuid'
    )

    class Meta:
        model = DataObject
        fields = ('uuid',
                  'url',)


class ArrayDataObjectSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    members = DataObjectSerializer(many=True, required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='data-array-detail',
        lookup_field='uuid'
    )

    class Meta:
        model = ArrayDataObject
        exclude = ('_change',)

    def create(self, validated_data):
        member_instances = self._create_member_instances()
        validated_data.pop('members', None)
        instance = self.Meta.model.objects.create(**validated_data)
        if member_instances:
            instance.add_members(member_instances)
        return instance

    def _create_member_instances(self):
        member_instances = []
        for member in self.initial_data.get('members', []):
            s = DataObjectSerializer(data=member)
            s.is_valid()
            member_instances.append(s.save())
        return member_instances

    def validate_is_array(self, value):
        if value == False:
            raise serializers.ValidationError(
                'ArrayDataObjectSerializer cannot be used if is_array=False')
        return value

    def validate(self, data):
        members = self.initial_data.get('members', [])
        for member in members:
            serializer = DataObjectSerializer(
                data=member,
                context=self.context)
            serializer.is_valid(raise_exception=True)
        return data
