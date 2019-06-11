import copy
from datetime import datetime, timedelta
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone
import jsonfield
import logging
import os
import pytz
import subprocess
import threading
import time

from . import render_from_template, render_string_or_list, copy_prefetch
from .base import BaseModel
from .data_channels import DataChannel
from .data_nodes import DataNode
from api import get_setting
from api import async
from api.models import uuidstr
from api.models.data_objects import DataObject, FileResource
from api.models.data_nodes import DataNode
from api.models import validators


logger = logging.getLogger(__name__)

class TaskAttempt(BaseModel):

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    tasks = models.ManyToManyField('Task', through='TaskMembership',
                                   related_name='all_task_attempts')
    interpreter = models.CharField(max_length=1024)
    name = models.CharField(max_length=255, blank=True) # used in Docker container name
    command = models.TextField()
    environment = jsonfield.JSONField()
    environment_info = jsonfield.JSONField(blank=True)
    resources = jsonfield.JSONField(blank=True)
    resources_info = jsonfield.JSONField(blank=True)
    last_heartbeat = models.DateTimeField(auto_now=True)
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    status_is_initializing = models.BooleanField(default=False)
    status_is_finished = models.BooleanField(default=False)
    status_is_failed = models.BooleanField(default=False)
    status_is_killed = models.BooleanField(default=False)
    status_is_running = models.BooleanField(default=False)
    status_is_cleaned_up = models.BooleanField(default=False)

    @property
    def status(self):
        if self.status_is_initializing:
            return 'Initializing'
        if self.status_is_failed:
            return 'Failed'
        elif self.status_is_finished:
            return 'Finished'
        elif self.status_is_killed:
            return 'Killed'
        elif self.status_is_running:
            return 'Running'
        else:
            return 'Unknown'

    def heartbeat(self):
        # Saving with an empty set of attributes will update
        # last_heartbeat since auto_now=True
        self.setattrs_and_save_with_retries({})
        return self.last_heartbeat

    def get_output(self, channel):
        return self.outputs.get(channel=channel)

    def is_responsive(self):
        heartbeat = int(get_setting('TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS'))
        timeout = int(get_setting('TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS'))
        return (timezone.now() - self.last_heartbeat).total_seconds() < timeout
    
    def _process_error(self, failure_text, detail=''):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries(
            {'status_is_failed': True,
             'status_is_running': False})
        self.add_event(failure_text, detail=detail, is_error=True)

    def system_error(self, detail=''):
        self._process_error("System error", detail=detail)
        for task in self.active_on_tasks.all():
            task.system_error(
                detail="Child TaskAttempt %s failed" % self.uuid)

    def analysis_error(self, detail=''):
        self._process_error("Analysis error", detail=detail)
        for task in self.active_on_tasks.all():
            task.analysis_error(
                detail="Child TaskAttempt %s failed" % self.uuid)

    def has_terminal_status(self):
        return self.status_is_finished \
            or self.status_is_failed \
            or self.status_is_killed

    def might_succeed(self):
        return self.status_is_initializing \
            or self.status_is_finished \
            or self.status_is_running

    def finish(self):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries({
            'datetime_finished': timezone.now(),
            'status_is_finished': True,
            'status_is_running': False })
        for task in self.active_on_tasks.all():
            task.finish()

    def add_event(self, event, detail='', is_error=False):
        event = TaskAttemptEvent(
            event=event, task_attempt=self, detail=detail[-1000:], is_error=is_error)
        event.full_clean()
        event.save()

    @classmethod
    def create_from_task(cls, task):
        task_attempt = cls(
            status_is_initializing=True,
            interpreter=task.interpreter,
            command=task.command,
            environment=task.environment,
            resources=task.resources,
            name = task.name,
        )
        task_attempt.full_clean()
        task_attempt.save()
        task_attempt.initialize(task)
        return task_attempt

    def initialize(self, task):
        self._initialize_inputs(task)
        self._initialize_outputs(task)
        # Must add task before setting status to initialized.
        # Otherwise the garbage collector may delete it as an orphan.
        self.setattrs_and_save_with_retries(
            {'status_is_initializing': False,
             'status_is_running': True}
        )

    def _initialize_inputs(self, task):
        for input in task.inputs.all():
            task_attempt_input = TaskAttemptInput(
                task_attempt=self,
                type=input.type,
                channel=input.channel,
                mode=input.mode,
                data_node=input.data_node.flattened_clone(save=True))
            task_attempt_input.full_clean()
            task_attempt_input.save()

    def _initialize_outputs(self, task):
        for task_output in task.outputs.all():
            task_attempt_output = TaskAttemptOutput(
                task_attempt=self,
                type=task_output.type,
                channel=task_output.channel,
                mode=task_output.mode,
                source=self._render_output_source(task_output.source, task),
                parser=task_output.parser
            )
            task_attempt_output.full_clean()
            task_attempt_output.save()

    def _render_output_source(self, task_output_source, task):
        input_context = task.get_input_context()

        stream = task_output_source.get('stream')
        filename = render_from_template(
            task_output_source.get('filename'), input_context)
        filenames = render_string_or_list(
            task_output_source.get('filenames'),
            input_context)
        glob = render_from_template(
            task_output_source.get('glob'), input_context)

        output_source = {}
        if stream:
            output_source['stream'] = stream
        if filename:
            output_source['filename'] = filename
        if filenames:
            output_source['filenames'] = filenames
        if glob:
            output_source['glob'] = glob
        return output_source        

    def kill(self, detail):
        if not self.has_terminal_status():
            self.setattrs_and_save_with_retries(
                {'status_is_killed': True,
                 'status_is_running': False})
            self.add_event('TaskAttempt was killed', detail=detail, is_error=True)
        self.cleanup()

    def cleanup(self):
        if self.status_is_cleaned_up:
            return
        if get_setting('PRESERVE_ALL'):
            self.add_event('Skipped cleanup because PRESERVE_ALL is True',
                           is_error=False)
            return
        if get_setting('PRESERVE_ON_FAILURE') and self.status_is_failed:
            self.add_event('Skipped cleanup because PRESERVE_ON_FAILURE is True',
                           is_error=False)
            return
        async.execute(async.cleanup_task_attempt, self.uuid)

    def run_with_heartbeats(self):
        heartbeat_interval = int(get_setting(
            'TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS'))
        # Polling interval should never be less than heartbeat interval
        polling_interval = min(1, heartbeat_interval)

        t = threading.Thread(target=_run_execute_task_attempt_playbook,
                             args=[self,],
                             kwargs=None)
        t.start()

        last_heartbeat = self.last_heartbeat

        while t.is_alive():
            # Beat if (heartbeat_interval - polling_interval) has elapsed,
            # to ensure that we never exceed heartbeat_interval between beats.
            if (datetime.utcnow().replace(tzinfo=pytz.utc) - last_heartbeat)\
               .total_seconds() > (heartbeat_interval - polling_interval):
                last_heartbeat = self.heartbeat()
            time.sleep(polling_interval)

    def prefetch(self):
        if not hasattr(self, '_prefetched_objects_cache'):
            self.prefetch_list([self,])

    def prefetch_list(cls, instances):
        queryset = TaskAttempt\
                   .objects\
                   .filter(uuid__in=[i.uuid for i in instances])\
                   .prefetch_related('inputs')\
                   .prefetch_related('inputs__data_node')\
                   .prefetch_related('outputs')\
                   .prefetch_related('outputs__data_node')\
                   .prefetch_related('events')\
                   .prefetch_related('log_files')\
                   .prefetch_related('log_files__data_object')\
                   .prefetch_related(
                       'log_files__data_object__file_resource')
        # Transfer prefetch data to original instances
        queried_task_attempts = [item for item in queryset]
        copy_prefetch(queried_task_attempts, instances)
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
        return data_nodes


