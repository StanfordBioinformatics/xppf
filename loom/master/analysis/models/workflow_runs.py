from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from analysis.exceptions import *
from analysis.models.base import AnalysisAppInstanceModel, AnalysisAppImmutableModel
from analysis.models.data_objects import DataObject
from analysis.models.task_definitions import TaskDefinition
from analysis.models.task_runs import TaskRun, TaskRunInput, TaskRunOutput
from jinja2 import DictLoader, Environment
from universalmodels import fields


"""
This module defines WorkflowRun and other classes related to
receiving and running a request for analysis.
"""


class WorkflowRun(AnalysisAppInstanceModel):
    """WorkflowRun represents a request to execute a Workflow on a particular
    set of inputs, and the execution status of that Workflow
    """

    NAME_FIELD = 'workflow__workflow_name'

    workflow = fields.ForeignKey('Workflow')
    workflow_run_inputs = fields.OneToManyField('WorkflowRunInput')
    workflow_run_outputs = fields.OneToManyField('WorkflowRunOutput')
    step_runs = fields.OneToManyField('StepRun', related_name='workflow_run')
    channels = fields.OneToManyField('Channel')
    status = fields.CharField(
        max_length=255,
        default='running',
        choices=(('running', 'Running'),
                 ('canceled', 'Canceled'),
                 ('completed', 'Completed')
        )
    )

    @classmethod
    def update_status_for_all(cls):
        for workflow_run in cls.objects.filter(status='running'):
            workflow_run.update_status()

    def update_status(self):
        for step_run in self.step_runs.filter(status='waiting') | self.step_runs.filter(status='running'):
            step_run.update_status()
        step_run_statuses = [step_run.status for step_run in self.step_runs.all()]
        if all([status == 'completed' for status in step_run_statuses]):
            self.update({'status': 'completed'})
        if any([status == 'error' for status in step_run_statuses]):
            self.update({'status': 'error'})

    def cancel(self):
        for step_run in self.step_runs.filter(status='waiting') | self.step_runs.filter(status='running'):
            step_run.cancel()
        self.update({'status': 'canceled'})
    
    @classmethod
    def order_by_most_recent(cls, count=None):
        workflow_runs = cls.objects.order_by('datetime_created').reverse()
        if count is not None and (workflow_runs.count() > count):
            return workflow_runs[:count]
        else:
            return workflow_runs

    @classmethod
    def create(cls, *args, **kwargs):
        workflow_run = super(WorkflowRun, cls).create(*args, **kwargs)
        # WorkflowRunInputs must be already created by the client
        workflow_run._sync_outputs()
        workflow_run._sync_step_runs()
        workflow_run._sync_channels()
        # TODO Assign workflow status (probably w/ default field)
        return workflow_run

    @classmethod
    def validate_create_input(cls, workflow_run_struct):
        # Structure will be validated by creating object.
        # However, channels are implicitly defined, and we have to validate to avoid
        # confusing errors creating channels.

        # First get a list of to_channel names and make sure there are no duplicates
        def add_input(channel_inputs, channel_name):
            if channel_name in channel_inputs:
                raise Exception("The channel '%s' has two data sources. Only one is allowed." % channel_name)
            channel_inputs.append(channel_name)
            
        channel_inputs = []
        if workflow_run_struct.get('workflow_run_inputs') is not None:
            for workflow_run_input in workflow_run_struct['workflow_run_inputs']:
                if workflow_run_input.get('workflow_input') is None:
                    raise Exception('workflow_run_input definition is missing a workflow_input. %s' % workflow_run_input)
                if workflow_run_input['workflow_input'].get('to_channel') is None:
                    raise Exception('workflow_input is missing channel. %s' % workflow_run_input['workflow_input'])
                channel_name = workflow_run_input['workflow_input']['to_channel']
                add_input(channel_inputs, channel_name)
        if workflow_run_struct.get('workflow') is None:
            raise Exception('WorkflowRun definition is invalid. Missing workflow. %s' % workflow_run_struct)
        if workflow_run_struct['workflow']['steps'] is None:
            raise Exception('Workflow definition is invalid. Missing steps. %s' % workflow_run_struct['workflow'])
        for step in workflow_run_struct['workflow']['steps']:
            if step.get('step_outputs') is None:
                raise Exception('Step definition is invalid, missing step_outputs. %s' % step)
            for step_output in step['step_outputs']:
                if step_output.get('to_channel') is None:
                    raise Exception('step_output definition is invalid. Missing "to_channel". %s' % step_output)
                channel_name = step_output['to_channel']
                add_input(channel_inputs, channel_name)

        # Now verify that every from_channel has a source channel defined
        def check_source(channel_inputs, channel_name):
            if channel_name not in channel_inputs:
                raise Exception("from_channel '%s' is defined, but it has no source. "\
                                "There should be a corresponding workflow_input or a step_output with to_channel '%s'"
                                % (channel_name, channel_name))

        if workflow_run_struct['workflow'].get('workflow_outputs') is None:
            raise Exception('Invalid workflow, missing workflow_outputs. %s' % workflow_run_struct['workflow'])
        for workflow_output in  workflow_run_struct['workflow']['workflow_outputs']:
            if workflow_output.get('from_channel') is None:
                raise Exception('Invalid workflow output, from_channel is missing. %s' % workflow_output)
            channel_name = workflow_output['from_channel']
            check_source(channel_inputs, channel_name)
        for step in workflow_run_struct['workflow']['steps']:
            if step.get('step_inputs') is not None:
                for step_input in step['step_inputs']:
                    if step_input.get('from_channel') is None:
                        raise Exception('step_input definition is invalid. Missing "from_channel". %s' % step_input)
                    channel_name = step_input.get('from_channel')
                    check_source(channel_inputs, channel_name)
                
    def _sync_outputs(self):
        for workflow_output in self.workflow.workflow_outputs.all():
            self._sync_output(workflow_output)

    def _sync_output(self, workflow_output):
        """Create a workflow_run_output corresponding each workflow_output if it does not already exist.
        """
        try:
            self.workflow_run_outputs.get(workflow_output___id=workflow_output._id)
            return
        except ObjectDoesNotExist:
            self.workflow_run_outputs.add(
                WorkflowRunOutput.create(
                    {'workflow_output': workflow_output.to_struct()}
                )
            )

    def _sync_step_runs(self):
        for step in self.workflow.steps.all():
            self._sync_step_run(step)

    def _sync_step_run(self, step):
        """Create a step_run corresponding each step if it does not already exist.
        """
        try:
            self.step_runs.get(step___id=step._id)
            return
        except ObjectDoesNotExist:
            step_run = StepRun.create(
                {'step': step.to_struct(),
                 'workflow_name': self.workflow.workflow_name,
                 'workflow_run_datetime_created': self.datetime_created
                }
            )
            self.step_runs.add(step_run)
            for step_input in step_run.step.step_inputs.all():
                step_run.step_run_inputs.add(
                    StepRunInput.create(
                        {'step_input': step_input.to_struct()}
                    ))
            for step_output in step_run.step.step_outputs.all():
                step_run.step_run_outputs.add(
                    StepRunOutput.create(
                        {'step_output': step_output.to_struct()}
                    )
                )
    
    def _sync_channels(self):
        # One per workflow_run_input and one per step_run_output
        for workflow_run_input in self.workflow_run_inputs.all():
            channel_name = workflow_run_input.workflow_input.to_channel
            try:
                self._get_channel_by_name(channel_name)
            except ObjectDoesNotExist:
                self._add_channel(workflow_run_input, channel_name)
        for step_run in self.step_runs.all():
            for step_run_output in step_run.step_run_outputs.all():
                channel_name = step_run_output.step_output.to_channel
                try:
                    self._get_channel_by_name(channel_name)
                except ObjectDoesNotExist:
                    self._add_channel(step_run_output, channel_name)
        self._create_subchannels()
        self._add_input_data_objects_to_channels()
                
    def _add_channel(self, workflow_run_input_or_step_run_output, channel_name):
        channel = Channel.create({'channel_name': channel_name})
        self.channels.add(channel)
        workflow_run_input_or_step_run_output.add_channel(channel)

    def _get_channel_by_name(self, channel_name):
        return self.channels.get(channel_name=channel_name)

    def _create_subchannels(self):
        # One per workflow_run_ouput and step_run_input
        for workflow_run_output in self.workflow_run_outputs.all():
            channel_name = workflow_run_output.workflow_output.from_channel
            self._add_subchannel(workflow_run_output, channel_name)
        for step_run in self.step_runs.all():
            for step_run_input in step_run.step_run_inputs.all():
                channel_name = step_run_input.step_input.from_channel
                self._add_subchannel(step_run_input, channel_name)

    def _add_subchannel(self, workflow_run_output_or_step_run_input, channel_name):
        channel = self._get_channel_by_name(channel_name)
        if workflow_run_output_or_step_run_input.subchannel is None:
            subchannel = channel.create_subchannel(workflow_run_output_or_step_run_input)
    
    def _add_input_data_objects_to_channels(self):
        for workflow_run_input in self.workflow_run_inputs.all():
            channel_name = workflow_run_input.workflow_input.to_channel
            channel = self._get_channel_by_name(channel_name)
            channel.add_data_object(workflow_run_input.data_object)
            channel.update({'is_closed_to_new_data': True})

    def get_workflow_run_input_by_name(self, input_name):
        return self.workflow_run_inputs.get(input_name=input_name)
        
    
