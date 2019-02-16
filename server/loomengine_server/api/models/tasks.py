from django.core.exceptions import ValidationError
from django.db import models, IntegrityError
from django.utils import timezone
import logging
import jsonfield
import time

from . import render_from_template, render_string_or_list, ArrayInputContext, \
    calculate_contents_fingerprint, positiveIntegerDefaultDict
from .base import BaseModel
from .data_channels import DataChannel
from api import get_setting, reload_models, match_and_update_by_uuid
from api import async
from api.exceptions import ConcurrentModificationError
from api.models import uuidstr
from api.models.data_nodes import DataNode
from api.models.task_attempts import TaskAttempt
from api.models import validators

logger = logging.getLogger(__name__)

class TaskAlreadyExistsException(Exception):
    pass


class Task(BaseModel):
    """A Task is a Step executed on a particular set of inputs.
    For non-parallel steps, each Run will have one task. For parallel,
    each Run will have one task for each set of inputs.
    """
    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    interpreter = models.CharField(max_length=1024)
    raw_command = models.TextField()
    command = models.TextField(blank=True)
    environment = jsonfield.JSONField()
    resources = jsonfield.JSONField(blank=True)
    run = models.ForeignKey('Run',
                            related_name='tasks',
                            on_delete=models.CASCADE,
                            null=True, # null for testing only
                            blank=True)
    task_attempt = models.ForeignKey('TaskAttempt',
                                     related_name='active_on_tasks',
                                     on_delete=models.PROTECT,
                                     null=True,
                                     blank=True)
    timeout_failure_count = models.IntegerField(default=0)
    analysis_failure_count = models.IntegerField(default=0)
    system_failure_count = models.IntegerField(default=0)
    data_path = jsonfield.JSONField(
        validators=[validators.validate_data_path],
        blank=True)
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    status_is_finished = models.BooleanField(default=False)
    status_is_failed = models.BooleanField(default=False)
    status_is_killed = models.BooleanField(default=False)
    status_is_running = models.BooleanField(default=False)
    status_is_waiting = models.BooleanField(default=True)

    def execute(self, force_rerun=False, delay=0):
        force_rerun = force_rerun or get_setting('FORCE_RERUN')
        async.execute_with_delay(
            async.execute_task, self.uuid, 
            force_rerun=force_rerun,
            delay=delay)

    def get_fingerprintable_contents(self):
        # Avoid sorted_by because it triggers extra queries
        inputs = sorted(self.inputs.all(), key=lambda i: i.channel)
        input_fingerprints = [i.get_fingerprintable_contents()
                              for i in inputs]
        outputs = sorted(self.outputs.all(), key=lambda o: o.channel)
        output_fingerprints = [o.get_fingerprintable_contents()
                               for o in outputs]
        return {
            'interpreter': self.interpreter,
            'raw_comment': self.raw_command,
            'environment': self.environment,
            'resources': self.resources,
            'inputs': input_fingerprints,
            'outputs': output_fingerprints,
        }

    def calculate_contents_fingerprint(self):
        return calculate_contents_fingerprint(self.get_fingerprintable_contents())

    def get_fingerprint(self):
        fingerprint_value = self.calculate_contents_fingerprint()
        try:
            fingerprint = TaskFingerprint.objects.create(
                value=fingerprint_value)
        except IntegrityError:
            # Fingerprint already exists
            fingerprint = TaskFingerprint.objects.get(value=fingerprint_value)
        return fingerprint

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

    def is_timed_out(self):
        timeout_hours = self.run.timeout_hours
        if not timeout_hours:
            timeout_hours = get_setting('TASK_TIMEOUT_HOURS')
        return (timezone.now() -
                self.task_attempt.datetime_created)\
                .total_seconds()/3600 > timeout_hours

    def is_responsive(self):
        if self.task_attempt and not self.task_attempt.might_succeed():
            return False
        heartbeat = int(get_setting('TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS'))
        timeout = int(get_setting('TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS'))
        try:
            last_heartbeat = self.task_attempt.last_heartbeat
        except AttributeError:
            # No TaskAttempt selected
            last_heartbeat = self.datetime_created
        return (timezone.now() - last_heartbeat).total_seconds() < timeout

    def _process_error(self, detail, max_retries,
                       failure_count_attribute, failure_text,
                       exponential_delay=False):
        if self.has_terminal_status():
            return
        self._kill_children(detail=detail)  # Do this before attempting retry
        failure_count = int(getattr(self, failure_count_attribute)) + 1
        if failure_count <= max_retries:
            self.setattrs_and_save_with_retries(
                {failure_count_attribute: failure_count})
            if not detail:
                detail = 'Restarting task after %s (retry %s/%s)'\
                         %(failure_text.lower(), failure_count, max_retries)
            self.add_event(failure_text, detail=detail, is_error=True)
            if exponential_delay:
                delay = 2**failure_count
            else:
                delay = 0
            self.execute(delay=delay, force_rerun=self.run.force_rerun)
            return
        else:
            if not detail:
                detail='%s. Already used all %s retries' \
                        % (failure_text, max_retries)
            self.setattrs_and_save_with_retries(
                {
                    failure_count_attribute: failure_count,
                    'status_is_failed': True,
                    'status_is_running': False,
                    'status_is_waiting': False
                })
            self.add_event(
                'Retries exceeded for %s' % failure_text.lower(),
                detail=detail,
                is_error=True)
            self.run.fail(detail='Task %s failed' % self.uuid)

    def system_error(self, detail=''):
        self._process_error(
            detail,
            get_setting('MAXIMUM_RETRIES_FOR_SYSTEM_FAILURE'),
            'system_failure_count',
            'System error',
            exponential_delay=True)

    def analysis_error(self, detail=''):
        self._process_error(
            detail,
            get_setting('MAXIMUM_RETRIES_FOR_ANALYSIS_FAILURE'),
            'analysis_failure_count',
            'Analysis error')

    def timeout_error(self, detail=''):
        self._process_error(
            detail,
            get_setting('MAXIMUM_RETRIES_FOR_TIMEOUT_FAILURE'),
            'timeout_failure_count',
            'Timeout error')
    
    def has_terminal_status(self):
        return self.status_is_finished \
            or self.status_is_failed \
            or self.status_is_killed

    def finish(self):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries(
            { 'datetime_finished': timezone.now(),
              'status_is_finished': True,
              'status_is_running': False,
              'status_is_waiting': False,
            })
        self._push_all_outputs()
        for task_attempt in self.all_task_attempts.all():
            task_attempt.cleanup()
        if self.run.are_tasks_finished():
            self.run.finish()

    def kill(self, detail=''):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries({
            'status_is_waiting': False,
            'status_is_running': False,
            'status_is_killed': True
        })
        self.add_event('Task was killed', detail=detail, is_error=True)
        self._kill_children(detail=detail)

    def _kill_children(self, detail=''):
        for task_attempt in self.all_task_attempts.all():
            task_attempt.kill(detail)

    def _push_all_outputs(self):
        task_attempt_output_data_nodes = {}
        for output in self.outputs.all():
            # Copy data from the TaskAttemptOutput to the TaskOutput
            # From there, it is already connected to downstream runs.
            attempt_output = self.task_attempt.get_output(output.channel)
            attempt_output.data_node.clone(seed=output.data_node, save=False)
            task_attempt_output_data_nodes[output.data_node.uuid] = output.data_node
        DataNode.save_list_with_children(
            task_attempt_output_data_nodes.values())
        self.run.push_all_outputs()

    @classmethod
    def bulk_create_tasks(cls, unsaved_tasks, unsaved_task_inputs,
                          unsaved_task_outputs, unsaved_data_nodes, force_rerun):
        if get_setting('TEST_NO_CREATE_TASK'):
            return
        all_data_nodes = DataNode.save_list_with_children(unsaved_data_nodes.values())

        bulk_tasks = Task.objects.bulk_create(unsaved_tasks.values())
        tasks = reload_models(Task, bulk_tasks)

        match_and_update_by_uuid(
            unsaved_task_inputs, 'task', tasks)
        match_and_update_by_uuid(
            unsaved_task_inputs, 'data_node', all_data_nodes)
        TaskInput.objects.bulk_create(unsaved_task_inputs)

        match_and_update_by_uuid(
            unsaved_task_outputs, 'task', tasks)
        match_and_update_by_uuid(
            unsaved_task_outputs, 'data_node', all_data_nodes)
        TaskOutput.objects.bulk_create(unsaved_task_outputs)

        for task in tasks:
            task.run.set_running_status()

        for task in tasks:
            task.execute(force_rerun=force_rerun)
        return tasks

    @classmethod
    def create_unsaved_task_from_input_set(cls, input_set, run, run_outputs):
        try:
            if input_set:
                data_path = input_set.data_path
                if len(filter(lambda t: t.data_path==data_path, run.tasks.all())) > 0:
                    # No-op. Task already exists.
                    return None, [], [], {}
            else:
                # If run has no inputs, we get an empty input_set.
                # Task will go on the root node.
                data_path = []

            task = Task(
                run=run,
                raw_command=run.command,
                interpreter=run.interpreter,
                environment=run.template.environment,
                resources=run.template.resources,
                data_path=data_path,
                status_is_running=True,
                status_is_waiting=False,
            )
            task_inputs = []
            task_outputs = []
            data_nodes = {}
            for input_item in input_set:
                data_node = input_item.data_node.flattened_clone(save=False)
                task_inputs.append(TaskInput(
                    task=task,
                    channel=input_item.channel,
                    as_channel=input_item.as_channel,
                    type=input_item.type,
                    mode=input_item.mode,
                    data_node = data_node))
                data_nodes[data_node.uuid] = data_node
            for run_output in run_outputs:
                data_node = run_output.data_node.get_or_create_node(
                    data_path, save=False)
                task_outputs.append(TaskOutput(
                    channel=run_output.channel,
                    as_channel=run_output.as_channel,
                    type=run_output.type,
                    task=task,
                    mode=run_output.mode,
                    source=run_output.source,
                    parser=run_output.parser,
                    data_node=data_node))
                data_nodes[run_output.data_node.uuid] = run_output.data_node
                data_nodes[data_node.uuid] = data_node
            task.command = task.render_command(task_inputs, task_outputs, data_path)
            return task, task_inputs, task_outputs, data_nodes
        except Exception as e:
            run.fail(detail='Error creating Task: "%s"' % str(e))
            raise

    def create_and_activate_task_attempt(self):
        try:
            task_attempt = TaskAttempt.create_from_task(self)
            self.activate_task_attempt(task_attempt)
            return task_attempt
        except Exception as e:
            self.system_error(detail='Error creating TaskAttempt: "%s"' % str(e))
            raise

    def activate_task_attempt(self, task_attempt):
        self.setattrs_and_save_with_retries({
            'task_attempt': task_attempt,
            'status_is_running': True,
            'status_is_waiting': False})
        self.add_to_all_task_attempts(task_attempt)
        if task_attempt.status_is_finished:
            self.finish()

    def add_to_all_task_attempts(self, task_attempt):
        from api.models.task_attempts import TaskMembership
        tm = TaskMembership(parent_task=self, child_task_attempt=task_attempt)
        tm.save()
        
    def get_input_context(self, inputs=None, data_path=None):
        context = {}
        if inputs is None:
            inputs = self.inputs.all()
        if data_path is None:
            data_path = self.data_path
        # For valid dimesions (integer > 0) where path is not set,
        # return 1 for both index and size.
        index = positiveIntegerDefaultDict(lambda: 1)
        size = positiveIntegerDefaultDict(lambda: 1)
        count = 1
        for index_size_pair in data_path:
            index[count] = index_size_pair[0]+1
            size[count] = index_size_pair[1]
        context['index'] = index
        context['size'] = size
        for input in inputs:
            if input.as_channel:
                channel = input.as_channel
            else:
                channel = input.channel
            if input.data_node.is_leaf:
                context[channel] = input.data_node\
                                        .substitution_value
            else:
                context[channel] = ArrayInputContext(
                    input.data_node.substitution_value,
                    input.type
                )
        return context

    def get_output_context(self, input_context, outputs=None):
        # This returns a value only for Files, where the filename
        # is known beforehand and may be used in the command.
        # For other types, nothing is added to the context.
        context = {}
        if outputs is None:
            outputs = self.outputs.all()
        for output in outputs:
            if output.as_channel:
                channel = output.as_channel
            else:
                channel = output.channel
            if output.source.get('filename'):
                context[channel] = render_string_or_list(
                    output.source.get('filename'), input_context)
        return context

    def get_full_context(self, inputs=None, outputs=None, data_path=None):
        context = self.get_input_context(inputs=inputs, data_path=data_path)
        context.update(self.get_output_context(context, outputs=outputs))
        return context

    def render_command(self, inputs, outputs, data_path):
        return render_from_template(
            self.raw_command,
            self.get_full_context(inputs=inputs, outputs=outputs, data_path=data_path))

    def get_output(self, channel):
        return self.outputs.get(channel=channel)

    def add_event(self, event, detail='', is_error=False):
        event = TaskEvent(
            event=event, task=self,
            detail=detail[-1000:], is_error=is_error)
        event.full_clean()
        event.save()

    @property
    def name(self):
        # In unit tests there may be tasks with no run
        if self.run:
            return self.run.name
        else:
            return str(self.uuid)

    def prefetch(self):
        if not hasattr(self, '_prefetched_objects_cache'):
            self.prefetch_list([self,])

    @classmethod
    def prefetch_list(cls, instances):
        queryset = Task\
                   .objects\
                   .filter(uuid__in=[i.uuid for i in instances])\
                   .prefetch_related('inputs')\
                   .prefetch_related('inputs__data_node')\
                   .prefetch_related('outputs')\
                   .prefetch_related('events')\
                   .prefetch_related('all_task_attempts')\
                   .prefetch_related('all_task_attempts__inputs')\
                   .prefetch_related('all_task_attempts__inputs__data_node')\
                   .prefetch_related('all_task_attempts__outputs')\
                   .prefetch_related('all_task_attempts__outputs__data_node')\
                   .prefetch_related('all_task_attempts__events')\
                   .prefetch_related('all_task_attempts__log_files')\
                   .prefetch_related('all_task_attempts__log_files__data_object')\
                   .prefetch_related(
                       'all_task_attempts__log_files__data_object__file_resource')\
                   .prefetch_related('task_attempt')\
                   .prefetch_related('task_attempt__inputs')\
                   .prefetch_related('task_attempt__inputs__data_node')\
                   .prefetch_related('task_attempt__outputs')\
                   .prefetch_related('task_attempt__outputs__data_node')\
                   .prefetch_related('task_attempt__events')\
                   .prefetch_related('task_attempt__log_files')\
                   .prefetch_related('task_attempt__log_files__data_object')\
                   .prefetch_related(
                       'task_attempt__log_files__data_object__file_resource')
        # Transfer prefetch data to original instances
        for task in queryset:
            for instance in filter(lambda i: i.uuid==task.uuid, instances):
                instance._prefetched_objects_cache = task._prefetched_objects_cache
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
        for task_attempt in self.all_task_attempts.all():
            task_attempt._get_data_nodes(data_nodes)
        if self.task_attempt:
            self.task_attempt._get_data_nodes(data_nodes)
        return data_nodes


