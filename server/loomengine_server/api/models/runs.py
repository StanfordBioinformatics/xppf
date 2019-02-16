from django.core import mail
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned, \
    ValidationError
from django.db import models
from django.template.loader import render_to_string
from django.utils import timezone
import logging
import jsonfield
import requests

from .base import BaseModel
from . import flatten_nodes, copy_prefetch
from api import get_setting
from api import async
from api.exceptions import *
from api.models import uuidstr
from api.models import validators
from api.models.data_objects import DataObject
from api.models.data_channels import DataChannel
from api.models.data_nodes import DataNode
from api.models.input_calculator import InputCalculator
from api.models.tasks import Task, TaskInput, TaskOutput, TaskAlreadyExistsException
from api.models.task_attempts import TaskAttempt
from api.models.templates import Template
from api.exceptions import ConcurrentModificationError


"""
A Run represents the execution of a Template with a given set of inputs.
Like Templates, Runs may have an arbitrary depth of nested children (steps),
but only the leaf nodes represent analysis to be performed. Leaf and branch 
nodes are both of class Run.

Depending on the inputs, a Run can produce a single Task or many parallel
Tasks.
"""

logger = logging.getLogger(__name__)


class RunAlreadyClaimedForPostprocessingException(Exception):
    pass


class Run(BaseModel):
    """AbstractWorkflowRun represents the process of executing a Workflow on
    a particular set of inputs. The workflow may be either a Step or a
    Workflow composed of one or more Steps.
    """

    NAME_FIELD = 'name'
    ID_FIELD = 'uuid'
    TAG_FIELD = 'tags__tag'

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    name = models.CharField(max_length=255)
    is_leaf = models.BooleanField()
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    timeout_hours = models.FloatField(null=True, blank=True)
    environment = jsonfield.JSONField(
        blank=True,
        validators=[validators.validate_environment])
    resources = jsonfield.JSONField(
        blank=True,
        validators=[validators.validate_resources])
    notification_addresses = jsonfield.JSONField(
        blank=True, validators=[validators.validate_notification_addresses])
    notification_context = jsonfield.JSONField(
        null=True, blank=True, default=None,
        validators=[validators.validate_notification_context])
    parent = models.ForeignKey('self', null=True, blank=True,
                            related_name='steps', db_index=True,
                            on_delete=models.SET_NULL)
    template = models.ForeignKey('Template',
                                 related_name='runs',
                                 on_delete=models.PROTECT,
                                 null=True, # For testing only
                                 blank=True)
    postprocessing_status = models.CharField(
        max_length=255,
        default='not_started',
        choices=(('not_started', 'Not Started'),
                 ('in_progress', 'In Progress'),
                 ('complete', 'Complete'),
                 ('failed', 'Failed'))
    )

    status_is_finished = models.BooleanField(default=False)
    status_is_failed = models.BooleanField(default=False)
    status_is_killed = models.BooleanField(default=False)
    status_is_running = models.BooleanField(default=False)
    status_is_waiting = models.BooleanField(default=True)

    # For leaf nodes only
    command = models.TextField(blank=True)
    interpreter = models.CharField(max_length=1024, blank=True)

    force_rerun = models.BooleanField(default=False)
    imported = models.BooleanField(default=False)

    @property
    def status(self):
        if self.status_is_failed:
            return 'Failed'
        elif self.status_is_finished:
            return 'Finished'
        elif self.status_is_killed:
            return 'Killed'
        elif self.status_is_running:
            return 'Running'
        elif self.status_is_waiting:
            return 'Waiting'
        else:
            return 'Unknown'

    def get_input(self, channel):
        inputs = [i for i in self.inputs.filter(channel=channel)]
        assert len(inputs) < 2, 'too many inputs for channel %s' % channel
        assert len(inputs) == 1, 'missing input for channel %s' % channel
        return inputs[0]

    def get_output(self, channel):
        outputs = [o for o in self.outputs.filter(channel=channel)]
        assert len(outputs) == 1, 'missing output for channel %s' % channel
        return outputs[0]

    def get_user_input(self, channel):
        user_inputs = [i for i in self.user_inputs.filter(channel=channel)]
        assert len(user_inputs) < 2, 'too many user_inputs for channel %s' % channel
        if len(user_inputs) == 0:
            return None
        return inputs[0]
        
    def finish(self):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries(
            {'datetime_finished': timezone.now(),
             'status_is_running': False,
             'status_is_waiting': False,
             'status_is_finished': True})
        if self.parent:
            if self.parent._are_children_finished():
                self.parent.finish()
        else:
            # Send notifications only if topmost run
            async.execute(async.send_notifications, self.uuid)

    def _are_children_finished(self):
        return all([step.status_is_finished for step in self.steps.all()])

    def are_tasks_finished(self):
        task_tree = TaskNode.create_from_task_list(self.tasks.all())
        return task_tree.is_complete()

    def has_terminal_status(self):
        return self.status_is_finished \
            or self.status_is_failed \
            or self.status_is_killed

    def fail(self, detail=''):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries({
            'status_is_failed': True,
            'status_is_running': False,
            'status_is_waiting': False})
        self.add_event("Run failed", detail=detail, is_error=True)
        if self.parent:
            self.parent.fail(detail='Failure in step %s@%s' % (
                self.name, self.uuid))
        else:
            # Send kill signal to children if topmost run
            self._kill_children(detail='Automatically killed due to failure')
            # Send notifications if topmost run
            async.execute(async.send_notifications, self.uuid)

    def kill(self, detail=''):
        if self.has_terminal_status():
            return
        self.add_event('Run was killed', detail=detail, is_error=True)
        self.setattrs_and_save_with_retries(
            {'status_is_killed': True,
             'status_is_running': False,
             'status_is_waiting': False})
        self._kill_children(detail=detail)
        if self.parent:
            self.parent.kill(detail=detail)

    def _kill_children(self, detail=''):
        for step in self.steps.all():
            step.kill(detail=detail)
        for task in self.tasks.all():
            task.kill(detail=detail)

    def set_running_status(self):
        if self.status_is_running and not self.status_is_waiting:
            return
        self.setattrs_and_save_with_retries({
            'status_is_running': True,
            'status_is_waiting': False})
        if self.parent:
            self.parent.set_running_status()

    def add_event(self, event, detail='', is_error=False):
        event = RunEvent(
            event=event, run=self, detail=detail[-1000:], is_error=is_error)
        event.full_clean()
        event.save()

    def push_all_inputs(self):
        if get_setting('TEST_NO_PUSH_INPUTS'):
            return
        unsaved_tasks = {}
        unsaved_task_inputs = []
        unsaved_task_outputs = []
        unsaved_data_nodes = {}
        for leaf in self.get_leaves():
            if leaf.inputs.exists():
                leaf_outputs = leaf.outputs.all()
                for input_set in InputCalculator(leaf)\
                    .get_input_sets():
                    task, task_inputs, task_outputs, data_nodes \
                        = Task.create_unsaved_task_from_input_set(
                            input_set, leaf, leaf_outputs)
                    if task is None:
                        # Task already exists, none to create
                        continue
                    unsaved_tasks[task.uuid] = task
                    unsaved_task_inputs.extend(task_inputs)
                    unsaved_task_outputs.extend(task_outputs)
                    unsaved_data_nodes.update(data_nodes)
            else:
                # Special case: No inputs on leaf node
                task, task_inputs, task_outputs, data_nodes \
                    = Task.create_unsaved_task_from_input_set([], leaf)
                if task is None:
                    continue
                unsaved_tasks[task.uuid] = task
                unsaved_task_inputs.extend(task_inputs)
                unsaved_task_outputs.extend(task_outputs)
                unsaved_data_nodes.update(data_nodes)
        Task.bulk_create_tasks(unsaved_tasks, unsaved_task_inputs,
                               unsaved_task_outputs, unsaved_data_nodes,
                               self.force_rerun)

    def push_all_outputs(self):
        for run in self._get_downstream_runs():
            run.push_all_inputs()

    def _get_downstream_runs(self):
        runs = set()
        for output in self.outputs.all():
            for run_input in output.data_node.downstream_run_inputs.all():
                runs.add(run_input.run)
        return runs

    @classmethod
    def get_dependencies(cls, uuid, request):
        from api.serializers import URLRunSerializer

        context = {'request': request}
        run = cls.objects.filter(uuid=uuid)\
                         .prefetch_related('parent')
        if run.count() < 1:
            raise cls.DoesNotExist
        if run.first().parent:
            runs = [URLRunSerializer(run.first().parent, context=context).data]
        else:
            runs = []
        return {'runs': runs}

    def delete(self):
        from api.models.data_nodes import DataNode
        nodes_to_delete = set()
        for queryset in [
                DataNode.objects.filter(runinput__run__uuid=self.uuid),
                DataNode.objects.filter(runoutput__run__uuid=self.uuid),
                DataNode.objects.filter(userinput__run__uuid=self.uuid),
                DataNode.objects.filter(taskinput__task__run__uuid=self.uuid),
                DataNode.objects.filter(taskoutput__task__run__uuid=self.uuid),
                DataNode.objects.filter(
                    taskattemptinput__task_attempt__tasks__run__uuid=self.uuid),
                DataNode.objects.filter(
                    taskattemptoutput__task_attempt__tasks__run__uuid=self.uuid)
        ]:
            for item in queryset.all():
                nodes_to_delete.add(item)

        # TaskAttempt will not be deleted if shared with another run
        task_attempts_to_cleanup = [item for item in TaskAttempt.objects.filter(
            tasks__run__uuid=self.uuid)]

        # The "imported" flag handles the scenario where:
        # Run A contains run B. A user exports run B and imports it into
        # another loom server. Later another user imports A but then deletes it.
        # B should be preserved. This is done by deleting only children where
        # imported==False
        runs_to_delete = set()
        queryset = Run.objects.filter(parent__uuid=self.uuid, imported=False)
        for item in queryset.all():
            runs_to_delete.add(item)
        super(Run, self).delete()
        for item in nodes_to_delete:
            try:
                item.delete()
            except models.ProtectedError:
                pass
        for run in runs_to_delete:
            run.delete()
        for task_attempt in task_attempts_to_cleanup:
            task_attempt.cleanup()

    def get_leaves(self, leaf_list=None):
        if leaf_list is None:
            leaf_list = []
        if self.is_leaf:
            leaf_list.append(self)
        else:
            for step in self.steps.all():
                step.get_leaves(leaf_list=leaf_list)
        return leaf_list

    def prefetch(self):
        if not hasattr(self, '_prefetched_objects_cache'):
            self.prefetch_list([self,])

    @classmethod
    def prefetch_list(cls, instances):
        queryset = Run\
                   .objects\
                   .filter(uuid__in=[i.uuid for i in instances])
        MAXIMUM_TREE_DEPTH = get_setting('MAXIMUM_TREE_DEPTH')
        # Prefetch 'children', 'children__children', etc. up to max depth               
        # This incurs 1 query per level up to actual depth.                             
        # No extra queries incurred if we go too deep.)                                 
        for i in range(1, MAXIMUM_TREE_DEPTH+1):
            queryset = queryset.prefetch_related('__'.join(['steps']*i))
        # Transfer prefetched steps to original instances
        queried_runs_1 = [run for run in queryset]
        copy_prefetch(queried_runs_1, instances)
        # Flatten tree so we can simultaneously prefetch related models on all nodes
        node_list = []
        for instance in instances:
            node_list.extend(flatten_nodes(instance, 'steps'))
        queryset = Run.objects.filter(uuid__in=[n.uuid for n in node_list])\
            .select_related('template')\
            .prefetch_related('inputs')\
            .prefetch_related('inputs__data_node')\
            .prefetch_related('outputs')\
            .prefetch_related('outputs__data_node')\
            .prefetch_related('user_inputs')\
            .prefetch_related('user_inputs__data_node')\
            .prefetch_related('events')\
            .prefetch_related('tasks')\
            .prefetch_related('tasks__inputs')\
            .prefetch_related('tasks__inputs__data_node')\
            .prefetch_related('tasks__outputs')\
            .prefetch_related('tasks__outputs__data_node')\
            .prefetch_related('tasks__events')\
            .prefetch_related('tasks__all_task_attempts')\
            .prefetch_related('tasks__all_task_attempts__inputs')\
            .prefetch_related('tasks__all_task_attempts__inputs__data_node')\
            .prefetch_related('tasks__all_task_attempts__outputs')\
            .prefetch_related('tasks__all_task_attempts__outputs__data_node')\
            .prefetch_related('tasks__all_task_attempts__events')\
            .prefetch_related('tasks__all_task_attempts__log_files')\
            .prefetch_related('tasks__all_task_attempts__log_files__data_object')\
            .prefetch_related(
                'tasks__all_task_attempts__log_files__data_object__file_resource')\
            .prefetch_related('tasks__task_attempt')\
            .prefetch_related('tasks__task_attempt__inputs')\
            .prefetch_related('tasks__task_attempt__inputs__data_node')\
            .prefetch_related('tasks__task_attempt__outputs')\
            .prefetch_related('tasks__task_attempt__outputs__data_node')\
            .prefetch_related('tasks__task_attempt__events')\
            .prefetch_related('tasks__task_attempt__log_files')\
            .prefetch_related('tasks__task_attempt__log_files__data_object')\
            .prefetch_related(
                'tasks__task_attempt__log_files__data_object__file_resource')
        # Transfer prefetched data to child nodes on original instances
        queried_runs_2 = [run for run in queryset]
        copy_prefetch(queried_runs_2, node_list,
                      child_field='steps', one_to_x_fields=['template',])
        # Prefetch all data nodes
	data_nodes = []
	for instance in instances:
            instance._get_data_nodes(data_nodes)
	DataNode.prefetch_list(data_nodes)

    def _get_data_nodes(self, data_nodes=None):
        if data_nodes is None:
            data_nodes = []
        for input in self.inputs.all():
            if input.data_node:
                data_nodes.append(input.data_node)
        for output in self.outputs.all():
            if output.data_node:
                data_nodes.append(output.data_node)
        for user_input in self.user_inputs.all():
            if user_input.data_node:
                data_nodes.append(user_input.data_node)
        for task in self.tasks.all():
            task._get_data_nodes(data_nodes)
        for run in self.steps.all():
            run._get_data_nodes(data_nodes)
        return data_nodes

    @classmethod
    def _prefetch_for_filter(cls, queryset=None):
        if queryset is None:
            queryset = cls.objects.all()
        return queryset.prefetch_related('tags')

    def _send_email_notifications(self, email_addresses, context):
        if not email_addresses:
            return
        try:
            text_content = render_to_string('email/notify_run_completed.txt',
                                            context)
            html_content = render_to_string('email/notify_run_completed.html',
                                            context)
            connection = mail.get_connection()
            connection.open()
            email = mail.EmailMultiAlternatives(
                'Loom run %s@%s is %s' % (
                    self.name, self.uuid[0:8], self.status.lower()),
                text_content,
                get_setting('DEFAULT_FROM_EMAIL'),
                email_addresses,
            )
            email.attach_alternative(html_content, "text/html")
            email.send()
            connection.close()
        except Exception as e:
            self.add_event(
                "Email notifications failed", detail=str(e), is_error=True)
            raise
        self.add_event("Email notifications sent",
                       detail=email_addresses, is_error=False)

    def _send_http_notifications(self, urls, context):
        if not urls:
            return
        any_failures = False
        try:
            data = {
                'message': 'Loom run %s is %s' % (
                    context['run_name_and_id'],
                    context['run_status']),
                'run_uuid': self.uuid,
                'run_name': self.name,
                'run_status': self.status,
                'run_url': context['run_url'],
                'run_api_url': context['run_api_url'],
                'server_name': context['server_name'],
                'server_url': context['server_url'],
            }
        except Exception as e:
            self.add_event("Http notification failed", detail=str(e), is_error=True)
            raise
        for url in urls:
            try:
                response = requests.post(
                    url,
                    json=data,
                    verify=get_setting('NOTIFICATION_HTTPS_VERIFY_CERTIFICATE'))
                response.raise_for_status()
            except Exception as e:
                self.add_event("Http notification failed", detail=str(e), is_error=True)
                any_failures = True
        if not any_failures:
            self.add_event("Http notification succeeded", detail=', '.join(urls),
                           is_error=False)


