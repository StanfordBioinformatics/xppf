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


class TestArrayInputContext(TestCase):

    filenames = ['one', 'two.txt', 'three', 'two.txt', 'three', 'three']
    integers = [1, 2, 3, 2, 3, 3]

    def testIterFilenames(self):
        context = ArrayInputContext(self.filenames, 'file', 
                                    {'two.txt': 0, 'three': 0})
        filenames = [item for item in context]
        self.assertEqual(
            filenames,
            ['one', 'two__0__.txt', 'three__0__', 'two__1__.txt',
             'three__1__', 'three__2__']
        )

    def testGetitemFilenames(self):
        context = ArrayInputContext(self.filenames, 'file', 
                                    {'two.txt': 0, 'three': 0})
        self.assertEqual(context[1], 'two__0__.txt')

    def testStrFilenames(self):
        context = ArrayInputContext(self.filenames, 'file', 
                                    {'two.txt': 0, 'three': 0})
        string = str(context)
        self.assertEqual(
            string,
            'one two__0__.txt three__0__ two__1__.txt three__1__ three__2__'
        )
 
    def testIterIntegers(self):
        context = ArrayInputContext(self.integers, 'integer', {})
        values = [item for item in context]
        self.assertEqual(
            values,
            self.integers)


    def testGetitemIntegers(self):
        context = ArrayInputContext(self.integers, 'integer', {})
        values = [item for item in context]
        self.assertEqual(context[1], 2)

    def testStrIntegers(self):
        context = ArrayInputContext(self.integers, 'integer', {})
        string = str(context)
        self.assertEqual(
            string,
            '1 2 3 2 3 3'
        )
