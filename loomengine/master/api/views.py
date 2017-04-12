from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
import logging
import os
import rest_framework
from rest_framework import viewsets
from rest_framework.decorators import detail_route

from api import get_setting
from api import models
from api import serializers
from api import async
from loomengine.utils import version


logger = logging.getLogger(__name__)

DATA_CLASSES = {'file': models.FileDataObject,
                'string': models.StringDataObject,
                'boolean': models.BooleanDataObject,
                'float': models.FloatDataObject,
                'integer': models.IntegerDataObject}


class ExpandableViewSet(viewsets.ModelViewSet):

    def get_serializer_context(self):
        return {'request': self.request,
                'expand': 'expand' in self.request.query_params}


class DataObjectViewSet(viewsets.ModelViewSet):
    """
    Data Objects of any type, including arrays.
    For documentation of each data type, see the respective /api/data-*/ endpoints.
    """

    lookup_field = 'uuid'
    serializer_class = serializers.DataObjectSerializer

    def get_queryset(self):
        queryset = models.DataObject.objects.all()
        queryset = queryset.select_related('stringdataobject')\
                           .select_related('filedataobject')\
                           .select_related('filedataobject__file_resource')\
                           .select_related('booleandataobject')\
                           .select_related('integerdataobject')\
                           .select_related('floatdataobject')\
                           .select_related('arraydataobject')\
                           .prefetch_related(
                               'arraydataobject__prefetch_members__stringdataobject')\
                           .prefetch_related(
                               'arraydataobject__prefetch_members__booleandataobject')\
                           .prefetch_related(
                               'arraydataobject__prefetch_members__integerdataobject')\
                           .prefetch_related(
                               'arraydataobject__prefetch_members__floatdataobject')\
                           .prefetch_related(
                               'arraydataobject__prefetch_members__filedataobject__'\
                               'file_resource')
        return queryset.order_by('-datetime_created')


class FileDataObjectViewSet(viewsets.ModelViewSet):
    """
    Data Objects of type 'file'. parameters: 
    q = {file query string e.g. filename@uuid};
    source_type = [ 'log' | 'imported' | 'result' ].
    All Data Object types including 'file' may be managed at /api/data-objects/,
    but file-specific parameters are processed only at /api/data-files/
    """
    lookup_field = 'uuid'
    serializer_class = serializers.FileDataObjectSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        source_type = self.request.query_params.get('source_type', '')
        if query_string:
            queryset = models.FileDataObject.filter_by_name_or_id_or_hash(query_string)
        else:
            queryset = models.FileDataObject.objects.all()
        if source_type and source_type != 'all':
            queryset = queryset.filter(source_type=source_type)
        queryset = queryset.select_related('file_resource')
        return queryset.order_by('-datetime_created')

    @detail_route(methods=['post'], url_path='initialize-file-resource',
                  # Use base serializer since request has no data. Used by API doc.
                  serializer_class=rest_framework.serializers.Serializer)

    def initialize_file_resource(self, request, uuid=None):
        try:
            file_data_object = models.FileDataObject.objects.get(uuid=uuid)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        if file_data_object.file_resource:
            s = serializers.FileResourceSerializer(
                file_data_object.file_resource, context={'request': request})
            return JsonResponse(s.data, status=200)
        file_data_object.initialize_file_resource()
        s = serializers.FileResourceSerializer(
            file_data_object.file_resource, context={'request': request})
        return JsonResponse(s.data, status=201)


class StringDataObjectViewSet(viewsets.ModelViewSet):
    """
    Data Objects of type 'string'.
    This endpoint is primarily for documentation. 
    Use /api/data-objects/ instead, which accepts all data object types.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.StringDataObjectSerializer

    def get_queryset(self):
        queryset = models.StringDataObject.objects.all()
        return queryset.order_by('-datetime_created')


class BooleanDataObjectViewSet(viewsets.ModelViewSet):
    """
    Data Objects of type 'boolean'. 
    This endpoint is primarily for documentation. 
    Use /api/data-objects/ instead, which accepts all data object types.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.BooleanDataObjectSerializer

    def get_queryset(self):
        queryset = models.BooleanDataObject.objects.all()
        return queryset.order_by('-datetime_created')


