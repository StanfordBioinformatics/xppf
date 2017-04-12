from rest_framework import serializers

from api.exceptions import *
from .base import CreateWithParentModelSerializer, SuperclassModelSerializer
from api.models.data_objects import FileDataObject
from api.models.tasks import Task, TaskInput, TaskOutput, \
    TaskAttempt, TaskAttemptOutput, TaskAttemptInput, \
    TaskAttemptLogFile, TaskAttemptTimepoint, TaskTimepoint
from api.serializers.data_objects import DataObjectSerializer


class TaskTimepointSerializer(CreateWithParentModelSerializer):

    class Meta:
        model = TaskTimepoint
        fields = ('message', 'detail', 'timestamp', 'is_error')


class TaskAttemptInputSerializer(CreateWithParentModelSerializer):

    data_object = DataObjectSerializer(allow_null=True, required=False)
    type = serializers.CharField(read_only=True)
    channel = serializers.CharField(read_only=True)

    class Meta:
        model = TaskAttemptInput
        fields = ('type', 'channel', 'data_object',)


class TaskAttemptOutputSerializer(CreateWithParentModelSerializer):

    data_object = DataObjectSerializer(allow_null=True, required=False)
    type = serializers.CharField(read_only=True)
    channel = serializers.CharField(read_only=True)
    source = serializers.JSONField(required=False)
    # parser = TaskDefinitionOutputParserSerializer(read_only=True)

    class Meta:
        model = TaskAttemptOutput
        fields = ('id', 'type', 'channel', 'source', 'data_object')

    def update(self, instance, validated_data):
        data_object_data = self.initial_data.get('data_object', None)
        validated_data.pop('data_object', None)
        
        if data_object_data:
            if not instance.data_object:
                if data_object_data.get('type') == 'file':
                    # We can't use the serializer because it fails to initialize
                    # the file data object when it isn't attached to a
                    # task_attempt_output
                    data_object = FileDataObject.objects.create(
                        **data_object_data)
                    instance = instance.setattrs_and_save_with_retries(
                        {'data_object': data_object})
                else:
                    s = DataObjectSerializer(data=data_object_data)
                    s.is_valid(raise_exception=True)
                    validated_data['data_object'] = s.save()
            else:
                s = DataObjectSerializer(instance.data_object, data=data_object_data)
                s.is_valid(raise_exception=True)
                validated_data['data_object'] = s.save()
        return super(self.__class__, self).update(
            instance,
            validated_data)


class TaskAttemptLogFileSerializer(CreateWithParentModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='task-attempt-log-file-detail',
        lookup_field='uuid')
    file = DataObjectSerializer(allow_null=True, required=False)

    class Meta:
        model = TaskAttemptLogFile
        fields = ('uuid', 'url', 'log_name', 'file', 'datetime_created')


class TaskAttemptTimepointSerializer(CreateWithParentModelSerializer):

    class Meta:
        model = TaskAttemptTimepoint
        fields = ('message', 'detail', 'timestamp', 'is_error')


class TaskAttemptSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='task-attempt-detail',
        lookup_field='uuid')
    log_files = TaskAttemptLogFileSerializer(
        many=True, allow_null=True, required=False)
    inputs = TaskAttemptInputSerializer(many=True, allow_null=True, required=False)
    outputs = TaskAttemptOutputSerializer(
        many=True, allow_null=True, required=False)
    timepoints = TaskAttemptTimepointSerializer(
        many=True, allow_null=True, required=False)
    resources = serializers.JSONField(required=False)
    environment = serializers.JSONField(required=False)
    
    class Meta:
        model = TaskAttempt
        fields = ('uuid', 'url', 'datetime_created', 'datetime_finished', 
                  'last_heartbeat', 'status_is_finished', 'status_is_failed',
                  'status_is_killed', 'status_is_running', 'status_is_cleaned_up',
                  'log_files', 'inputs', 'outputs', 'interpreter', 
                  'rendered_command', 'environment', 'resources', 'timepoints')


    def update(self, instance, validated_data):
        instance = self.Meta.model.objects.get(uuid=instance.uuid)
        # Only updates to status message fields,
        # status_is_finished, status_is_failed, and status_is_running
        status_is_finished = validated_data.pop('status_is_finished', None)
        status_is_failed = validated_data.pop('status_is_failed', None)
        status_is_running = validated_data.pop('status_is_running', None)

        attributes = {}
        if status_is_finished is not None:
            attributes['status_is_finished'] = status_is_finished
        if status_is_failed is not None:
            attributes['status_is_failed'] = status_is_failed
        if status_is_running is not None:
            attributes['status_is_running'] = status_is_running
        instance = instance.setattrs_and_save_with_retries(attributes)
        return instance