class WorkflowRunInput(AnalysisAppInstanceModel):
    """WorkflowRunInput serves as a binding between a DataObject and a Workflow input
    in a WorkflowRun
    """

    workflow_input = fields.ForeignKey('WorkflowInput')
    data_object = fields.ForeignKey('DataObject', null=True)
    channel = fields.ForeignKey('Channel', null=True)

    def add_channel(self, channel):
        self.update({'channel': channel.to_struct()})


class WorkflowRunOutput(AnalysisAppInstanceModel):

    workflow_output = fields.ForeignKey('WorkflowOutput')
    subchannel = fields.ForeignKey('Subchannel', null=True)

    def add_subchannel(self, subchannel):
        self.update({'subchannel': subchannel.to_struct()})


class Channel(AnalysisAppInstanceModel):
    """Channel acts as a queue for data objects being being passed into or out of steps.
    """

    channel_name = fields.CharField(max_length=255)
    subchannels = fields.OneToManyField('Subchannel')
    is_closed_to_new_data = fields.BooleanField(default=False)

    def add_data_object(self, data_object):
        for subchannel in self.subchannels.all():
            subchannel.add_data_object(data_object)
    
    def create_subchannel(self, workflow_run_output_or_step_run_input):
        subchannel = Subchannel.create({'channel_name': self.channel_name})
        self.subchannels.add(subchannel)
        workflow_run_output_or_step_run_input.add_subchannel(subchannel)

    def close(self):
        self.update({'is_closed_to_new_data': True})