class RunEvent(BaseModel):

    run = models.ForeignKey(
        'Run',
	related_name='events',
	on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now,
                                     editable=False)
    event = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    is_error = models.BooleanField(default=False)


class UserInput(DataChannel):

    class Meta:
        unique_together = (("run", "channel"),)

    run = models.ForeignKey(
        'Run',
        related_name='user_inputs',
        on_delete=models.CASCADE)


class RunInput(DataChannel):

    class Meta:
        unique_together = (("run", "channel"),)

    run = models.ForeignKey('Run',
                            related_name='inputs',
                            on_delete=models.CASCADE,
                            null=True, # for testing only
                            blank=True)
    mode = models.CharField(max_length=255, blank=True)
    group = models.IntegerField(null=True, blank=True)
    as_channel = models.CharField(max_length=255, null=True, blank=True)

    def is_ready(self, data_path=None):
        if self.data_node:
            return self.data_node.is_ready(data_path=data_path)
        else:
            return False


class RunOutput(DataChannel):

    class Meta:
        unique_together = (("run", "channel"),)

    run = models.ForeignKey('Run',
                            related_name='outputs',
                            on_delete=models.CASCADE,
                            null=True, # for testing only
                            blank=True)
    mode = models.CharField(max_length=255, blank=True)
    source = jsonfield.JSONField(blank=True)
    parser = jsonfield.JSONField(
	validators=[validators.OutputParserValidator.validate_output_parser],
        blank=True)
    as_channel = models.CharField(max_length=255, null=True, blank=True)


class TaskNode(object):
    """This converts tasks into a tree for the sole purpose of checking
    to see if the tree is complete. Each node knows its degree, so the tree
    is complete if the number of existing children matches the degree, and
    if all those children are also complete.
    """

    def __init__(self):
        self.degree = None
        self.children = {}
        self.task = None

    @classmethod
    def create_from_task_list(cls, tasks):
        root = TaskNode()
        for task in tasks:
            root._extend_to_leaf(task, task.data_path)
        return root

    def _extend_to_leaf(self, task, data_path):
        if len(data_path) == 0:
            self.task = task
            self.degree = None
            return
        else:
            first_hop = data_path.pop(0)
            degree = first_hop[1]
            index = first_hop[0]
            if self.degree is None:
                self.degree = degree
            assert self.degree == degree, 'Degree mismatch in tasks'
            child = self.children.get(index)
            if child is None:
                child = TaskNode()
                self.children[index] = child
            child._extend_to_leaf(task, data_path)

    def is_complete(self):
        if self.degree == None:
            # leaf
            if self.task is not None:
                return self.task.status_is_finished
            else:
                return False
        else:
            # non-leaf
            return len(self.children) == self.degree \
                and all([self.children[i].is_complete() for i in range(self.degree)])