class IntegerDataObjectViewSet(viewsets.ModelViewSet):
    """
    Data Objects of type 'integer'.
    This endpoint is primarily for documentation. 
    Use /api/data-objects/ instead, which accepts all data object types.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.IntegerDataObjectSerializer

    def get_queryset(self):
        queryset = models.IntegerDataObject.objects.all()
        return queryset.order_by('-datetime_created')


class FloatDataObjectViewSet(viewsets.ModelViewSet):
    """
    Data Objects of type 'float'.
    This endpoint is primarily for documentation. 
    Use /api/data-objects/ instead, which accepts all data object types.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.FloatDataObjectSerializer

    def get_queryset(self):
        queryset = models.FloatDataObject.objects.all()
        return queryset.order_by('-datetime_created')


class ArrayDataObjectViewSet(viewsets.ModelViewSet):
    """
    Array Data Objects of any type. 
    'members' contains a JSON formatted list of member data objects.
    Each DataObject representation may be a complete object, the value from which
    a new object will be created, or the identifier from which an existing 
    FileDataObject can be looked up.
    This endpoint is primarily for documentation. 
    Use /api/data-objects/ instead, which accepts both array and non-array DataObjects.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.ArrayDataObjectSerializer

    def get_queryset(self):
        queryset = models.DataObject.objects.all()
        queryset = queryset.filter(is_array=True)
        return queryset.order_by('-datetime_created')


class DataTreeViewSet(ExpandableViewSet):
    """
    A tree whose nodes represent DataObjects, all of the same type.
    The 'contents' field is a JSON that may be a DataObject, a list of
    DataObjects, or nested lists of DataObjects representing a tree structure.
    Each DataObject representation may be a complete object, the value from which
    a new object will be created, or the identifier from which an existing 
    FileDataObject can be looked up.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.DataTreeNodeSerializer

    def get_queryset(self):
        queryset = models.DataTreeNode.objects.filter(parent__isnull=True)
        queryset = queryset\
                   .select_related('data_object')\
                   .prefetch_related('descendants__data_object')\
                   .prefetch_related('descendants__data_object__stringdataobject')\
                   .prefetch_related('descendants__data_object__filedataobject')\
                   .prefetch_related(
                       'descendants__data_object__filedataobject__file_resource')\
                   .prefetch_related('descendants__data_object__booleandataobject')\
                   .prefetch_related('descendants__data_object__integerdataobject')\
                   .prefetch_related('descendants__data_object__floatdataobject')
        return queryset


class FileResourceViewSet(viewsets.ModelViewSet):
    """
    FileResource represents the location where a file is stored.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.FileResourceSerializer

    def get_queryset(self):
        return models.FileResource.objects.all().order_by('-datetime_created')

        
class TaskViewSet(ExpandableViewSet):
    """
    A Task represents a specific set of (runtime environment, command, inputs).
    A step may contain many tasks if its inputs are parallel.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.TaskSerializer

    def get_queryset(self):
        queryset = models.Task.objects.all()
        queryset = queryset\
                   .select_related('selected_task_attempt')\
                   .prefetch_related('task_attempts')\
                   .prefetch_related('inputs')\
                   .prefetch_related('inputs__data_object')\
                   .prefetch_related('inputs__data_object__stringdataobject')\
                   .prefetch_related('inputs__data_object__filedataobject')\
                   .prefetch_related('inputs__data_object__filedataobject__'\
                                     'file_resource')\
                   .prefetch_related('inputs__data_object__booleandataobject')\
                   .prefetch_related('inputs__data_object__integerdataobject')\
                   .prefetch_related('inputs__data_object__floatdataobject')\
                   .prefetch_related('inputs__data_object__arraydataobject')\
                   .prefetch_related(
                       'inputs__data_object__arraydataobject__'\
                       'prefetch_members__stringdataobject')\
                   .prefetch_related(
                       'inputs__data_object__arraydataobject__'\
                       'prefetch_members__booleandataobject')\
                   .prefetch_related(
                       'inputs__data_object__arraydataobject__'\
                       'prefetch_members__integerdataobject')\
                   .prefetch_related(
                       'inputs__data_object__arraydataobject__'\
                       'prefetch_members__floatdataobject')\
                   .prefetch_related(
                       'inputs__data_object__arraydataobject__'\
                       'prefetch_members__filedataobject__'\
                       'file_resource')\
                   .prefetch_related('outputs')\
                   .prefetch_related('outputs__data_object')\
                   .prefetch_related('outputs__data_object__stringdataobject')\
                   .prefetch_related('outputs__data_object__filedataobject')\
                   .prefetch_related('outputs__data_object__filedataobject__'\
                                     'file_resource')\
                   .prefetch_related('outputs__data_object__booleandataobject')\
                   .prefetch_related('outputs__data_object__integerdataobject')\
                   .prefetch_related('outputs__data_object__floatdataobject')\
                   .prefetch_related('outputs__data_object__arraydataobject')\
                   .prefetch_related(
                       'outputs__data_object__arraydataobject__'\
                       'prefetch_members__stringdataobject')\
                   .prefetch_related(
                       'outputs__data_object__arraydataobject__'\
                       'prefetch_members__booleandataobject')\
                   .prefetch_related(
                       'outputs__data_object__arraydataobject__'\
                       'prefetch_members__integerdataobject')\
                   .prefetch_related(
                       'outputs__data_object__arraydataobject__'\
                       'prefetch_members__floatdataobject')\
                   .prefetch_related(
                       'outputs__data_object__arraydataobject__'\
                       'prefetch_members__filedataobject__'\
                       'file_resource')\
                   .prefetch_related('timepoints')
        return queryset.order_by('-datetime_created')