class Subchannel(AnalysisAppInstanceModel):
    """Every channel can have only one source but 0 or many destinations, representing
    the possibility that a file produce by one step can be used by 0 or many other 
    steps. Each of these destinations has its own queue, implemented as a Subchannel.
    """

    channel_name = fields.CharField(max_length=255)
    data_objects = fields.ManyToManyField('DataObject')

    def add_data_object(self, data_object):
        self.data_objects.add(data_object)

    def is_empty(self):
        return self.data_objects.count() == 0

    def is_dead(self):
        return self.channel.is_closed_to_new_data and self.is_empty()

    def pop(self):
        data_object = self.data_objects.first()
        self.data_objects = self.data_objects.all()[1:]
        return data_object


class StepRun(AnalysisAppInstanceModel):

    step = fields.ForeignKey('Step')
    step_run_inputs = fields.OneToManyField('StepRunInput')
    step_run_outputs = fields.OneToManyField('StepRunOutput')
    task_runs = fields.OneToManyField('TaskRun')
    workflow_name = fields.CharField(max_length=255, default='')
    workflow_run_datetime_created = fields.DateTimeField(default=timezone.now) 
    status = fields.CharField(
        max_length=255,
        default='waiting',
        choices=(('waiting', 'Waiting'),
                 ('running', 'Running'),
                 ('completed', 'Completed'),
                 ('canceled', 'Canceled'),
                 ('error', 'Error'),
        )
    )

    def update_status(self):
        while True:
            if not self._are_inputs_ready():
                break
            else:
                self.update({'status': 'running'})
                self._create_task_run()
        for task_run in self.task_runs.filter(status='ready_to_run') | self.task_runs.filter(status='running'):
            task_run.update_status()
        # Are input sources all finished?
        if all([input.subchannel.is_dead() for input in self.step_run_inputs.all()]):
            # Are all the lingering runs finished?
            if all([task_run.status == 'completed' for task_run in self.task_runs.all()]):
                #Then mark the StepRun completed and close all the channels it feeds
                self._mark_completed()
        if any([task_run.status == 'error' for task_run in self.task_runs.all()]):
            self.update({'status': 'error'})

    def cancel(self):
        for task_run in self.task_runs.filter(status='ready_to_run') | self.task_runs.filter(status='running'):
            task_run.cancel()
        self.update({'status': 'canceled'})
                
    def _mark_completed(self):
        for output in self.step_run_outputs.all():
            output.close()
        self.update({'status': 'completed'})

    def _get_task_inputs(self):
        if not self._are_inputs_ready():
            raise MissingInputsError('Inputs are missing')
        input_data_objects = []
        for step_run_input in self.step_run_inputs.all():
            name = step_run_input.step_input.from_channel
            data_object = step_run_input.subchannel.pop()
            input_data_objects.append((name, data_object))
        return input_data_objects

    def _are_inputs_ready(self):
        if self.step_run_inputs.count() == 0:
            # Special case: Task has no inputs. We can't determine if this has been processed by
            # checking for an empty queue.
            # If there exists a healthy TaskRun, say no.
            return self.task_runs.count() == 0
        # Return False if any input channel has 0 items in queue
        for step_run_input in self.step_run_inputs.all():
            if step_run_input.subchannel.data_objects.count() == 0:
                return False
        return True

    def _create_task_run(self):
        # This has the form [(channel_name, data_object), ...]
        input_data_objects = self._get_task_inputs()
        
        task_run_inputs = self._create_task_run_inputs(input_data_objects)
        task_run_outputs = self._create_task_run_outputs()
        task_definition = self._create_task_definition(task_run_inputs, task_run_outputs)

        task_run = TaskRun.create({
            'task_run_inputs': task_run_inputs,
            'task_run_outputs': task_run_outputs,
            'task_definition': task_definition,
            'step_name': self.step.step_name,
            'workflow_name': self.workflow_name,
            'workflow_run_datetime_created': self.workflow_run_datetime_created
        })
        
        self.task_runs.add(task_run)

    def _create_task_run_inputs(self, input_data_objects):
        task_run_inputs = []
        for channel_name, data_object in input_data_objects:
            task_run_input = TaskRunInput.create(
                {
                    'task_definition_input': {
                        'data_object': data_object.to_struct()
                    }
                }
            )
            step_run_input = self._get_input_by_channel(channel_name)
            step_run_input.add_task_run_input(task_run_input)
            task_run_inputs.append(task_run_input.to_struct())
        return task_run_inputs

    def _create_task_run_outputs(self):
        task_run_outputs = []
        for step_run_output in self.step_run_outputs.all():
            task_run_output = TaskRunOutput.create({
                'task_definition_output': {
                    'path': step_run_output.step_output.from_path
                }
            })
            step_run_output.add_task_run_output(task_run_output)
            task_run_outputs.append(task_run_output.to_struct())
        return task_run_outputs

    def _create_task_definition(self, task_run_inputs, task_run_outputs):
        task_definition_inputs = [i['task_definition_input'] for i in task_run_inputs]
        task_definition_outputs = [o['task_definition_output'] for o in task_run_outputs]
        return {
            'inputs': task_definition_inputs,
            'outputs': task_definition_outputs,
            'command': self._get_task_definition_command(self.step.command, task_definition_inputs, task_definition_outputs),
            'environment': self._get_task_definition_environment(self.step.environment)
        }

    def _get_task_definition_command(self, raw_command, task_definition_inputs, task_definition_outputs):
        context = {}
        for (step_run_input, task_definition_input) in zip(self.step_run_inputs.all(), task_definition_inputs):
            context[step_run_input.subchannel.channel_name] = task_definition_input['data_object']['file_name']
        for (step_run_output, task_definition_output) in zip(self.step_run_outputs.all(), task_definition_outputs):
            context[step_run_output.channel.channel_name] = task_definition_output['path']
        loader = DictLoader({'template': raw_command})
        env = Environment(loader=loader)
        template = env.get_template('template')
        command = template.render(**context)
        return command

    def _get_task_definition_environment(self, requested_environment):
        # TODO get specific docker image ID
        return {
            'docker_image': requested_environment.downcast().docker_image
        }

    def _get_input_by_channel(self, channel_name):
        return self.step_run_inputs.get(subchannel__channel_name=channel_name)

    def _get_output_by_channel():
        return self.step_run_outputs.get(channel__channel_name=channel_name)


class StepRunInput(AnalysisAppInstanceModel):
    step_input = fields.ForeignKey('StepInput')
    task_run_inputs = fields.ManyToManyField('TaskRunInput')
    subchannel = fields.ForeignKey('Subchannel', null=True)

    def add_subchannel(self, subchannel):
        self.update({'subchannel': subchannel.to_struct()})

    def add_task_run_input(self, task_run_input):
        self.task_run_inputs.add(task_run_input)

class StepRunOutput(AnalysisAppInstanceModel):
    step_output = fields.ForeignKey('StepOutput', null=True)
    task_run_outputs = fields.ManyToManyField('TaskRunOutput', related_name='step_run_outputs')
    channel = fields.ForeignKey('Channel', null=True)

    def add_channel(self, channel):
        self.update({'channel': channel.to_struct()})

    def add_task_run_output(self, task_run_output):
        self.task_run_outputs.add(task_run_output)

    def close(self):
        self.channel.close()
