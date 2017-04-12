import copy
from django.test import TestCase, TransactionTestCase

from . import fixtures
from . import get_mock_request, get_mock_context
from api.serializers.run_requests import *
from api.serializers.templates import TemplateSerializer
from api.models.data_trees import DataTreeNode


class TestRunRequestSerializer(TransactionTestCase):

    def testCreate(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           TEST_NO_PUSH_INPUTS_ON_RUN_CREATION=True,
                           WORKER_TYPE='MOCK'):
            s = TemplateSerializer(data=fixtures.templates.flat_workflow)
            s.is_valid(raise_exception=True)
            workflow = s.save()
            workflow_id = '%s@%s' % (workflow.name, workflow.uuid)

            run_request_data = {
                'template': workflow_id,
                'inputs': [
                    fixtures.run_requests.run_request_input,
                ]
            }

            s = RunRequestSerializer(
                data=run_request_data)
            s.is_valid(raise_exception=True)
            rr = s.save()

        self.assertEqual(
            rr.inputs.first().get_data_as_scalar().substitution_value,
            fixtures.run_requests.run_request_input['data']['contents'])

        uuid = RunRequestSerializer(rr, context=get_mock_context()).data[
            'inputs'][0]['data']['uuid']
        data_tree = DataTreeNode.objects.get(uuid=uuid)

        self.assertEqual(
            data_tree.data_object.substitution_value,
            fixtures.run_requests.run_request_input['data']['contents'])

        self.assertEqual(
            RunRequestSerializer(rr, context=get_mock_context()).data[
                'template']['uuid'],
            rr.template.uuid)

        self.assertEqual(rr.run.template.uuid, rr.template.uuid)

    def testCreateNested(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           TEST_NO_PUSH_INPUTS_ON_RUN_CREATION=True,
                           WORKER_TYPE='MOCK'):
            s = TemplateSerializer(data=fixtures.templates.nested_workflow)
            s.is_valid(raise_exception=True)
            workflow = s.save()

            workflow_id = '%s@%s' % (workflow.name, workflow.uuid)

            run_request_data = {'template': workflow_id}

            s = RunRequestSerializer(
                data=run_request_data)
            s.is_valid(raise_exception=True)

            rr = s.save()

        self.assertEqual(rr.run.template.name, workflow.name)
        self.assertEqual(rr.run.downcast().steps.first().template.name,
                         workflow.steps.first().name)

