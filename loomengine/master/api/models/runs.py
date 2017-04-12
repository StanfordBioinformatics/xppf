from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned, ValidationError
from django.db import models
from django.dispatch import receiver
from django.utils import timezone
import jsonfield

from .base import BaseModel
from api import get_setting
from api import async
from api.exceptions import *
from api.models import uuidstr
from api.models.data_objects import DataObject
from api.models.input_output_nodes import InputOutputNode
from api.models.tasks import Task, TaskInput, TaskOutput, TaskAlreadyExistsException
from api.models.templates import Template


"""
This module defines Run and other classes related to
running an analysis
"""


class RunAlreadyClaimedForPostprocessingException(Exception):
    pass


class WorkflowRunManager(object):

    def __init__(self, run):
        assert run.type == 'workflow', \
            'Bad run type--expected "workflow" but found "%s"' % run.type
        self.run = run

    def get_inputs(self):
        return self.run.workflowrun.inputs

    def get_outputs(self):
        return self.run.workflowrun.outputs

    def get_tasks(self):
        raise Exception('No tasks on run of type "workflow"')

    def kill(self, kill_message):
        return self.run.workflowrun._kill(kill_message)
    

class StepRunManager(object):

    def __init__(self, run):
        assert run.type == 'step', \
            'Bad run type--expected "step" but found "%s"' % run.type
        self.run = run

    def get_inputs(self):
        return self.run.steprun.inputs

    def get_outputs(self):
        return self.run.steprun.outputs

    def get_tasks(self):
        return self.run.steprun.tasks

    def kill(self, kill_message):
        return self.run.steprun._kill(kill_message)