class TaskAttemptViewSet(ExpandableViewSet):
    """
    A TaskAttempt represents a single attempt at executing a Task.
    A Task may have multiple TaskAttempts if retries are executed.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.TaskAttemptSerializer

    def get_queryset(self):
        queryset = models.TaskAttempt.objects.all()
        queryset = queryset.select_related('task')\
                           .prefetch_related('inputs')\
                           .prefetch_related('inputs__data_object')\
                           .prefetch_related('inputs__data_object__stringdataobject')\
                           .prefetch_related('inputs__data_object__filedataobject')\
                           .prefetch_related('inputs__data_object__filedataobject__'\
                                             'file_resource')\
                           .prefetch_related('inputs__data_object__booleandataobject')\
                           .prefetch_related('inputs__data_object__integerdataobject')\
                           .prefetch_related('inputs__data_object__floatdataobject')\
                           .prefetch_related('inputs__data_object__arraydataobject')\
                           .prefetch_related(
                               'inputs__data_object__arraydataobject__'\
                               'prefetch_members__stringdataobject')\
                           .prefetch_related(
                               'inputs__data_object__arraydataobject__'\
                               'prefetch_members__booleandataobject')\
                           .prefetch_related(
                               'inputs__data_object__arraydataobject__'\
                               'prefetch_members__integerdataobject')\
                           .prefetch_related(
                               'inputs__data_object__arraydataobject__'\
                               'prefetch_members__floatdataobject')\
                           .prefetch_related(
                               'inputs__data_object__arraydataobject__'\
                               'prefetch_members__filedataobject__'\
                               'file_resource')\
                           .prefetch_related('outputs')\
                           .prefetch_related('outputs__'\
                                             'data_object')\
                           .prefetch_related('outputs__'\
                                             'data_object__stringdataobject')\
                           .prefetch_related('outputs__'\
                                             'data_object__filedataobject')\
                           .prefetch_related('outputs__'\
                                             'data_object__filedataobject__'\
                                             'file_resource')\
                           .prefetch_related('outputs__'\
                                             'data_object__booleandataobject')\
                           .prefetch_related('outputs__'\
                                             'data_object__integerdataobject')\
                           .prefetch_related('outputs__'\
                                             'data_object__floatdataobject')\
                           .prefetch_related('outputs__'\
                                             'data_object__arraydataobject')\
                           .prefetch_related(
                               'outputs__data_object__'\
                               'arraydataobject__prefetch_members__stringdataobject')\
                           .prefetch_related(
                               'outputs__data_object__'\
                               'arraydataobject__prefetch_members__booleandataobject')\
                           .prefetch_related(
                               'outputs__data_object__'\
                               'arraydataobject__prefetch_members__integerdataobject')\
                           .prefetch_related(
                               'outputs__data_object__'\
                               'arraydataobject__prefetch_members__floatdataobject')\
                           .prefetch_related(
                               'outputs__data_object__'\
                               'arraydataobject__prefetch_members__filedataobject__'\
                               'file_resource')\
                           .prefetch_related('log_files__file')\
                           .prefetch_related('log_files__file__'\
                                             'filedataobject__file_resource')\
                           .prefetch_related('timepoints')
        return queryset.order_by('-datetime_created')

    @detail_route(methods=['post'], url_path='create-log-file',
                  serializer_class=serializers.TaskAttemptLogFileSerializer)
    def create_log_file(self, request, uuid=None):
        data_json = request.body
        data = json.loads(data_json)
        try:
            task_attempt = models.TaskAttempt.objects.get(uuid=uuid)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        s = serializers.TaskAttemptLogFileSerializer(
            data=data,
            context={
                'parent_field': 'task_attempt',
                'parent_instance': task_attempt,
                'request': request,
            })
        s.is_valid(raise_exception=True)
        model = s.save()
        return JsonResponse(s.data, status=201)

    @detail_route(methods=['post'], url_path='fail',
                  # Use base serializer since request has no data. Used by API doc.
                  serializer_class=rest_framework.serializers.Serializer)
    def fail(self, request, uuid=None):
        try:
            task_attempt = models.TaskAttempt.objects.get(uuid=uuid)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        task_attempt.fail()
        return JsonResponse({}, status=201)

    @detail_route(methods=['post'], url_path='finish',
                  serializer_class=rest_framework.serializers.Serializer)
    def finish(self, request, uuid=None):
        try:
            task_attempt = models.TaskAttempt.objects.get(uuid=uuid)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        async.finish_task_attempt(task_attempt.uuid)
        return JsonResponse({}, status=201)
    
    @detail_route(methods=['post'], url_path='create-timepoint',
                  serializer_class=serializers.TaskAttemptTimepointSerializer)
    def create_timepoint(self, request, uuid=None):
        data_json = request.body
        data = json.loads(data_json)
        try:
            task_attempt = models.TaskAttempt.objects.get(uuid=uuid)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        s = serializers.TaskAttemptTimepointSerializer(
            data=data,
            context={
                'parent_field': 'task_attempt',
                'parent_instance': task_attempt,
                'request': request
            })
        s.is_valid(raise_exception=True)
        model = s.save()

        return JsonResponse(s.data, status=201)

    @detail_route(methods=['get'], url_path='worker-settings')
    def get_worker_settings(self, request, uuid=None):
        try:
            task_attempt = models.TaskAttempt.objects.get(uuid=uuid)
            return JsonResponse({
                'WORKING_DIR': task_attempt.get_working_dir(),
                'STDOUT_LOG_FILE': task_attempt.get_stdout_log_file(),
                'STDERR_LOG_FILE': task_attempt.get_stderr_log_file(),
                'HEARTBEAT_INTERVAL_SECONDS':
                get_setting('TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS'),
            }, status=200)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        except Exception as e:
            return JsonResponse({"message": e.message}, status=500)


class TemplateViewSet(ExpandableViewSet):
    """
    A Template is a pattern for analysis to be performed, but without necessarily
    having inputs assigned. May be type 'step' or 'workflow'. 
    For documentation of each Template type, 
    see the respective /api/template-*/ endpoints.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.TemplateSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        imported = 'imported' in self.request.query_params
        if query_string:
            queryset = models.Template.filter_by_name_or_id(query_string)
        else:
            queryset = models.Template.objects.all()
        if imported:
            queryset = queryset.filter(template_import__isnull=False)
        queryset = queryset\
                   .prefetch_related('workflow__steps')\
                   .prefetch_related(
                       'workflow__fixed_inputs__data_root')\
                   .prefetch_related(
                       'step__fixed_inputs__data_root')
        return queryset.order_by('-datetime_created')


