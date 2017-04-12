import os
import yaml

from api.models import RunRequest
from api.serializers import FileDataObjectSerializer, \
    RunRequestSerializer, TemplateSerializer
import loomengine.utils.md5calc

def wait_for_true(test_method, timeout_seconds=20, sleep_interval=None):
    from datetime import datetime
    import time

    if sleep_interval is None:
        sleep_interval = timeout_seconds/10.0
    start_time = datetime.now()
    while not test_method():
        time.sleep(sleep_interval)
        time_running = datetime.now() - start_time
        if time_running.seconds > timeout_seconds:
            raise Exception("Timeout")


def make_run_request(template, **kwargs):
    run_request = {}
    run_request['template'] = '@%s' % str(template.uuid)
    run_request['inputs'] = []

    for (channel, value) in kwargs.iteritems():
        input = template.get_input(channel)
        if input.get('type') == 'file':
            # Files have to be pre-imported.
            # Other data types can be given in the template
            file_path = value
            hash_value = loomengine.utils.md5calc\
                                         .calculate_md5sum(file_path)
            file_data = {
                'type': 'file',
                'filename': os.path.basename(file_path),
                'md5': hash_value,
                'source_type': 'imported',
                'file_resource':{
                    'upload_status': 'complete',
                    'file_url': 'file://' + os.path.abspath(file_path),
                    'md5': hash_value,
                }
            }
            s = FileDataObjectSerializer(data=file_data)
            s.is_valid(raise_exception=True)
            fdo = s.save()
            value = '@%s' % fdo.uuid
        run_request['inputs'].append({
            'channel': channel,
            'data': {'contents': value,},
        })

    s = RunRequestSerializer(data=run_request)
    s.is_valid(raise_exception=True)
    run_request = s.save()
    return run_request

def make_run_request_from_template_file(template_path, **kwargs):
    with open(template_path) as f:
        template_data = yaml.load(f)
    s = TemplateSerializer(data=template_data)
    s.is_valid(raise_exception=True)
    template = s.save()
    return make_run_request(template, **kwargs)


class AbstractRunTest(object):

    def run_template(self, template_path, **kwargs):
        with self.settings(WORKER_TYPE='MOCK'):
            run_request = make_run_request_from_template_file(template_path, **kwargs)
        wait_for_true(
            lambda: RunRequest.objects.get(id=run_request.id).run.postprocessing_status == 'complete', timeout_seconds=120, sleep_interval=1)
        wait_for_true(
            lambda: all([step.postprocessing_status=='complete'
                         for step
                         in RunRequest.objects.get(
                             id=run_request.id).run.workflowrun.steps.all()]),
            timeout_seconds=120,
            sleep_interval=1)

        return run_request