class Run(BaseModel):
    """AbstractWorkflowRun represents the process of executing a Workflow on 
    a particular set of inputs. The workflow may be either a Step or a 
    Workflow composed of one or more Steps.
    """

    NAME_FIELD = 'template__name'

    _MANAGER_CLASSES = {
        'step': StepRunManager,
        'workflow': WorkflowRunManager
    }
    uuid = models.CharField(default=uuidstr, editable=False,
                            unique=True, max_length=255)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=255,
                            choices = (('step', 'Step'),
                                       ('workflow', 'Workflow')))
    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    datetime_finished = models.DateTimeField(null=True, blank=True)
    parent = models.ForeignKey('WorkflowRun',
                               related_name='steps',
                               null=True,
                               blank=True,
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
    status_is_running = models.BooleanField(default=True)

    @property
    def status(self):
        if self.status_is_failed:
            return 'Failed'
        elif self.status_is_killed:
            return 'Killed'
        elif self.status_is_running:
            return 'Running'
        elif self.status_is_finished:
            return 'Finished'
        else:
            return 'Unknown'

    @classmethod
    def _get_manager_class(cls, type):
        return cls._MANAGER_CLASSES[type]

    def _get_manager(self):
        return self._get_manager_class(self.type)(self)

    @property
    def inputs(self):
        return self._get_manager().get_inputs()

    @property
    def outputs(self):
        return self._get_manager().get_outputs()

    @property
    def tasks(self):
        return self._get_manager().get_tasks()

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

    @classmethod
    def create_from_template(cls, template, parent=None, run_request=None):
        if template.type == 'step':
            run = StepRun.objects.create(
                template=template,
                name=template.name,
                type=template.type,
                command=template.step.command,
                interpreter=template.step.interpreter,
                parent=parent).run_ptr
            if run_request:
                run_request.setattrs_and_save_with_retries({'run': run})

            # Postprocess run only if postprocessing of template is done.
            # It is possible for the run to be completed before the template
            # is postprocessing_status=='complete'. In that case, the run postprocessing
            # will be triggered by the template postprocessing when the template
            # is ready
            template = Template.objects.get(uuid=template.uuid)
            if template.postprocessing_status == 'complete':
                async.postprocess_step_run(run.uuid)
        else:
            assert template.type == 'workflow', \
                'Invalid template type "%s"' % template.type
            run = WorkflowRun.objects.create(template=template,
                                             name=template.name,
                                             type=template.type,
                                             parent=parent).run_ptr
            if run_request:
                run_request.setattrs_and_save_with_retries({'run': run})

            # Postprocess run only if postprocessing of template is done.
            # It is possible for the run to be completed before the template
            # is postprocessing_status==ready. In that case, the run postprocessing
            # will be triggered by the template postprocessing when the template
            # is ready
            template = Template.objects.get(uuid=template.uuid)
            if template.postprocessing_status == 'complete':
                async.postprocess_workflow_run(run.uuid)

        run.add_timepoint("Run %s@%s was created" % (run.name, run.uuid))
        if run.parent:
            run.parent.add_timepoint("Child run %s@%s was created" % (
                run.name, run.uuid))
        return run.downcast()

    def downcast(self):
        if self.type == 'step':
            try:
                return self.steprun
            except AttributeError:
                # already downcast
                return self
        else:
            assert self.type == 'workflow', \
                'cannot downcast unknown type "%s"' % self.type
            try:
                return self.workflowrun
            except AttributeError:
                # already downcast
                return self

    def _connect_input_to_parent(self, input):
        if self.parent:
            try:
                parent_connector = self.parent.connectors.get(
                    channel=input.channel)
                parent_connector.connect(input)
            except ObjectDoesNotExist:
                self.parent.downcast()._create_connector(input)
            except MultipleObjectsReturned:
                raise ChannelNameCollisionError(
                    'ERROR! There is more than one run input named "%s". '\
                    'Channel names must be unique within a run.' % input.channel)

    def _connect_input_to_run_request(self, input):
        try:
            run_request = self.run_request
        except ObjectDoesNotExist:
            # No run request here
            return
        try:
            run_request_input = run_request.inputs.get(channel=input.channel)
        except MultipleObjectsReturned:
            raise ChannelNameCollisionError(
                'ERROR! There is more than one run input named "%s". '\
                'Channel names must be unique within a run.' % input.channel)
        run_request_input.connect(input)

    def _connect_output_to_parent(self, output):
        if self.parent:
            try:
                parent_connector = self.parent.connectors.get(channel=output.channel)
                parent_connector.connect(output)
            except MultipleObjectsReturned:
                raise ChannelNameCollisionError(
                    'ERROR! There is more than one run output named "%s". '\
                    'Channel names must be unique within a run.' % output.channel)
            except ObjectDoesNotExist:
                self.parent.downcast()._create_connector(output)

    def fail(self, message, detail=''):
        self.setattrs_and_save_with_retries({
            'status_is_failed': True,
            'status_is_running': False})
        self.add_timepoint(message, detail=detail, is_error=True)
        if self.parent:
            self.parent.fail('Run %s failed' % self.uuid, detail=detail)
        else:
            self.kill(detail)

    def kill(self, kill_message):
        return self._get_manager().kill(kill_message)

    def add_timepoint(self, message, detail='', is_error=False):
        timepoint = RunTimepoint.objects.create(
            message=message, run=self, detail=detail, is_error=is_error)

    def _claim_for_postprocessing(self):
        # There are two paths to get Run.postprocess():
        # 1. user calls "run" on a template that is already ready, and
        #    run is postprocessed right away.
        # 2. user calls "run" on a template that is not ready, and run
        #    is postprocessed only after template is ready.
        # There is a chance of both paths being executed, so we have to
        # protect against that

        assert self.template.postprocessing_status == 'complete', \
            'Template not ready, cannot postprocess run %s' % run.uuid

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

    def _push_all_inputs(self):
        if get_setting('TEST_NO_PUSH_INPUTS_ON_RUN_CREATION'):
            return
        for input in self.inputs.all():
            input.push_all()


class RunTimepoint(BaseModel):
    run = models.ForeignKey(
        'Run',
	related_name='timepoints',
	on_delete=models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now,
                                     editable=False)
    message = models.CharField(max_length=255)
    detail = models.TextField(null=True, blank=True)
    is_error = models.BooleanField(default=False)


class WorkflowRun(Run):

    def add_step(self, step_run):
        step_run.setattrs_and_save_with_retries({'parent': self})

    @classmethod
    def postprocess(cls, run_uuid):
        run = WorkflowRun.objects.get(uuid=run_uuid)

        try:
            run._claim_for_postprocessing()
        except RunAlreadyClaimedForPostprocessingException:
            return

        try:
            run._initialize_inputs()
            run._initialize_outputs()
            run._initialize_steps()
            run.setattrs_and_save_with_retries({'postprocessing_status': 'complete'})
        except Exception as e:
            run = WorkflowRun.objects.get(uuid=run_uuid)
            run.setattrs_and_save_with_retries({'postprocessing_status': 'failed'})
            run.fail('Postprocessing failed', detail=e.message)
            raise

    def _initialize_inputs(self):
        run = self.downcast()
        visited_channels = set()
        if run.template.inputs:
            for input in run.template.inputs:
                assert input.get('channel') not in visited_channels, \
                    'Encountered multiple inputs for channel "%s"' \
                    % input.get('channel')
                visited_channels.add(input.get('channel'))

                run_input = WorkflowRunInput.objects.create(
                    workflow_run=run,
                    channel=input.get('channel'),
                    type=input.get('type'),
                )

                # One of these two should always take effect. The other is ignored.
                self._connect_input_to_parent(run_input)
                self._connect_input_to_run_request(run_input)

                # Now create a connector on the current WorkflowRun so that
                # children can connect on this channel
                self._create_connector(run_input)

        for fixed_input in run.template.fixed_inputs.all():
            assert fixed_input.channel not in visited_channels, \
                'Encountered multiple inputs/fixed_inputs for channel "%s"' \
                % fixed_input.channel
            visited_channels.add(fixed_input.channel)

            run_input = WorkflowRunInput.objects.create(
                workflow_run=run,
                channel=fixed_input.channel,
                type=fixed_input.type)

            run_input.connect(fixed_input)

            # Now create a connector on the current WorkflowRun so that
            # children can connect on this channel
            self._create_connector(run_input)

    def _initialize_outputs(self):
        run = self.downcast()
        visited_channels = set()
        for output in run.template.outputs:
            assert output.get('channel') not in visited_channels, \
                'Encountered multiple outputs for channel %s' \
                % output.get('channel')
            visited_channels.add(output.get('channel'))

            run_output = WorkflowRunOutput.objects.create(
                workflow_run=run,
                type=output.get('type'),
                channel=output.get('channel'))

            # This takes effect only if the WorkflowRun has a parent
            self._connect_output_to_parent(run_output)

            # Now create a connector on the current WorkflowRun so that
            # children can connect on this channel
            self._create_connector(run_output)

    def _initialize_steps(self):
        run = self.downcast()
        run = Run.objects.get(id=run.id)
        run = run.downcast()
        for step in run.template.workflow.steps.all():
            self.create_from_template(step, parent=run)

    def _create_connector(self, io_node):
        try:
            connector = WorkflowRunConnectorNode.objects.create(
                workflow_run = self,
                channel = io_node.channel,
                type = io_node.type
            )
        except ValidationError:
            # connector already exists. Just use it.
            connector = self.connectors.get(channel=io_node.channel)
        connector.connect(io_node)

    def update_workflow_status(self):
        if self._are_children_finished():
            self.setattrs_and_save_with_retries({'status_is_running': False,
                                                 'status_is_finished': True})
            self.add_timepoint("Run %s@%s finished successfully" % (
                self.name, self.uuid))
            if self.parent:
                self.parent.add_timepoint("Child Run %s@%s finished successfully" % (
                    self.name, self.uuid))
        if self.parent:
            self.parent.update_workflow_status()

    def _are_children_finished(self):
        return all([step.status_is_finished for step in self.steps.all()])

    def _kill(self, kill_message):
        self.add_timepoint('Run killed', detail=kill_message, is_error=True)
        self.setattrs_and_save_with_retries(
            {'status_is_killed': True,
             'status_is_running': False})
        for step in self.downcast().steps.all():
            step.kill(kill_message)


class StepRun(Run):

    command = models.TextField()
    interpreter = models.CharField(max_length=1024)

    @classmethod
    def postprocess(cls, run_uuid):
        run = StepRun.objects.get(uuid=run_uuid)

        try:
            run._claim_for_postprocessing()
        except RunAlreadyClaimedForPostprocessing:
            return

        try:
            run._initialize_inputs()
            run._initialize_outputs()
            run.setattrs_and_save_with_retries({'postprocessing_status': 'complete'})
            run._push_all_inputs()
        except Exception as e:
            run = StepRun.objects.get(uuid=run_uuid)
            run.setattrs_and_save_with_retries({'postprocessing_status': 'failed'})
            run.fail('Postprocessing failed', detail=e.message)
            raise

    def _initialize_inputs(self):
        visited_channels = set()
        for input in self.template.inputs:
            assert input.get('channel') not in visited_channels, \
                "steprun has multiple inputs for channel '%s'" \
                % input.get('channel')
            visited_channels.add(input.get('channel'))

            run_input = StepRunInput.objects.create(
                step_run=self,
                channel=input.get('channel'),
                type=input.get('type'),
                group=input.get('group'),
                mode=input.get('mode'))
            
            # One of these two should always take effect. The other is ignored.
            self._connect_input_to_parent(run_input)
            self._connect_input_to_run_request(run_input)

        for fixed_input in self.template.fixed_inputs.all():
            assert fixed_input.channel not in visited_channels, \
                "steprun has multiple inputs or fixed inputs for channel "\
                "'%s'" % input.channel
            visited_channels.add(fixed_input.channel)

            run_input = StepRunInput.objects.create(
                step_run=self,
                channel=fixed_input.channel,
                type=fixed_input.type,
                group=fixed_input.group,
                mode=fixed_input.mode)
            run_input.connect(fixed_input)

    def _initialize_outputs(self):
        visited_channels = set()
        for output in self.template.outputs:
            assert output.get('channel') not in visited_channels, \
                "workflowrun has multiple outputs for channel '%s'"\
                % output.get('channel')

            visited_channels.add(output.get('channel'))

            run_output = StepRunOutput.objects.create(
                step_run=self,
                type=output.get('type'),
                channel=output.get('channel'),
                source=output.get('source'),
                mode=output.get('mode'))

            self._connect_output_to_parent(run_output)

    def get_output(self, channel):
        return self.outputs.get(channel=channel)

    def update_status(self):
        self.setattrs_and_save_with_retries({'status_is_running': False,
                                             'status_is_finished': True})
        self.add_timepoint("Run %s@%s finished successfully" % (self.name, self.uuid))
        if self.parent:
            self.parent.add_timepoint(
                "Child Run %s@%s finished successfully" % (self.name, self.uuid))
            self.parent.update_workflow_status()

    def _kill(self, kill_message):
        self.add_timepoint('Run killed', detail=kill_message, is_error=True)
        self.setattrs_and_save_with_retries(
            {'status_is_killed': True,
             'status_is_running': False})
        for task in self.downcast().tasks.all():
            task.kill(kill_message)
            
    def push(self, channel, index):
        """Indicates that new data is available at the given index 
        on the given channel. This may trigger creation of new tasks.
        """
        for input_set in TaskInputManager(
                self.inputs.all(), channel, index).get_ready_input_sets():
            if get_setting('TEST_NO_TASK_CREATION'):
                return
            try:
                task = Task.create_from_input_set(input_set, self)
                async.run_task(task.uuid)
            except TaskAlreadyExistsException:
                pass


class StepRunInput(InputOutputNode):

    step_run = models.ForeignKey('StepRun',
                                 related_name='inputs',
                                 on_delete=models.CASCADE)
    mode = models.CharField(max_length=255)
    group = models.IntegerField()

    def is_ready(self):
        if self.get_data_as_scalar() is None:
            return False
        return self.get_data_as_scalar().is_ready()

    def push_all(self):
        """Notify steps that input data is available.
        This method triggers a separate call to push(index) on the StepRunInput
        for each available DataObject.
        """
        if self.data_root is None:
            return
	self.data_root.push_all()

    def push(self, index):
        """Indicates that new data is available at the given index.
        Notify StepRun.
        """
        self.step_run.push(self.channel, index)


class StepRunOutput(InputOutputNode):

    step_run = models.ForeignKey('StepRun',
                                 related_name='outputs',
                                 on_delete=models.CASCADE,
                                 null=True, # for testing only
                                 blank=True)
    mode = models.CharField(max_length=255)
    source = jsonfield.JSONField(null=True, blank=True)

    def push(self, index, data_object):
        self.add_data_object(index, data_object)
        self.data_root.push_by_index(index)


class WorkflowRunConnectorNode(InputOutputNode):
    # A connector resides in a workflow. All inputs/outputs on the workflow
    # connect internally to connectors, and all inputs/outputs on the
    # nested steps connect externally to connectors on their parent workflow.
    # The primary purpose of this object is to eliminate directly connecting
    # input/output nodes of siblings since their creation order is uncertain.
    # Instead, connections between siblings always pass through a connector
    # in the parent workflow.
    
    workflow_run = models.ForeignKey('WorkflowRun',
                                     related_name='connectors',
                                     on_delete=models.CASCADE)

    class Meta:
        unique_together = (("workflow_run", "channel"),)


class WorkflowRunInput(InputOutputNode):

    workflow_run = models.ForeignKey('WorkflowRun',
                                     related_name='inputs',
                                     on_delete=models.CASCADE)


class WorkflowRunOutput(InputOutputNode):

    workflow_run = models.ForeignKey('WorkflowRun',
                                     related_name='outputs',
                                     on_delete=models.CASCADE)


class TaskInputManager(object):
    """Manages the set of nodes acting as inputs for one step.
    Each input node may have more than one DataObject,
    and DataObjects may arrive to the node at different times.
    """
    def __init__(self, input_nodes, channel, index):
        self.input_nodes = input_nodes
        self.channel = channel
        self.index = index

    def get_ready_input_sets(self):
        """New data is available at the given channel and index. See whether 
        any new tasks can be created with this data.
        """
        for input_node in self.input_nodes:
            if not input_node.is_ready():
                return []
        return [InputSet(self.input_nodes, self.index)]


class InputItem(object):
    """Info needed by the Task to construct a TaskInput
    """

    def __init__(self, input_node, index):
        self.data_object = input_node.get_data_object(index)
        self.type = self.data_object.type
        self.channel = input_node.channel


class InputSet(object):
    """A TaskInputManager can produce one or more InputSets, where each
    InputSet corresponds to a single Task.
    """

    def __init__(self, input_nodes, index):
        self.index = index
        self.input_items = [InputItem(i, index) for i in input_nodes]

    def __iter__(self):
        return self.input_items.__iter__()
