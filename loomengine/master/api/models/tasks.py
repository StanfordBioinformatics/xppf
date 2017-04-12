from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.utils import timezone
import jsonfield
import os

from .base import BaseModel, render_from_template
from api import get_setting
from api import async
from api.models import uuidstr
from api.models.data_objects import DataObject, FileDataObject


class TaskAlreadyExistsException(Exception):
    pass


def validate_list_of_ints(value):
    try:
        are_ints = [isinstance(i, int) for i in value]
    except TypeError:
        raise ValidationError('Value must be a list of ints')
    if not all(are_ints):
        raise ValidationError('Value must be a list of ints')
    

class Task(BaseModel):

    """A Task is a Step executed on a particular set of inputs.
    For non-parallel steps, each StepRun will have one task. For parallel,
    each StepRun will have one task for each set of inputs.
    """

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    interpreter = models.CharField(max_length=1024)
    command = models.TextField()
    rendered_command = models.TextField(null=True, blank=True)
    environment = jsonfield.JSONField()
    resources = jsonfield.JSONField()
    
    step_run = models.ForeignKey('StepRun',
                                 related_name='tasks',
                                 on_delete=models.CASCADE,
                                 null=True, # null for testing only
                                 blank=True)

    selected_task_attempt = models.OneToOneField('TaskAttempt',
                                                 related_name='task_as_selected',
                                                 on_delete=models.CASCADE,
                                                 null=True,
                                                 blank=True)
    index = jsonfield.JSONField(validators=[validate_list_of_ints],
                                null=True, blank=True)

    # While status_is_running, Loom will continue trying to complete the task
    status_is_running = models.BooleanField(default=True)
    status_is_failed = models.BooleanField(default=False)
    status_is_killed = models.BooleanField(default=False)
    status_is_finished = models.BooleanField(default=False)

    @property
    def attempt_number(self):
        return self.task_attempts.count()

    def is_unresponsive(self):
        heartbeat = int(get_setting('TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS'))
        timeout = int(get_setting('TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS'))
        try:
            last_heartbeat = self.selected_task_attempt.last_heartbeat
        except AttributeError:
            # No TaskAttempt selected
            last_heartbeat = self.datetime_created
        # Actual interval is expected to be slightly longer than setpoint,
        # depending on settings in TaskRunner. If 2.5 x heartbeat_interval
        # has passed, we have probably missed 2 heartbeats 
        return (timezone.now() - last_heartbeat).total_seconds() > timeout

    def fail(self, message, detail=''):
        self.setattrs_and_save_with_retries(
            {'status_is_failed': True,
             'status_is_running': False})
        self.add_timepoint(message, detail=detail, is_error=True)
        if not self.step_run.status_is_failed:
            self.step_run.fail(
                'Task %s failed' % self.uuid,
                detail=detail)
    
    def finish(self):
        self.setattrs_and_save_with_retries(
            { 'datetime_finished': timezone.now(),
              'status_is_finished': True,
              'status_is_running': False })
        self.step_run.add_timepoint('Child Task %s finished successfully' % self.uuid)
        self.step_run.update_status()
        for output in self.outputs.all():
            output.pull_data_object()
            output.push_data_object(self.index)
        for task_attempt in self.task_attempts.all():
            task_attempt.cleanup()

    def kill(self, kill_message):
        self.setattrs_and_save_with_retries({
            'status_is_running': False,
            'status_is_killed': True
        })
        self.add_timepoint('Task killed', detail=kill_message, is_error=True)
        for task_attempt in self.task_attempts.all():
            async.kill_task_attempt(task_attempt.uuid, kill_message)

    @classmethod
    def create_from_input_set(cls, input_set, step_run):
        index = input_set.index
        if step_run.tasks.filter(index=index).count() > 0:
            raise TaskAlreadyExistsException
        task = Task.objects.create(
            step_run=step_run,
            command=step_run.command,
            interpreter=step_run.interpreter,
            environment=step_run.template.environment,
            resources=step_run.template.resources,
            index=index,
        )
        for input in input_set:
            TaskInput.objects.create(
                task=task,
                channel=input.channel,
                type=input.type,
                data_object = input.data_object)
        for step_run_output in step_run.outputs.all():
            task_output = TaskOutput.objects.create(
                channel = step_run_output.channel,
                type=step_run_output.type,
                task=task,
                source=step_run_output.source)
        task = task.setattrs_and_save_with_retries(
            { 'rendered_command': task.render_command() })
        task.add_timepoint('Task %s was created' % task.uuid)
        step_run.add_timepoint('Child Task %s was created' % task.uuid)
        return task

    def create_and_activate_attempt(self):
        try:
            task_attempt = TaskAttempt.create_from_task(self)
            self.setattrs_and_save_with_retries({
                'selected_task_attempt': task_attempt })
            self.add_timepoint('Created child TaskAttempt %s' % task_attempt.uuid)
        except ConcurrentModificationError as e:
            task_attempt.add_timepoint(
                'Failed to update task with newly created task_attempt',
                detail=e.message,
                is_error=True)
            task_attempt.fail()
            raise
        task_attempt.add_timepoint('TaskAttempt %s was created' % task_attempt.uuid)
        return task_attempt

    def get_input_context(self):
        context = {}
        for input in self.inputs.all():
            context[input.channel] = input.data_object\
                                            .substitution_value
        return context

    def get_output_context(self, input_context):
        context = {}
        for output in self.outputs.all():
            # This returns a value only for Files, where the filename
            # is known beforehand and may be used in the command.
            # For other types, nothing is added to the context.
            if output.source.get('filename'):
                context[output.channel] = render_from_template(
                    output.source.get('filename'),
                    input_context)
        return context

    def get_full_context(self):
        context = self.get_input_context()
        context.update(self.get_output_context(context))
        return context

    def render_command(self):
        return render_from_template(
            self.command,
            self.get_full_context())

    def get_output(self, channel):
        return self.outputs.get(channel=channel)

    def add_timepoint(self, message, detail='', is_error=False):
        timepoint = TaskTimepoint.objects.create(
            message=message, task=self, detail=detail, is_error=is_error)