class StepViewSet(ExpandableViewSet):
    """
    Templates of type 'step', which contain a command
    and runtime environment.
    This endpoint is primarily for documentation. 
    Use /api/templates/ instead, which accepts all Template types.
    """
    lookup_field = 'uuid'
    serializer_class = serializers.StepSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        imported = 'imported' in self.request.query_params
        if query_string:
            queryset = models.Step.filter_by_name_or_id(query_string)
        else:
            queryset = models.Step.objects.all()
        if imported:
            queryset = queryset.filter(template_import__isnull=False)
        queryset = queryset\
                   .prefetch_related(
                       'fixed_inputs__data_root')
        return queryset.order_by('-datetime_created')


class WorkflowViewSet(ExpandableViewSet):
    """
    Templates of type 'workflow', which act as containers
    for other Templates. 
    'steps' is a JSON formatted list of child templates, where
    each may be type 'step' or 'workflow'.
    This endpoint is primarily for documentation. 
    Use /api/templates/ instead, which accepts all Template types.
    """

    lookup_field = 'uuid'
    serializer_class = serializers.WorkflowSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        imported = 'imported' in self.request.query_params
        if query_string:
            queryset = models.Workflow.filter_by_name_or_id(query_string)
        else:
            queryset = models.Workflow.objects.all()
        if imported:
            queryset = queryset.filter(template_import__isnull=False)
        queryset = queryset\
                   .prefetch_related('steps')\
                   .prefetch_related(
                       'fixed_inputs__data_root')
        return queryset.order_by('-datetime_created')


