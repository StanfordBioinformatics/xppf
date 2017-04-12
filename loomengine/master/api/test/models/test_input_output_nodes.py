from django.test import TestCase

from api.models.data_objects import *
from api.models.input_output_nodes import *
from api.models.data_trees import MissingBranchError
from api.models.runs import StepRunOutput


def _get_string_data_object(text):
    return StringDataObject.objects.create(
        type='string',
        value=text
    )

class TestInputOutputNode(TestCase):

    def testAddDataObject(self):
        io_node = StepRunOutput.objects.create(channel='test',
                                               mode='no_scatter', type='string')
        path = [(1,2), (0,1)]
        string_value = 'text'
        data_object = _get_string_data_object(string_value)
        io_node.add_data_object(path, data_object)
        with self.assertRaises(MissingBranchError):
            io_node.get_data_object([0,0])
        self.assertEqual(
            io_node.get_data_object([1,0]).substitution_value,
            string_value)
        self.assertEqual(io_node.data_root.id,
                         io_node.data_root.get_node([1,0]).root_node.id)
                         

    def testConnect(self):
        io_node1 = StepRunOutput.objects.create(channel='test',
                                                mode='no_scatter', type='string')
        io_node2 = StepRunOutput.objects.create(channel='test',
                                                mode='no_scatter', type='string')

        io_node1.connect(io_node2)
        self.assertEqual(io_node1.data_root.id, io_node2.data_root.id)

    def testIsConnected(self):
        io_node1 = StepRunOutput.objects.create(channel='test',
                                                mode='no_scatter', type='string')
        io_node2 = StepRunOutput.objects.create(channel='test',
                                                mode='no_scatter', type='string')
        self.assertFalse(io_node1.is_connected(io_node2))

        io_node1.connect(io_node2)
        self.assertTrue(io_node1.is_connected(io_node2))

    def testConnectError(self):
        io_node1 = StepRunOutput.objects.create(channel='test',
                                                mode='no_scatter', type='string')
        io_node2 = StepRunOutput.objects.create(channel='test',
                                                mode='no_scatter', type='string')

        io_node1._initialize_data_root()
        io_node2._initialize_data_root()

        with self.assertRaises(ConnectError):
            io_node1.connect(io_node2)