class TaskInput(BaseModel):

    task = models.ForeignKey('Task',
                             related_name='inputs',
                             on_delete=models.CASCADE)
    data_object = models.ForeignKey('DataObject', on_delete=models.PROTECT)
    channel = models.CharField(max_length=255)
    type = models.CharField(max_length = 255,
                            choices=DataObject.DATA_TYPE_CHOICES)


class TaskOutput(BaseModel):

    task = models.ForeignKey('Task',
                             related_name='outputs',
                             on_delete=models.CASCADE)
    channel = models.CharField(max_length=255)
    type = models.CharField(max_length = 255,
                            choices=DataObject.DATA_TYPE_CHOICES)
    source = jsonfield.JSONField(null=True, blank=True)
    data_object = models.ForeignKey('DataObject', on_delete=models.PROTECT,
                                    null=True, blank=True)

    def pull_data_object(self):
        attempt_output = self.task.selected_task_attempt.get_output(self.channel)
        self.setattrs_and_save_with_retries({
            'data_object': attempt_output.data_object })

    def push_data_object(self, index):
        step_run_output = self.task.step_run.get_output(self.channel)
        if self.data_object.is_array:
            raise Exception('TODO: Handle array data objects')
        else:
            step_run_output.push(index, self.data_object)


class TaskTimepoint(BaseModel):
    task = models.ForeignKey(
        'Task',
        related_name='timepoints',
        on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now,
                                     editable=False)
    message = models.CharField(max_length=255)
    detail = models.TextField(null=True, blank=True)
    is_error = models.BooleanField(default=False)


