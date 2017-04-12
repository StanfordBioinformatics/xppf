from django.test import TestCase
from rest_framework import serializers

from api.serializers.tasks import *
from api.models.tasks import *
from api.models.data_objects import BooleanDataObject, StringDataObject, \
    FileResource, FileDataObject
from . import fixtures
from . import get_mock_context

def get_task():
    task = Task.objects.create(
        interpreter='/bin/bash',
        command='echo {{input1}}',
        rendered_command='echo True',
        resources={'memory': '1', 'disk_size': '1', 'cores': '1'},
        environment={'docker_image': 'ubuntu'},
        index=[0],
    )
    input_data_object = BooleanDataObject.objects.create(
        type='boolean',
        value=True
    )
    input = TaskInput.objects.create(task=task,
                                     data_object=input_data_object,
                                     channel='input1',
                                     type='boolean')

    output_data_object = StringDataObject.objects.create(
        type='string',
        value='answer'
    )

    task_output = TaskOutput.objects.create(
        task=task,
        channel='output1',
        type='string',
        data_object=output_data_object,
        source={'stream': 'stdout'}
    )
    task_attempt = TaskAttempt.objects.create(
        task=task,
        interpreter = task.interpreter,
        rendered_command=task.rendered_command,
        environment=task.environment,
        resources=task.resources)
    task_attempt_output = TaskAttemptOutput.objects.create(
        task_attempt=task_attempt,
        data_object=output_data_object,
        type='file',
        channel='test'
    )
    task_attempt_timepoint = TaskAttemptTimepoint.objects.create(
        task_attempt=task_attempt,
        message='oops',
        detail='something went wrong',
        is_error=True)
    log_file_resource = FileResource.objects.create(
        **fixtures.data_objects.file_resource)
    log_file_data_object = FileDataObject.objects.create(
        type='file',
        filename='stderr.log',
        file_resource = log_file_resource,
        md5 = fixtures.data_objects.file_resource['md5'],
        source_type='log',
        )
    log_file = TaskAttemptLogFile.objects.create(
        task_attempt=task_attempt,
        log_name='stderr',
        file=log_file_data_object
    )

    return task

class TestTaskSerializer(TestCase):

    def testRender(self):
        task = get_task()
        s = TaskSerializer(task, context=get_mock_context())
        task_data = s.data
        self.assertEqual(task_data['command'],
                         task.command)


class TestExpandableTaskSerializer(TestCase):

    def testRender(self):
        task = get_task()
        s = ExpandableTaskSerializer(task, context=get_mock_context())
        task_data = s.data
        self.assertEqual(task_data['uuid'],
                         task.uuid)

    
    