class TaskAttemptInput(DataChannel):

    task_attempt = models.ForeignKey('TaskAttempt',
                             related_name='inputs',
                             on_delete=models.CASCADE)
    mode = models.CharField(max_length=255)


class TaskAttemptOutput(DataChannel):

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    task_attempt = models.ForeignKey(
        'TaskAttempt',
        related_name='outputs',
        on_delete=models.CASCADE)
    mode = models.CharField(max_length=255)
    source = jsonfield.JSONField(blank=True)
    parser = jsonfield.JSONField(
        validators=[validators.OutputParserValidator.validate_output_parser],
        blank=True)

    def prefetch(self):
        if self.data_node and not hasattr(self.data_node, '_prefetched_objects_cache'):
            self.prefetch_list([self,])

    @classmethod
    def prefetch_list(cls, instances):
        queryset = TaskAttemptOutput\
                   .objects\
                   .filter(uuid__in=[i.uuid for i in instances])\
                   .select_related('data_node')
        queried_outputs = [o for o in queryset]
        # Transfer prefetched DataNodes to original instances
        for output in queried_outputs:
            # Skip if data_node is null
            if output.data_node:
                for instance in filter(lambda i: i.uuid==output.uuid, instances):
                    instance.data_node = output.data_node
        # Prefetch nested DataNode data
        DataNode.prefetch_list([o.data_node for o in queried_outputs])