class TaskInput(DataChannel):

    task = models.ForeignKey('Task',
                             related_name='inputs',
                             on_delete=models.CASCADE)
    mode = models.CharField(max_length=255)
    as_channel = models.CharField(max_length=255, null=True, blank=True)

    def get_fingerprintable_contents(self):
        return {
            'mode': self.mode,
            'type': self.type,
            'channel': self.as_channel if self.as_channel else self.channel,
            'data': {
                'contents': self.data_node.get_fingerprintable_contents()
            }
        }


class TaskOutput(DataChannel):

    task = models.ForeignKey('Task',
                             related_name='outputs',
                             on_delete=models.CASCADE)
    mode = models.CharField(max_length=255)
    source = jsonfield.JSONField(blank=True)
    parser = jsonfield.JSONField(
	validators=[validators.OutputParserValidator.validate_output_parser],
        blank=True)
    as_channel = models.CharField(max_length=255, null=True, blank=True)

    def get_fingerprintable_contents(self):
        return {
            'mode': self.mode,
            'type': self.type,
            'source': self.source,
            'parser': self.parser,
            'channel': self.as_channel if self.as_channel else self.channel
        }


class TaskEvent(BaseModel):
    task = models.ForeignKey(
        'Task',
        related_name='events',
        on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now,
                                     editable=False)
    event = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    is_error = models.BooleanField(default=False)

class TaskFingerprint(BaseModel):
    value = models.CharField(max_length=255, unique=True)
    active_task_attempt = models.OneToOneField(
        'TaskAttempt',
        related_name='fingerprint',
        on_delete=models.CASCADE,
        null=True,
        blank=True)

    def update_task_attempt_maybe(self, task_attempt):
        if task_attempt is None:
            return
        if task_attempt.status_is_failed or task_attempt.status_is_killed:
            return
        if self.active_task_attempt is None:
            # Save the valid TaskAttempt:
            self.setattrs_and_save_with_retries(
                {'active_task_attempt': task_attempt}
            )
            return
        # Don't update if active_task_attempt already finished
        if self.active_task_attempt.status_is_finished:
            return
        elif task_attempt.status_is_finished:
            # Finished is better than unfinished
            self.setattrs_and_save_with_retries(
                {'active_task_attempt': task_attempt}
            )
        elif task_attempt.status_is_running and \
             not self.active_task_attempt.status_is_running:
            # Running is better than not running or finished
            self.setattrs_and_save_with_retries(
                {'active_task_attempt': task_attempt}
            )
