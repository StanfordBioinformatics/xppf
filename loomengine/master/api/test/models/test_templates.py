from django.test import TestCase

from api.models import *


def get_step_one():
    step_one = Step.objects.create(
        name='step_one',
        command='echo {{one}} > {{two})',
        environment={'docker_image': 'ubuntu'},
        resources={'memory': 6, 'cores': 1},
        inputs=[{'channel': 'one', 'type': 'string',
                 'mode': 'no_scatter', 'group': 0}],
        outputs=[{'channel': 'two', 'type': 'string',
                  'source': {'stream': 'stdout'},
                  'mode': 'no_scatter'}],
        type='step',
        postprocessing_status='complete')
    return step_one

def get_step_two():
    step_two = Step.objects.create(
        name='step_two',
        command='echo {{two}} "!" > {{three}})',
        environment={'docker_imate': 'ubuntu'},
        resources={'memory': 6, 'cores': 1},
        inputs=[{'channel': 'two', 'type': 'string',
                 'mode': 'no_scatter', 'group': 0}],
        outputs=[{'channel': 'three', 'type': 'string',
                  'source': {'stream': 'stdout'},
                  'mode': 'no_scatter'}],
        type='step',
        postprocessing_status='complete')
    return step_two
        
def get_workflow():
    workflow = Workflow.objects.create(
        type='workflow',
        name='one_two',
        inputs = [{'channel': 'one', 'type': 'string', 'mode': 'no_gather'}],
        outputs = [{'channel': 'three', 'type': 'string'}],
        postprocessing_status='complete')
    workflow.add_steps([get_step_one(),
                        get_step_two()])
    return workflow



class TestTemplate(TestCase):

    def testCreate(self):

        workflow = get_workflow()

        self.assertEqual(workflow.children.all()[0].child_template.name, 'step_one')
        self.assertEqual(workflow.children.all()[1].child_template.name, 'step_two')