class ExpandableTaskAttemptSerializer(TaskAttemptSerializer):
    # This serializer is used for display only
    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='task-attempt-detail',
        lookup_field='uuid')

    class Meta:
        model = TaskAttempt
        fields = ('uuid',
                  'url',)

    def to_representation(self, instance):
        if self.context.get('expand'):
            self.Meta = TaskAttemptSerializer.Meta
            return super(ExpandableTaskAttemptSerializer, self).to_representation(
                instance)
        else:
            return serializers.HyperlinkedModelSerializer.to_representation(
                self, instance)


class TaskInputSerializer(CreateWithParentModelSerializer):

    data_object = DataObjectSerializer(read_only=True)
    type = serializers.CharField(read_only=True)
    channel = serializers.CharField(read_only=True)

    class Meta:
        model = TaskInput
        fields = ('data_object', 'type', 'channel',)


class TaskOutputSerializer(CreateWithParentModelSerializer):

    data_object = DataObjectSerializer(read_only=True)
    type = serializers.CharField(read_only=True)
    channel = serializers.CharField(read_only=True)
    source = serializers.JSONField(required=False)

    class Meta:
        model = TaskOutput
        fields = ('data_object', 'source', 'type', 'channel')


class TaskSerializer(serializers.HyperlinkedModelSerializer):

    uuid = serializers.CharField(required=False, read_only=True)
    url = serializers.HyperlinkedIdentityField(
        view_name='task-detail',
        lookup_field='uuid')
    resources = serializers.JSONField(required=False)
    environment = serializers.JSONField(required=False)
    inputs = TaskInputSerializer(many=True, read_only=True)
    outputs = TaskOutputSerializer(many=True, read_only=True)
    task_attempts = ExpandableTaskAttemptSerializer(many=True, read_only=True)
    selected_task_attempt = ExpandableTaskAttemptSerializer(read_only=True)
    command = serializers.CharField(read_only=True)
    rendered_command = serializers.CharField(read_only=True)
    interpreter = serializers.CharField(read_only=True)
    datetime_finished = serializers.CharField(read_only=True)
    datetime_created = serializers.CharField(read_only=True)
    status_message = serializers.CharField(read_only=True)
    status_detail = serializers.CharField(read_only=True)
    status_is_finished = serializers.BooleanField(read_only=True)
    status_is_failed = serializers.BooleanField(read_only=True)
    status_is_killed = serializers.BooleanField(read_only=True)
    status_is_running = serializers.BooleanField(read_only=True)
    attempt_number = serializers.IntegerField(read_only=True)
    timepoints = TaskTimepointSerializer(
        many=True, allow_null=True, required=False)
    index = serializers.JSONField(required=True)

    class Meta:
        model = Task
        fields = (
            'uuid',
            'url',
            'resources',
            'environment',
            'inputs', 
            'outputs',
            'task_attempts',
            'selected_task_attempt', 
            'command',
            'rendered_command',
            'interpreter',
            'datetime_finished',
            'datetime_created',
            'status_message',
            'status_detail',
            'status_is_finished',
            'status_is_failed',
            'status_is_killed',
            'status_is_running',
            'attempt_number',
            'timepoints',
            'index',
        )


class ExpandableTaskSerializer(TaskSerializer):
    # This serializer is used for display only
    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='task-detail',
        lookup_field='uuid')
    datetime_created = serializers.CharField(read_only=True)

    class Meta:
        model = Task
        fields = ('uuid',
                  'url',
                  'status_message',
                  'datetime_created',)

    def to_representation(self, instance):
        if self.context.get('expand'):
            self.Meta = TaskSerializer.Meta
            return super(ExpandableTaskSerializer, self).to_representation(
                instance)
        else:
            return serializers.HyperlinkedModelSerializer.to_representation(
                self, instance)
