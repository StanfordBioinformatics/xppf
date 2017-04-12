from django.test import TestCase

from api.models.data_objects import *
from api.models.tasks import *


def get_task():
    task = Task.objects.create(
        interpreter='/bin/bash',
        command='echo {{input1}}',
        rendered_command='echo True',
        resources={'memory': '1', 'disk_size': '1', 'cores': '1'},
        environment={'docker_image': 'ubuntu'},
        index = [0],
    )
    input_data_object = BooleanDataObject.objects.create(
        type='boolean',
        value=True
    )
    input = TaskInput.objects.create(task=task,
                                     data_object=input_data_object,
                                     channel='input1',
                                     type='boolean')
    input_data_object2 = StringDataObject.objects.create(
        type='string',
        value='mydata',
    )
    input2 = TaskInput.objects.create(task=task,
                                     data_object=input_data_object2,
                                     channel='input2',
                                     type='string')
    output = TaskOutput.objects.create(
        task=task,
        channel='output1',
        type='string',
        source={'filename': '{{input2}}.txt'}
    )
    return task


class TestTask(TestCase):

    def testCreate(self):
        task = get_task()
        self.assertTrue(task.command.startswith('echo'))

    def testCreateAttempt(self):
        task = get_task()
        task_attempt = task.create_and_activate_attempt()
        self.assertEqual(task_attempt.rendered_command, task.rendered_command)


class TestTaskAttempt(TestCase):

    def setUp(self):
        self.task = get_task()
        self.task_attempt = self.task.create_and_activate_attempt()

    def testCreateAttempt(self):
        self.assertEqual(self.task_attempt.outputs.first().channel,
                         self.task.outputs.first().channel)
        self.assertEqual(self.task_attempt.outputs.first().type,
                         self.task.outputs.first().type)
        self.assertEqual(self.task_attempt.outputs.first().source.get('stream'),
                         self.task.outputs.first().source.get('stream'))
        self.assertEqual(self.task_attempt.outputs.first().source.get('filename'),
                         'mydata.txt')