class TaskAttemptLogFile(BaseModel):

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    task_attempt = models.ForeignKey(
        'TaskAttempt',
        related_name='log_files',
        on_delete=models.CASCADE)
    log_name = models.CharField(max_length=255)
    data_object = models.OneToOneField(
        'DataObject',
        null=True,
        blank=True,
        related_name='task_attempt_log_file',
        on_delete=models.PROTECT)
    # datetime_created used only for sorting in index view
    datetime_created = models.DateTimeField(
        default=timezone.now, editable=False)


class TaskAttemptEvent(BaseModel):

    task_attempt = models.ForeignKey(
        'TaskAttempt',
        related_name='events',
        on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now,
                                     editable=False)
    event = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    is_error = models.BooleanField(default=False)


class TaskMembership(BaseModel):
    parent_task = models.ForeignKey('Task', on_delete=models.CASCADE)
    child_task_attempt = models.ForeignKey('TaskAttempt', on_delete=models.CASCADE)


# To run on new thread
def _run_execute_task_attempt_playbook(task_attempt):
    from django.contrib.auth.models import User
    from django.db import IntegrityError
    from rest_framework.authtoken.models import Token

    if get_setting('LOGIN_REQUIRED'):
        try:
            loom_user = User.objects.create(username='loom-system')
        except IntegrityError:
            loom_user = User.objects.get(username='loom-system')
        try:
            token = Token.objects.get(user=loom_user).key
        except Token.DoesNotExist:
            token = Token.objects.create(user=loom_user).key
    else:
        token = None

    env = copy.copy(os.environ)
    playbook = os.path.join(
        get_setting('PLAYBOOK_PATH'),
        get_setting('RUN_TASK_ATTEMPT_PLAYBOOK'))
    cmd_list = ['ansible-playbook',
                '-i', get_setting('ANSIBLE_INVENTORY'),
                playbook,
                # Without this, ansible uses /usr/bin/python,
                # which may be missing needed modules
                '-e', 'ansible_python_interpreter="/usr/bin/env python"',
    ]

    if get_setting('DEBUG'):
        cmd_list.append('-vvvv')

    if task_attempt.resources:
        disk_size = str(task_attempt.resources.get('disk_size', ''))
        cores = str(task_attempt.resources.get('cores', ''))
        memory = str(task_attempt.resources.get('memory', ''))
    else:
        disk_size = ''
        cores = ''
        memory = ''
    docker_image = task_attempt.environment.get(
        'docker_image')
    new_vars = {'LOOM_TASK_ATTEMPT_ID': str(task_attempt.uuid),
                'LOOM_TASK_ATTEMPT_DOCKER_IMAGE': docker_image,
                'LOOM_TASK_ATTEMPT_STEP_NAME': task_attempt.name,
    }
    if token:
        new_vars['LOOM_TOKEN'] = token
    if cores:
        new_vars['LOOM_TASK_ATTEMPT_CORES'] = cores
    if disk_size:
        new_vars['LOOM_TASK_ATTEMPT_DISK_SIZE_GB'] = disk_size
    if memory:
        new_vars['LOOM_TASK_ATTEMPT_MEMORY'] = memory

    env.update(new_vars)

    try:
        p = subprocess.Popen(cmd_list,
                             env=env,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    except Exception as e:
        logger.error(str(e))
        task_attempt.system_error(detail=str(e))
        return

    terminal_output = ''
    for line in iter(p.stdout.readline, ''):
        terminal_output += line
        print line.strip()
    p.wait()
    if p.returncode != 0:
        logger.error('_run_execute_task_attempt_playbook failed for '\
                     'task_attempt.uuid="%s" with returncode="%s".'
                     % (task_attempt.uuid, p.returncode))
        msg = "Failed to launch worker process for TaskAttempt %s" \
              % task_attempt.uuid
        task_attempt.system_error(detail=terminal_output)
