from django.test import TestCase

from api.test.models import _get_string_data_node
from api.models.data_objects import *
from api.models.tasks import *


def get_task():
    task = Task.objects.create(
        interpreter='/bin/bash',
        raw_command='echo {{input1}}; echo {{ input3|join(", ") }} {{index[1]}} {{size[1]}} {{index[2]}} {{size[2]}}',
        command='echo True',
        resources={'memory': '1', 'disk_size': '1', 'cores': '1'},
        environment={'docker_image': 'ubuntu'},
        data_path = [[1,2],],
    )
    input_data_node = _get_string_data_node('input1')

    input = TaskInput.objects.create(task=task,
                                     data_node=input_data_node,
                                     channel='input1',
                                     mode='no_gather',
                                     type='boolean')

    input_data_node2 = _get_string_data_node('input2')
    input2 = TaskInput.objects.create(task=task,
                                      data_node=input_data_node2,
                                      channel='input2',
                                      mode='no_gather',
                                      type='string')

    input_data_node3 = _get_string_data_node(
        ['salud','amor','dinero'])

    input3 = TaskInput.objects.create(task=task,
                                      data_node=input_data_node3,
                                      channel='input3',
                                      mode='gather',
                                      type='string')
    output = TaskOutput.objects.create(
        task=task,
        channel='output1',
        type='string',
        mode='no_scatter',
        source={'filename': '{{input2}}.txt'}
    )
    return task


class TestTask(TestCase):

    def setUp(self):
        self.task = get_task()
    
    def testCreate(self):
        self.assertTrue(self.task.command.startswith('echo'))

    def testCreateAttempt(self):
        task_attempt = self.task.create_and_activate_task_attempt()
        self.assertEqual(task_attempt.command, self.task.command)

    def testGetInputContext(self):
        context = self.task.get_input_context()
        self.assertEqual(context['input3'][2], 'dinero')
        self.assertEqual(str(context['input3']), 'salud amor dinero')
        command = self.task.render_command(
            self.task.inputs.all(), self.task.outputs.all(), self.task.data_path)
        self.assertEqual(command, 'echo input1; echo salud, amor, dinero 2 2 1 1')

    def testGetContentsForFingerprint(self):
        self.assertEqual(self.task.calculate_contents_fingerprint(),
                         'adf76dc0c0a43cbc2e5e9f8a001ccfbf')


class TestTaskAttempt(TestCase):

    def setUp(self):
        self.task = get_task()
        self.task_attempt = self.task.create_and_activate_task_attempt()

    def testCreateAttempt(self):
        self.assertEqual(self.task_attempt.outputs.first().channel,
                         self.task.outputs.first().channel)
        self.assertEqual(self.task_attempt.outputs.first().type,
                         self.task.outputs.first().type)
        self.assertEqual(self.task_attempt.outputs.first().source.get('stream'),
                         self.task.outputs.first().source.get('stream'))
        self.assertEqual(self.task_attempt.outputs.first().source.get('filename'),
                         'input2.txt')
