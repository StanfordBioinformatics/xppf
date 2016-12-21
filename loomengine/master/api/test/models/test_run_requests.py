from django.test import TransactionTestCase

from api.models import *
from .test_templates import get_workflow

class TestRunRequest(TransactionTestCase):

    def _get_run_request(self):
        template = get_workflow()
        run_request = RunRequest.objects.create(template=template)
        input_one = RunRequestInput.objects.create(
            run_request=run_request, channel='one')
        data_object = StringDataObject.objects.create(
            type='string', value='one')
        input_one.add_data_as_scalar(data_object)
        with self.settings(DEBUG_DISABLE_TASK_DELAY=True):
            run_request.initialize()
        return run_request

    def testInitialize(self):
        run_request = self._get_run_request()

        # Verify that input data to run_request is shared with input
        # node for step
        step_one = run_request.run.workflowrun.steps.all().get(
            steprun__template__name='step_one')
        data = step_one.inputs.first().data_root.data_object
        self.assertEqual(data.substitution_value, 'one')

