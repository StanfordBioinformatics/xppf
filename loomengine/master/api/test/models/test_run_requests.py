from django.test import TransactionTestCase, override_settings

from .test_templates import get_workflow
from api.test.helper import make_run_request
from api import async
from api.models import *


@override_settings(TEST_DISABLE_ASYNC_DELAY=True, TEST_NO_PUSH_INPUTS_ON_RUN_CREATION=True)
class TestRunRequest(TransactionTestCase):

    def testInitialize(self):
        template = get_workflow()
        run_request = make_run_request(template, one='one')

        # Verify that input data to run_request is shared with input
        # node for step
        step_one = run_request.run.workflowrun.steps.all().get(
            steprun__template__name='step_one')
        data = step_one.inputs.first().data_root.data_object
        self.assertEqual(data.substitution_value, 'one')