class RunViewSet(ExpandableViewSet):
    """
    A Run represents the execution of a Template on a specific set of inputs.
    May be type 'step' or 'workflow'. 
    For documentation of each Run type, 
    see the respective /api/run-*/ endpoints.
    """

    lookup_field = 'uuid'
    serializer_class = serializers.RunSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        parent_only = 'parent_only' in self.request.query_params
        if query_string:
            queryset = models.Run.filter_by_name_or_id(query_string)
        else:
            queryset = models.Run.objects.all()
        if parent_only:
            queryset = queryset.filter(parent__isnull=True)
        queryset = queryset.select_related('workflowrun__template')\
                           .prefetch_related('workflowrun__inputs')\
                           .prefetch_related(
                               'workflowrun__inputs__data_root')\
                           .prefetch_related('workflowrun__outputs')\
                           .prefetch_related(
                               'workflowrun__outputs__data_root')\
                           .prefetch_related('workflowrun__steps')\
                           .select_related(
                               'workflowrun__run_request')\
                           .prefetch_related('workflowrun__timepoints')\
                           .select_related('steprun__template')\
                           .prefetch_related('steprun__inputs')\
                           .prefetch_related('steprun__inputs__data_root')\
                           .prefetch_related('steprun__outputs')\
                           .prefetch_related('steprun__outputs__data_root')\
                           .prefetch_related('steprun__tasks')\
                           .select_related(
                               'steprun__run_request')\
                           .prefetch_related('steprun__timepoints')
        return queryset.order_by('-datetime_created')


class StepRunViewSet(ExpandableViewSet):
    """
    Runs of type 'step', which contain a command
    and runtime environment.
    This endpoint is primarily for documentation. 
    Use /api/runs/ instead, which accepts all Run types.
    """

    lookup_field = 'uuid'
    serializer_class = serializers.StepRunSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        parent_only = 'parent_only' in self.request.query_params
        if query_string:
            queryset = models.StepRun.filter_by_name_or_id(query_string)
        else:
            queryset = models.StepRun.objects.all()
        if parent_only:
            queryset = queryset.filter(parent__isnull=True)
        queryset = queryset.select_related('template')\
                           .prefetch_related('inputs')\
                           .prefetch_related('inputs__data_root')\
                           .prefetch_related('outputs')\
                           .prefetch_related('outputs__data_root')\
                           .prefetch_related('tasks')\
                           .select_related(
                               'run_request')\
                           .prefetch_related('timepoints')
        return queryset.order_by('-datetime_created')


