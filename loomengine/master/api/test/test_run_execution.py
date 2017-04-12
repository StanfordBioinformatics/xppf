from django.test import TransactionTestCase, override_settings
import os

from .helper import AbstractRunTest, wait_for_true


@override_settings(TEST_DISABLE_ASYNC_DELAY=True, TEST_NO_PUSH_INPUTS_ON_RUN_CREATION=True)
class TestHelloWorld(TransactionTestCase, AbstractRunTest):

    def setUp(self):
        workflow_dir = os.path.join(
            os.path.dirname(__file__), 'fixtures', 'hello_world')
        workflow_file = os.path.join(workflow_dir, 'hello_world.yaml')
        hello_file = os.path.join(workflow_dir, 'hello.txt')
        world_file = os.path.join(workflow_dir, 'world.txt')

        self.run_request = self.run_template(workflow_file,
                                             hello=hello_file,
                                             world=world_file)

    def testRun(self):
        # Verify that all StepRuns have been created
        self.assertIsNotNone(
            self.run_request.run.downcast().steps.filter(name='hello_step'))
        self.assertIsNotNone(
            self.run_request.run.downcast().steps.filter(name='world_step'))

        #wait_for_true(lambda: self.run_request.run.status=='finished')
        
        # Verify that output data objects have been created
        #self.assertIsNotNone(
        #    self.run_request.outputs.first()\
        #    .data_root.data_object)

@override_settings(TEST_DISABLE_ASYNC_DELAY=True, TEST_NO_PUSH_INPUTS_ON_RUN_CREATION=True)
class TestManySteps(TransactionTestCase, AbstractRunTest):

    def setUp(self):
        workflow_dir = os.path.join(
            os.path.dirname(__file__), 'fixtures', 'many_steps')

        workflow_file = os.path.join(workflow_dir, 'many_steps.yaml')

        self.run_request = self.run_template(workflow_file)

    def testRun(self):
        pass
