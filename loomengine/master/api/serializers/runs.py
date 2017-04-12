from rest_framework import serializers
from django.core.exceptions import ObjectDoesNotExist

from .base import SuperclassModelSerializer, CreateWithParentModelSerializer
from api.models.runs import Run, StepRun, \
    StepRunInput, StepRunOutput, WorkflowRunInput, \
    WorkflowRunOutput, WorkflowRun, RunTimepoint
from api.serializers.templates import ExpandableTemplateSerializer
from api.serializers.tasks import ExpandableTaskSerializer
from api.serializers.input_output_nodes import InputOutputNodeSerializer
from api.serializers.run_requests import RunRequestSerializer


class RunSerializer(SuperclassModelSerializer):

    class Meta:
        model = Run
        fields = ()

    def _get_subclass_serializer_class(self, type):
        if type=='workflow':
            return WorkflowRunSerializer
        if type=='step':
            return StepRunSerializer
        else:
            # No valid type. Serializer with the base class
            return RunSerializer

    def _get_subclass_field(self, type):
        if type == 'step':
            return 'steprun'
        elif type == 'workflow':
            return 'workflowrun'
        else:
            return None

    def _get_type(self, data=None, instance=None):
        if instance:
            type = instance.type
        else:
            assert data, 'must provide either data or instance'
            type = data.get('type')
        if not type:
            return None
        return type


class ExpandableRunSerializer(RunSerializer):
    # This serializer is used for display only

    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='run-detail',
        lookup_field='uuid'
    )
    datetime_created = serializers.DateTimeField(read_only=True, format='iso-8601')

    class Meta:
        model = Run
	fields = ('uuid',
                  'url',
                  'name',
                  'status',
                  'datetime_created',
        )

    def to_representation(self, instance):
        if self.context.get('expand'):
            return super(ExpandableRunSerializer, self).to_representation(instance)
        else:
            return serializers.HyperlinkedModelSerializer.to_representation(
                self, instance)


class RunTimepointSerializer(CreateWithParentModelSerializer):

    class Meta:
        model = RunTimepoint
        fields = ('message', 'detail', 'timestamp', 'is_error')


class StepRunInputSerializer(InputOutputNodeSerializer):

    mode = serializers.CharField()
    group = serializers.IntegerField()

    class Meta:
        model = StepRunInput
        fields = ('type', 'channel', 'data', 'mode', 'group')


class StepRunOutputSerializer(InputOutputNodeSerializer):

    mode = serializers.CharField()
    source = serializers.JSONField(required=False)

    class Meta:
        model = StepRunOutput
        fields = ('type', 'channel', 'data', 'mode', 'source')


class StepRunSerializer(CreateWithParentModelSerializer):
    
    uuid = serializers.CharField(required=False)
    template = ExpandableTemplateSerializer()
    inputs = StepRunInputSerializer(many=True,
                                    required=False,
                                    allow_null=True)
    outputs = StepRunOutputSerializer(many=True)
    command = serializers.CharField()
    interpreter = serializers.CharField()
    type = serializers.CharField()
    tasks = ExpandableTaskSerializer(many=True)
    # run_request = RunRequestSerializer(required=False)
    datetime_created = serializers.DateTimeField(read_only=True, format='iso-8601')
    timepoints = RunTimepointSerializer(
        many=True, allow_null=True, required=False)
    status = serializers.CharField(read_only=True)
    url = serializers.HyperlinkedIdentityField(
        view_name='run-detail',
        lookup_field='uuid'
    )

    
    class Meta:
        model = StepRun
        fields = ('uuid', 'template', 'inputs', 'outputs',
                  'command', 'interpreter', 'tasks',
                  'postprocessing_status', 'type', 'datetime_created',
                  'status_is_finished', 'status_is_failed', 'status_is_killed',
                  'status_is_running', 'status', 'url', 'timepoints') #'run_request',


class WorkflowRunInputSerializer(InputOutputNodeSerializer):

    class Meta:
        model = WorkflowRunInput
        fields = ('type', 'channel', 'data',)


class WorkflowRunOutputSerializer(InputOutputNodeSerializer):

    class Meta:
        model = WorkflowRunOutput
        fields = ('type', 'channel', 'data',)


class WorkflowRunSerializer(CreateWithParentModelSerializer):

    uuid = serializers.CharField(required=False)
    type = serializers.CharField(required=False)
    template = ExpandableTemplateSerializer()
    steps = ExpandableRunSerializer(many=True)
    inputs = WorkflowRunInputSerializer(many=True,
                                        required=False,
                                        allow_null=True)
    outputs = WorkflowRunOutputSerializer(many=True)
    #run_request = RunRequestSerializer(required=False)
    datetime_created = serializers.DateTimeField(read_only=True, format='iso-8601')
    timepoints = RunTimepointSerializer(
        many=True, allow_null=True, required=False)
    status = serializers.CharField(read_only=True)
    url = serializers.HyperlinkedIdentityField(
        view_name='run-detail',
        lookup_field='uuid'
    )

    class Meta:
        model = WorkflowRun
        fields = ('uuid', 'template', 'steps', 'inputs', 'outputs',
                  'postprocessing_status', 'type', 'datetime_created',
                  'status_is_finished', 'status_is_failed', 'status_is_killed',
                  'status_is_running', 'status', 'url', 'timepoints',) # 'run_request',