class WorkflowRunViewSet(ExpandableViewSet):
    """
    Runs of type 'workflow', which act as containers
    for other Runs. 
    'steps' is a JSON formatted list of child runs, where
    each may be type 'step' or 'workflow'.
    This endpoint is primarily for documentation. 
    Use /api/runs/ instead, which accepts all Run types.
    """

    lookup_field = 'uuid'
    serializer_class = serializers.WorkflowRunSerializer

    def get_queryset(self):
        query_string = self.request.query_params.get('q', '')
        parent_only = 'parent_only' in self.request.query_params
        if query_string:
            queryset = models.WorkflowRun.filter_by_name_or_id(query_string)
        else:
            queryset = models.WorkflowRun.objects.all()
        if parent_only:
            queryset = queryset.filter(parent__isnull=True)
        queryset = queryset.select_related('template')\
                           .prefetch_related('inputs')\
                           .prefetch_related(
                               'inputs__data_root')\
                           .prefetch_related('outputs')\
                           .prefetch_related(
                               'outputs__data_root')\
                           .prefetch_related('steps')\
                           .select_related(
                               'run_request')\
                           .prefetch_related('timepoints')
        return queryset.order_by('-datetime_created')

    
class RunRequestViewSet(ExpandableViewSet):
    """
    A RunRequest represents a user request to execute a given Template
    with a particular set of Inputs. 'template' may be a Template object
    or an identifier (e.g. template_name@uuid).
    """
    lookup_field = 'uuid'
    serializer_class = serializers.RunRequestSerializer

    def get_queryset(self):
        queryset = models.RunRequest.objects.all()
        queryset = queryset.select_related('run')\
                           .select_related('template')\
                           .prefetch_related('inputs__data_root')
        return queryset.order_by('-datetime_created')

class TaskAttemptLogFileViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.TaskAttemptLogFileSerializer
    lookup_field = 'uuid'

    def get_queryset(self):
        queryset = models.TaskAttemptLogFile.objects.all()
        queryset = queryset.select_related('file')\
                   .select_related('file__filedataobject__file_resource')
        return queryset.order_by('-datetime_created')

    @detail_route(methods=['post'], url_path='initialize-file',
                  # Use base serializer since request has no data. Used by API doc.
                  serializer_class=rest_framework.serializers.Serializer)
    def initialize_file(self, request, uuid=None):
        try:
            task_attempt_log_file = models.TaskAttemptLogFile.objects.get(uuid=uuid)
        except ObjectDoesNotExist:
            return JsonResponse({"message": "Not Found"}, status=404)
        if task_attempt_log_file.file:
            s = serializers.DataObjectSerializer(
                task_attempt_log_file.file, context={'request': request})
            return JsonResponse(s.data, status=200)
        task_attempt_log_file.initialize_file()
        s = serializers.DataObjectSerializer(
            task_attempt_log_file.file, context={'request': request})
        return JsonResponse(s.data, status=201)


class TaskAttemptOutputViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.TaskAttemptOutputSerializer

    def get_queryset(self):
        queryset = models.TaskAttemptOutput.objects.all()
        queryset = queryset.select_related('data_object__stringdataobject')\
                           .select_related('data_object__filedataobject')\
                           .select_related(
                               'data_object__filedataobject__file_resource')\
                           .select_related('data_object__booleandataobject')\
                           .select_related('data_object__integerdataobject')\
                           .select_related('data_object__floatdataobject')\
                           .select_related('data_object__arraydataobject')\
                           .prefetch_related(
                               'data_object__arraydataobject__'\
                               'prefetch_members__stringdataobject')\
                           .prefetch_related(
                               'data_object__arraydataobject__'\
                               'prefetch_members__booleandataobject')\
                           .prefetch_related(
                               'data_object__arraydataobject__'\
                               'prefetch_members__integerdataobject')\
                           .prefetch_related(
                               'data_object__arraydataobject__'\
                               'prefetch_members__floatdataobject')\
                           .prefetch_related(
                               'data_object__arraydataobject__'\
                               'prefetch_members__filedataobject__'\
                               'file_resource')
        return queryset.order_by('-datetime_created')


@require_http_methods(["GET"])
def status(request):
    return JsonResponse({"message": "server is up"}, status=200)

@require_http_methods(["GET"])
def filemanager_settings(request):
    return JsonResponse({
        'GCE_PROJECT': get_setting('GCE_PROJECT'),
    })

@require_http_methods(["GET"])
def info(request):
    data = {
        'version': version.version()
    }
    return JsonResponse(data, status=200)

@require_http_methods(["GET"])
def raise_server_error(request):
    logger.error('Server error intentionally logged for debugging.')
    raise Exception('Server error intentionally raised for debugging')
