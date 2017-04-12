from rest_framework.test import RequestsClient
import datetime
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from . import fixtures
from . import get_mock_request, get_mock_context
from api.test.fixtures.many_steps import generator
from api.serializers.templates import *

@override_settings(TEST_DISABLE_ASYNC_DELAY=True)
class TestFixedStepInputSerializer(TestCase):

    def testCreate(self):
        step = Step(command='test command',
                    type='step',
                    name='test')
        step.save()

        s = FixedStepInputSerializer(
            data=fixtures.templates.fixed_step_input,
            context={'parent_field': 'step',
                     'parent_instance': step})
        s.is_valid(raise_exception=True)
        fixed_input = s.save()

        self.assertEqual(
            fixed_input.data_root.data_object.substitution_value,
            fixtures.templates.fixed_step_input['data']['contents'])


    def testRender(self):
        step = Step(command='test command',
                    type='step',
                    name='test')
        step.save()

        s = FixedStepInputSerializer(
            data=fixtures.templates.fixed_step_input,
            context={'parent_field': 'step',
                     'parent_instance': step})
        s.is_valid(raise_exception=True)
        fixed_input = s.save()

        s2 = FixedStepInputSerializer(fixed_input, context=get_mock_context())
        self.assertTrue('uuid' in s2.data['data'].keys())
        

@override_settings(TEST_DISABLE_ASYNC_DELAY=True)
class TestStepSerializer(TransactionTestCase):

    def testCreate(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           WORKER_TYPE='MOCK'):
            s = StepSerializer(data=fixtures.templates.step_a)
            s.is_valid(raise_exception=True)
            m = s.save()

        self.assertEqual(m.command, fixtures.templates.step_a['command'])
        self.assertEqual(
            m.fixed_inputs.first().data_root.data_object.substitution_value,
            fixtures.templates.step_a['fixed_inputs'][0]['data']['contents'])

    def testRender(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           WORKER_TYPE='MOCK'):
            s = StepSerializer(data=fixtures.templates.step_a,
                               context=get_mock_context())
            s.is_valid(raise_exception=True)
            m = s.save()

        self.assertEqual(m.command, s.data['command'])


@override_settings(TEST_DISABLE_ASYNC_DELAY=True)
class TestWorkflowSerializer(TransactionTestCase):

    def testCreateFlatWorkflow(self):
        s = WorkflowSerializer(data=fixtures.templates.flat_workflow,
                               context=get_mock_context())
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.steps.first().step.command,
            fixtures.templates.flat_workflow['steps'][0]['command'])
        self.assertEqual(
            m.fixed_inputs.first().data_root.data_object.substitution_value,
            fixtures.templates.flat_workflow['fixed_inputs'][0]['data']['contents'])

    def testCreateNestedWorkflow(self):
        s = WorkflowSerializer(data=fixtures.templates.nested_workflow)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(
            m.steps.first().workflow.steps.first().step.command,
            fixtures.templates.nested_workflow[
                'steps'][0]['steps'][0]['command'])
        self.assertEqual(
            m.fixed_inputs.first().data_root.data_object.substitution_value,
            fixtures.templates.nested_workflow['fixed_inputs'][0]['data']['contents'])

    def testRender(self):
        s = WorkflowSerializer(data=fixtures.templates.nested_workflow,
                               context=get_mock_context())
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertEqual(s.data['name'], 'nested')

@override_settings(TEST_DISABLE_ASYNC_DELAY=True)
class TestTemplateSerializer(TransactionTestCase):

    def testCreateStep(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           WORKER_TYPE='MOCK'):
            s = TemplateSerializer(data=fixtures.templates.step_a)
            s.is_valid(raise_exception=True)
            m = s.save()

        self.assertEqual(m.step.command, fixtures.templates.step_a['command'])
        self.assertEqual(
            m.fixed_inputs.first().data_root.data_object.substitution_value,
            fixtures.templates.step_a['fixed_inputs'][0]['data']['contents'])

    def testCreateFlatWorkflow(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           WORKER_TYPE='MOCK'):
            s = TemplateSerializer(data=fixtures.templates.flat_workflow)
            s.is_valid(raise_exception=True)
            m = s.save()

        self.assertEqual(
            m.steps.first().step.command, 
            fixtures.templates.flat_workflow['steps'][0]['command'])
        self.assertEqual(
            m.fixed_inputs.first().data_root.data_object.substitution_value,
            fixtures.templates.flat_workflow['fixed_inputs'][0]['data']['contents'])

    def testCreateNestedWorkflow(self):
        with self.settings(TEST_DISABLE_ASYNC_DELAY=True,
                           WORKER_TYPE='MOCK'):
            s = TemplateSerializer(data=fixtures.templates.nested_workflow)
            s.is_valid(raise_exception=True)
            m = s.save()

        self.assertEqual(
            m.steps.first().workflow.steps.first().step.command,
            fixtures.templates.nested_workflow[
                'steps'][0]['steps'][0]['command'])
        self.assertEqual(
            m.fixed_inputs.first().data_root.data_object.substitution_value,
            fixtures.templates.nested_workflow['fixed_inputs'][0]['data']['contents'])

    def testRender(self):
        s = TemplateSerializer(data=fixtures.templates.nested_workflow)
        s.is_valid(raise_exception=True)
        m = s.save()

        s2 = TemplateSerializer(m, context=get_mock_context())
        self.assertEqual(s2.data['name'], 'nested')

    def testCreationPostprocessing(self):

        STEP_COUNT=2
        
        data = generator.make_many_steps(STEP_COUNT)

        s = TemplateSerializer(data=data)
        s.is_valid(raise_exception=True)
        m = s.save()

        self.assertTrue(m.workflow.steps.count() == STEP_COUNT+1)
