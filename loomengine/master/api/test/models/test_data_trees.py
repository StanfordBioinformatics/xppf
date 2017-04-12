from django.test import TestCase

from api.models.data_objects import StringDataObject
from api.models.data_trees import *


def _get_string_data_object(text):
    return StringDataObject.objects.create(
        type='string',
        value=text
    )

class TestDataTreeNode(TestCase):

    def testAddDataObject(self):
        input_data=(
            ([(0,3),(0,1)], 'i'),
            ([(1,3),(0,2)], 'a'),
            ([(1,3),(1,2)], 'm'),
            ([(2,3),(0,5)], 'r'),
            ([(2,3),(1,5)], 'o'),
            ([(2,3),(2,5)], 'b'),
            ([(2,3),(3,5)], 'o'),
            ([(2,3),(4,5)], 't'),
        )
        
        root = DataTreeNode.objects.create()
        
        for path, letter in input_data:
            data_object = _get_string_data_object(letter)
            root.add_data_object(path, data_object)

        # spot check [['i'],['a','m'],['r','o','b','o','t']]
        self.assertEqual(root.get_data_object([0,0]).substitution_value, 'i')
        self.assertEqual(root.get_data_object([1,0]).substitution_value, 'a')
        self.assertEqual(root.get_data_object([1,1]).substitution_value, 'm')
        self.assertEqual(root.get_data_object([2,4]).substitution_value, 't')

    def testMissingData(self):
        input_data=(
            ([(0,3),(0,1)], 'i'),
            #([(1,3),(0,2)], 'a'),
            #([(1,3),(1,2)], 'm'),
            ([(2,3),(0,5)], 'r'),
            #([(2,3),(1,5)], 'o'),
            ([(2,3),(2,5)], 'b'),
            ([(2,3),(3,5)], 'o'),
            ([(2,3),(4,5)], 't'),
        )

        root = DataTreeNode.objects.create()
        
        for path, letter in input_data:
            data_object = _get_string_data_object(letter)
            root.add_data_object(path, data_object)

        # spot check [['i'],['a','m'],['r','o','b','o','t']]
        self.assertEqual(root.get_data_object([0,0]).substitution_value, 'i')
        with self.assertRaises(MissingBranchError):
            root.get_data_object([1,])
        with self.assertRaises(MissingBranchError):
            root.get_data_object([2,1])
        self.assertEqual(root.get_data_object([2,4]).substitution_value, 't')

    def testAddScalarDataObject(self):
        root = DataTreeNode.objects.create()
        text = 'text'
        data_object = _get_string_data_object(text)
        path = []
        root.add_data_object(path, data_object)
        self.assertEqual(root.get_data_object(path).substitution_value, text)
        
    def testAddScalarDataObjectTwice(self):
        root = DataTreeNode.objects.create()
        text = 'text'
        data_object = _get_string_data_object(text)
        path = []
        root.add_data_object(path, data_object)
        with self.assertRaises(RootDataAlreadyExistsError):
            root.add_data_object(path, data_object)
        
    def testAddBranchTwice(self):
        root = DataTreeNode.objects.create(degree=2)
        branch1 = root.add_branch(1, 1)
        branch2 = root.add_branch(1, 1)
        self.assertEqual(branch1.id, branch2.id)

    def testAddBranchOverLeaf(self):
        root = DataTreeNode.objects.create(degree=2)
        data_object = _get_string_data_object('text')
        root.add_leaf(1, data_object)
        with self.assertRaises(UnexpectedLeafNodeError):
            root.add_branch(1, 1)

    def testAddLeafOverBranch(self):
        root = DataTreeNode.objects.create(degree=2)
        data_object = _get_string_data_object('text')
        root.add_leaf(1, data_object)
        with self.assertRaises(UnexpectedLeafNodeError):
            root.add_branch(1, 1)

    def testAddLeafTwice(self):
        root = DataTreeNode.objects.create(degree=1)
        data_object = _get_string_data_object('text')
        root.add_leaf(0, data_object)
        with self.assertRaises(LeafDataAlreadyExistsError):
            root.add_leaf(0, data_object)

    def testIndexOutOfRangeError(self):
        degree = 2
        data_object = _get_string_data_object('text')
        root = DataTreeNode.objects.create(degree=degree)
        with self.assertRaises(IndexOutOfRangeError):
            root.add_leaf(degree, data_object)
        with self.assertRaises(IndexOutOfRangeError):
            root.add_leaf(-1, data_object)

    def testDegreeOutOfRangeError(self):
        data_object = _get_string_data_object('text')
        root = DataTreeNode.objects.create(degree=2)
        with self.assertRaises(DegreeOutOfRangeError):
            root.add_branch(1, -1)

    def testDegreeMismatchError(self):
        data_object = _get_string_data_object('text')
        root = DataTreeNode.objects.create(degree=2)
        root.add_branch(1, 2)
        with self.assertRaises(DegreeMismatchError):
            root.add_branch(1, 3)
        
    def testUnknownDegreeError(self):
        data_object = _get_string_data_object('text')
        root = DataTreeNode.objects.create()
        with self.assertRaises(UnknownDegreeError):
            root.add_leaf(0, data_object)
