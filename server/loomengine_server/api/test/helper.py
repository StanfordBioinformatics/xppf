import os
import yaml

from api.models import Run
from api.serializers import DataObjectSerializer, \
    RunSerializer, TemplateSerializer
import loomengine_utils.md5calc

def request_run(template, **kwargs):
    run = {}
    run['template'] = '@%s' % str(template.uuid)
    run['user_inputs'] = []

    for (channel, value) in kwargs.iteritems():
        input = template.get_input(channel)
        if input.type == 'file':
            # Files have to be pre-imported.
            # Other data types can be given in the template
            file_path = value
            hash_value = loomengine_utils.md5calc\
                                         .calculate_md5sum(file_path)
            file_data = {
                'type': 'file',
                'value': {
                    'filename': os.path.basename(file_path),
                    'md5': hash_value,
                    'source_type': 'imported',
                    'upload_status': 'complete',
                    'file_url': 'file://' + os.path.abspath(file_path),
                }
            }
            s = DataObjectSerializer(data=file_data)
            s.is_valid(raise_exception=True)
            fdo = s.save()
            value = '@%s' % fdo.uuid
        run['user_inputs'].append({
            'channel': channel,
            'data': {'contents': value,},
        })

    s = RunSerializer(data=run)
    s.is_valid(raise_exception=True)
    run = s.save()
    return run

def request_run_from_template_file(template_path, **kwargs):
    with open(template_path) as f:
        template_data = yaml.load(f, Loader=yaml.SafeLoader)
    s = TemplateSerializer(data=template_data)
    s.is_valid(raise_exception=True)
    template = s.save()
    return request_run(template, **kwargs)
