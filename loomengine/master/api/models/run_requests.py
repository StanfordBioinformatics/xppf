from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .base import BaseModel
from .input_output_nodes import InputOutputNode
from .runs import Run


class RunRequest(BaseModel):

    """RunRequest contains information submitted by a user
    to create a run, in particular the inputs and the template
    to be used. It also points to the corresponding run.
    """

    datetime_created = models.DateTimeField(default=timezone.now,
                                            editable=False)
    template = models.ForeignKey('Template', on_delete=models.PROTECT)
    run = models.OneToOneField('Run',
                               null=True,
                               blank=True,
                               related_name='run_request',
                               on_delete=models.PROTECT)

    def initialize_run(self):
        Run.create_from_template(self.template, run_request=self)

    @property
    def uuid(self):
        if not self.run:
            return None
        else:
            return self.run.uuid

    def validate_inputs(self):
        # Verify that there is 1 TemplateInput for each RunRequestInput
        # and that their channel names match
        if self.template.inputs is not None:
            template_inputs = [input.get('channel') for input
                               in self.template.inputs]
            for input in self.inputs.all():
                if not input.channel in template_inputs:
                    raise ValidationError(
                        'Run request is invalid. Input channel "%s" does not '\
                        'correspond to any channel in the template'
                        % input.channel)
                template_inputs.remove(input.channel)
            if len(template_inputs) > 0:
                raise ValidationError(
                    'Missing input for channel(s) "%s"' %
                    ', '.join([channel for channel in template_inputs]))


class RunRequestInput(InputOutputNode):

    run_request = models.ForeignKey(
        'RunRequest',
        related_name='inputs',
        on_delete=models.CASCADE)
