from django.core import mail
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned, \
    ValidationError
from django.db import models
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone
from mptt.models import MPTTModel, TreeForeignKey
import jsonfield
import requests

from .base import BaseModel
from api import get_setting
from api import async
from api.exceptions import *
from api.models import uuidstr
from api.models import validators
from api.models.data_objects import DataObject
from api.models.data_channels import DataChannel
from api.models.input_calculator import InputCalculator
from api.models.tasks import Task, TaskInput, TaskOutput, TaskAlreadyExistsException
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


class RunAlreadyClaimedForPostprocessingException(Exception):
    pass


class Run(MPTTModel, BaseModel):
    """AbstractWorkflowRun represents the process of executing a Workflow on
    a particular set of inputs. The workflow may be either a Step or a
    Workflow composed of one or more Steps.
    """

    NAME_FIELD = 'name'
    ID_FIELD = 'uuid'

    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    name = models.CharField(max_length=255)
    is_leaf = models.BooleanField()
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    environment = jsonfield.JSONField(
        blank=True,
        validators=[validators.validate_environment])
    resources = jsonfield.JSONField(
        blank=True,
        validators=[validators.validate_resources])
    notification_addresses = jsonfield.JSONField(
        blank=True, validators=[validators.validate_notification_addresses])
    parent = TreeForeignKey('self', null=True, blank=True,
                            related_name='steps', db_index=True,
                            on_delete=models.CASCADE)
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
        assert len(inputs) == 1, 'missing input for channel %s' % channel
        return inputs[0]

    def get_output(self, channel):
        outputs = [o for o in self.outputs.filter(channel=channel)]
        assert len(outputs) == 1, 'missing output for channel %s' % channel
        return outputs[0]

    def get_topmost_run(self):
        try:
            self.run_request
        except ObjectDoesNotExist:
            return self.parent.get_topmost_run()
        return self

    def is_topmost_run(self):
        try:
            self.run_request
        except ObjectDoesNotExist:
            return False
        return True

    def finish(self, request):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries(
            {'status_is_running': False,
             'status_is_waiting': False,
             'status_is_finished': True})
        if self.parent:
            if self.parent._are_children_finished():
                self.parent.finish(request)
        else:
            # Send notifications only if topmost run
            async.send_run_notifications(self.uuid, request)

    def _are_children_finished(self):
        return all([step.status_is_finished for step in self.steps.all()])

    @classmethod
    def create_from_template(cls, template, name=None,
                             notification_addresses=[], parent=None):
                             
        if name is None:
            name = template.name
        if template.is_leaf:
            run = Run.objects.create(
                template=template,
                is_leaf=template.is_leaf,
                name=name,
                command=template.command,
                interpreter=template.interpreter,
                environment=template.environment,
                resources=template.resources,
                notification_addresses=notification_addresses,
                parent=parent)
        else:
            run = Run.objects.create(
                template=template,
                is_leaf=template.is_leaf,
                name=name,
                environment=template.environment,
                resources=template.resources,
                notification_addresses=notification_addresses,
                parent=parent)
        return run

    def _connect_input_to_parent(self, input):
        if self.parent:
            try:
                parent_connector = self.parent.connectors.get(
                    channel=input.channel)
                parent_connector.connect(input)
            except ObjectDoesNotExist:
                self.parent._create_connector(input, is_source=False)

    def _connect_input_to_user_input(self, input):
        try:
            user_input = self.user_inputs.get(channel=input.channel)
        except ObjectDoesNotExist:
            return
        user_input.connect(input)

    def connect_inputs_to_template_data(self):
        for input in self.inputs.all():
            self._connect_input_to_template_data(input)

    def _connect_input_to_template_data(self, input):
        # Do not connect if parent connector.has_source
        if self._has_parent_connector_with_source(input.channel):
            return
        
        # Do not connect if UserInput exists
        if self._has_user_input(input.channel):                
            return

        template_input = self.template.inputs.get(channel=input.channel)

        if template_input.data_node is None:
            raise ValidationError(
                "No input data available on channel %s" % input.channel)
        if input.data_node is None:
            data_node = template_input.data_node.clone()
            input.setattrs_and_save_with_retries({'data_node': data_node})
        else:
            template_input.data_node.clone(seed=input.data_node)
            

    def _has_user_input(self, channel):
        try:
            self.user_inputs.get(channel=channel)
            return True
        except ObjectDoesNotExist:
            return False

    def _has_parent_connector_with_source(self, channel):
        if self.parent is None:
            return False
        try:
            connector = self.parent.connectors.get(channel=channel)
        except ObjectDoesNotExist:
            return False
        return connector.has_source

    def _connect_output_to_parent(self, output):
        if not self.parent:
            return
        try:
            parent_connector = self.parent.connectors.get(
                channel=output.channel)
            if parent_connector.has_source:
                raise ValidationError(
                    'Channel "%s" has more than one source' % output.channel)
            parent_connector.setattrs_and_save_with_retries({'has_source': True})
            parent_connector.connect(output)
        except ObjectDoesNotExist:
            self.parent._create_connector(output, is_source=True)

    def has_terminal_status(self):
        return self.status_is_finished \
            or self.status_is_failed \
            or self.status_is_killed

    def fail(self, request, detail=''):
        if self.has_terminal_status():
            return
        self.setattrs_and_save_with_retries({
            'status_is_failed': True,
            'status_is_running': False,
            'status_is_waiting': False})
        self.add_event("Run failed", detail=detail, is_error=True)
        if self.parent:
            self.parent.fail(request,
                             detail='Failure in step %s@%s' % (
                                 self.name, self.uuid))
        else:
            # Send kill signal to children
            self._kill_children(detail='Automatically killed due to failure')
            # Send notifications only if topmost run
            async.send_run_notifications(self.uuid, request)

    def kill(self, detail=''):
        if self.has_terminal_status():
            return
        self.add_event('Run was killed', detail=detail, is_error=True)
        self.setattrs_and_save_with_retries(
            {'status_is_killed': True,
             'status_is_running': False,
             'status_is_waiting': False})
        self._kill_children(detail=detail)

    def _kill_children(self, detail=''):
        for step in self.steps.all():
            step.kill(detail=detail)
        for task in self.tasks.all():
            task.kill(detail=detail)

    def send_notifications(self, request):
        assert request is not None, 'Request missing'
        server_url = '%s://%s' % (request.scheme,
                                  request.get_host())
        context = {
            'server_name': get_setting('SERVER_NAME'),
            'server_url': server_url,
            'run_url': '%s/#/runs/%s/' % (server_url, self.uuid),
            'run_api_url': '%s/api/runs/%s/' % (server_url, self.uuid),
            'run_status': self.status,
            'run_name_and_id': '%s@%s' % (self.name, self.uuid[0:8])
        }
        notification_addresses = []
        if self.notification_addresses:
            notification_addresses = self.notification_addresses
        if get_setting('LOOM_NOTIFICATION_ADDRESSES'):
            notification_addresses = notification_addresses\
                                     + get_setting('LOOM_NOTIFICATION_ADDRESSES')
        email_addresses = filter(lambda x: '@' in x, notification_addresses)
        urls = filter(lambda x: '@' not in x, notification_addresses)
        self._send_email_notifications(email_addresses, context)
        self._send_http_notifications(urls, context)

    def _send_email_notifications(self, email_addresses, context):
        if not email_addresses:
            return
        text_content = render_to_string('email/notify_run_completed.txt',
                                        context)
        html_content = render_to_string('email/notify_run_completed.html',
                                        context)
        connection = mail.get_connection()
        connection.open()
        email = mail.EmailMultiAlternatives(
            'Loom run %s@%s is %s' % (self.name, self.uuid[0:8], self.status.lower()),
            text_content,
            get_setting('DEFAULT_FROM_EMAIL'),
            email_addresses,
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        connection.close()

    def _send_http_notifications(self, urls, context):
        if not urls:
            return
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
        for url in urls:
            requests.post(url, data = data)

    def set_running_status(self):
        if self.status_is_running and not self.status_is_waiting:
            return
        self.setattrs_and_save_with_retries({
            'status_is_running': True,
            'status_is_waiting': False})
        if self.parent:
            self.parent.set_running_status()

    def add_event(self, event, detail='', is_error=False):
        event = RunEvent.objects.create(
            event=event, run=self, detail=detail[-1000:], is_error=is_error)

    def _claim_for_postprocessing(self):
        # There are two paths to get Run.postprocess():
        # 1. user calls "run" on a template that is already ready, and
        #    run is postprocessed right away.
        # 2. user calls "run" on a template that is not ready, and run
        #    is postprocessed only after template is ready.
        # There is a chance of both paths being executed, so we have to
        # protect against that

        self.postprocessing_status = 'in_progress'
        try:
            self.save()
        except ConcurrentModificationError:
            # The "save" method is overridden in our base model to have concurrency
            # protection. This error implies that the run was modified since
            # it was loaded.
            # Let's make sure it's being postprocessed by another
            # process, and we will defer to that process.
            run = Run.objects.get(uuid=run_uuid)
            if run.postprocessing_status != 'not_started':
                # Good, looks like another worker is postprocessing this run,
                # so we're done here
                raise RunAlreadyClaimedForPostprocessingException
            else:
                # Don't know why this run was modified. Raise an error
                raise Exception('Postprocessing failed due to unexpected '\
                                'concurrent modification')

    @classmethod
    def postprocess(cls, run_uuid, request=None):
        run = Run.objects.get(uuid=run_uuid)
        if run.postprocessing_status == 'complete':
            # Nothing more to do
            return

        try:
            run._claim_for_postprocessing()
        except RunAlreadyClaimedForPostprocessingException:
            return

        try:
            run._push_all_inputs(request)
            for step in run.steps.all():
                step.initialize(request)
            run.setattrs_and_save_with_retries({
                'postprocessing_status': 'complete'})

        except Exception as e:
            run.setattrs_and_save_with_retries({'postprocessing_status': 'failed'})
            run.fail(request, detail='Postprocessing failed with error "%s"' % str(e))
            raise

    def initialize(self, request=None):
        self.connect_inputs_to_template_data()
        self.create_steps()
        async.postprocess_run(self.uuid, request)

    def initialize_inputs(self):
        seen = set()
        for input in self.template.inputs.all():
            assert input.channel not in seen, \
                'Encountered multiple inputs for channel "%s"' \
                % input.channel
            seen.add(input.channel)

            run_input = RunInput.objects.create(
                run=self,
                channel=input.channel,
                as_channel=input.as_channel,
                type=input.type,
                group=input.group,
                mode=input.mode)

            # Create a connector on the current Run so that
            # children can connect on this channel
            self._connect_input_to_user_input(run_input)
            self._connect_input_to_parent(run_input)
            self._create_connector(run_input, is_source=True)

            # Do not connect to template data (fixed inputs)
            # yet, because siblings are still initializing
            # so we don't know if defalt data will be overridden.

    def initialize_outputs(self):
        if not self.template.outputs:
            return
        for output in self.template.outputs:
            kwargs = {'run': self,
                      'type': output.get('type'),
                      'channel': output.get('channel'),
                      'as_channel': output.get('as_channel'),
                      'source': output.get('source'),
                      'parser': output.get('parser')
            }
            if output.get('mode'):
                kwargs.update({'mode': output.get('mode')})
            run_output = RunOutput.objects.create(**kwargs)

            # This takes effect only if the WorkflowRun has a parent
            self._connect_output_to_parent(run_output)

            # Create a connector on the current Run so that
            # children can connect on this channel
            if not self.is_leaf:
                self._create_connector(run_output, is_source=False)

            # If this is a leaf node but has no parents, initialize the
            # DataNode so it will be available for connection by the TaskOutput
            if not run_output.data_node:
                run_output.initialize_data_node()

    def create_steps(self):
        """This is executed by the parent to ensure that all siblings are initialized
        before any are postprocessed.
        """
        if self.is_leaf:
            return
        for step in self.template.steps.all():
            child_run = self.create_from_template(step, parent=self)
            child_run.initialize_inputs()
            child_run.initialize_outputs()

    def _create_connector(self, io_node, is_source):
        if self.is_leaf:
            return
        try:
            connector = RunConnectorNode.objects.create(
                run=self,
                channel=io_node.channel,
                type=io_node.type,
                has_source=is_source
            )
        except ValidationError:
            # Connector already exists. Just use it.
            connector = self.connectors.get(channel=io_node.channel)

            # But first make sure it doesn't have multiple data sources
            if is_source:
                if connector.has_source:
                    raise ValidationError(
                        'Channel "%s" has more than one source'
                        % io_node.channel_name)
                else:
                    connector.has_source = True
                    connector.save()
        connector.connect(io_node)

    def _push_all_inputs(self, request):
        if get_setting('TEST_NO_PUSH_INPUTS_ON_RUN_CREATION'):
            return
        if self.inputs.exists():
            for input in self.inputs.all():
                self.push(input.channel, [], request)
        elif self.is_leaf:
            # Special case: No inputs on leaf node
            self._push_input_set([], request)

    def push(self, channel, data_path, request):
        """Called when new data is available at the given data_path 
        on the given channel. This will trigger creation of new tasks if 1)
        other input data for those tasks is available, and 2) the task with
        that data_path was not already created previously.
        """
        if get_setting('TEST_NO_CREATE_TASK'):
            return
        if not self.is_leaf:
            return
        for input_set in InputCalculator(self.inputs.all(), channel, data_path)\
            .get_input_sets():
            self._push_input_set(input_set, request)

    def _push_input_set(self, input_set, request):
        try:
            task = Task.create_from_input_set(input_set, self)
            async.run_task(task.uuid, request)
        except TaskAlreadyExistsException:
            pass


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


class RunConnectorNode(DataChannel):
    # A connector resides in a workflow. All inputs/outputs on the workflow
    # connect internally to connectors, and all inputs/outputs on the
    # nested steps connect externally to connectors on their parent workflow.
    # The primary purpose of this object is to eliminate directly connecting
    # input/output nodes of siblings since their creation order is uncertain.
    # Instead, connections between siblings always pass through a connector
    # in the parent workflow.

    has_source = models.BooleanField(default=False)
    run = models.ForeignKey('Run',
                            related_name='connectors',
                            on_delete=models.CASCADE)

    class Meta:
        unique_together = (("run", "channel"),)