class TaskAttempt(BaseModel):

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    task = models.ForeignKey('Task',
                             related_name='task_attempts',
                             on_delete=models.CASCADE)
    interpreter = models.CharField(max_length=1024)
    rendered_command = models.TextField()
    environment = jsonfield.JSONField()
    resources = jsonfield.JSONField()
    last_heartbeat = models.DateTimeField(auto_now=True)
    status_is_failed = models.BooleanField(default=False)
    status_is_finished = models.BooleanField(default=False)
    status_is_killed = models.BooleanField(default=False)
    status_is_running = models.BooleanField(default=True)
    status_is_cleaned_up = models.BooleanField(default=False)

    def heartbeat(self):
        # Saving with an empty set of attributes will update
        # last_heartbeat since auto_now=True
        self.setattrs_and_save_with_retries({})

    def get_output(self, channel):
        return self.outputs.get(channel=channel)

    def fail(self):
        task_attempt = TaskAttempt.objects.get(uuid=self.uuid)
        task_attempt.status_is_failed = True
        task_attempt.status_is_running = False
        task_attempt.save()
        task_attempt.add_timepoint(
            "TaskAttempt %s failed" % self.uuid,
            detail='The TaskRunner experienced an error when executing '\
            'TaskAttempt %s' % task_attempt.uuid,
            is_error=True)
        try:
            task_attempt.task_as_selected.fail(
                "Child TaskAttempt %s failed" % task_attempt.uuid,
                detail='The TaskRunner experienced an error when executing '\
                'TaskAttempt %s' % task_attempt.uuid)
        except ObjectDoesNotExist:
            # This attempt is no longer active
            # and will be ignored.
            pass

    def finish(self):
        self.setattrs_and_save_with_retries({
            'datetime_finished': timezone.now(),
            'status_is_finished': True,
            'status_is_running': False })
        try:
            task = self.task_as_selected
        except ObjectDoesNotExist:
            # This attempt is no longer active
            # and will be ignored.
            return
        if task.status_is_finished \
           or task.status_is_failed \
           or task.status_is_killed:
            return
        task.add_timepoint("Child TaskAttempt %s finished successfully" % self.uuid)
        task.finish()

    def add_timepoint(self, message, detail='', is_error=False):
        timepoint = TaskAttemptTimepoint.objects.create(
            message=message, task_attempt=self, detail=detail, is_error=is_error)

    @classmethod
    def create_from_task(cls, task):
        task_attempt = cls.objects.create(
            task=task,
            interpreter=task.interpreter,
            rendered_command=task.rendered_command,
            environment=task.environment,
            resources=task.resources
        )
        task_attempt.initialize()
        return task_attempt

    def initialize(self):
        if self.inputs.count() == 0:
            self._initialize_inputs()

        if self.outputs.count() == 0:
            self._initialize_outputs()

    def _initialize_inputs(self):
        for input in self.task.inputs.all():
            TaskAttemptInput.objects.create(
                task_attempt=self,
                type=input.type,
                channel=input.channel,
                data_object=input.data_object)

    def _initialize_outputs(self):
        for task_output in self.task.outputs.all():
            task_attempt_output = TaskAttemptOutput.objects.create(
                task_attempt=self,
                type=task_output.type,
                channel=task_output.channel,
                source=self._render_output_source(task_output.source)
            )

    def _render_output_source(self, task_output_source):
        stream=task_output_source.get('stream')
        if task_output_source.get('filename'):
            filename = render_from_template(
                task_output_source.get('filename'),
                self.task.get_input_context())
        else:
            filename = None

        return {'filename': filename,
                'stream': stream}

    def get_working_dir(self):
        return os.path.join(get_setting('FILE_ROOT_FOR_WORKER'),
                            'runtime_volumes',
                            str(self.uuid),
                            'work')

    def get_log_dir(self):
        return os.path.join(get_setting('FILE_ROOT_FOR_WORKER'),
                            'runtime_volumes',
                            str(self.uuid),
                            'logs')

    def get_worker_log_file(self):
        return os.path.join(self.get_log_dir(), 'worker.log')

    def get_stdout_log_file(self):
        return os.path.join(self.get_log_dir(), 'stdout.log')

    def get_stderr_log_file(self):
        return os.path.join(self.get_log_dir(), 'stderr.log')

    def kill(self, kill_message):
        self.setattrs_and_save_with_retries(
            {'status_is_killed': True,
             'status_is_running': False})
        self.add_timepoint('TaskAttempt killed', detail=kill_message, is_error=True)

    def cleanup(self):
        if self.status_is_cleaned_up:
            return
        if get_setting('PRESERVE_ALL'):
            self.add_timepoint('Skipping cleanup')
            return
        async.cleanup_task_attempt(self.uuid)
        self.setattrs_and_save_with_retries({
            'status_is_cleaned_up': True })
        self.add_timepoint('Cleaning up')


class TaskAttemptInput(BaseModel):

    task_attempt = models.ForeignKey('TaskAttempt',
                             related_name='inputs',
                             on_delete=models.CASCADE)
    data_object = models.ForeignKey('DataObject', on_delete=models.PROTECT)
    channel = models.CharField(max_length=255)
    type = models.CharField(max_length = 255,
                            choices=DataObject.DATA_TYPE_CHOICES)


class TaskAttemptOutput(BaseModel):

    # All info here is saved in the TaskOutput,
    # except for the data_object. If multiple
    # attempts are run, each may have a different
    # data_object.

    task_attempt = models.ForeignKey(
        'TaskAttempt',
        related_name='outputs',
        on_delete=models.CASCADE)
    data_object = models.OneToOneField(
        'DataObject',
        null=True,
        blank=True,
        related_name='task_attempt_output',
        on_delete=models.PROTECT)
    channel = models.CharField(max_length=255)
    type = models.CharField(max_length = 255,
                            choices=DataObject.DATA_TYPE_CHOICES)
    source = jsonfield.JSONField(null=True, blank=True)


class TaskAttemptLogFile(BaseModel):

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    task_attempt = models.ForeignKey(
        'TaskAttempt',
        related_name='log_files',
        on_delete=models.CASCADE)
    log_name = models.CharField(max_length=255)
    file = models.OneToOneField(
        'DataObject',
        null=True,
        blank=True,
        related_name='task_attempt_log_file',
        on_delete=models.PROTECT)
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)

    def initialize_file(self):
        # Create a blank file_data_object on save.
        # The client will upload the file to this object.
        if self.file is not None:
            raise Exception('FileDataObject already exists')
        file = FileDataObject.objects.create(
            source_type='log', type='file', filename=self.log_name)
        self.setattrs_and_save_with_retries(
            {'file': file})
        return self.file


class TaskAttemptTimepoint(BaseModel):
    task_attempt = models.ForeignKey(
        'TaskAttempt',
        related_name='timepoints',
        on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now,
                                     editable=False)
    message = models.CharField(max_length=255)
    detail = models.TextField(null=True, blank=True)
    is_error = models.BooleanField(default=False)
