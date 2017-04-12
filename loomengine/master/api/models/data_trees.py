from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from .base import BaseModel
from api.models.data_objects import DataObject
from api.models import uuidstr


"""
Data under each InputOutputNode is represented as a tree of DataTreeNodes. This
lets us represent multidimensional data to allow for nested scatter-gather,
e.g. scatter-scatter-gather-gather, where the layers of scatter are maintained
as distinct.
"""


class IndexOutOfRangeError(Exception):
    pass
class DegreeOutOfRangeError(Exception):
    pass
class DegreeMismatchError(Exception):
    pass
class UnknownDegreeError(Exception):
    pass
class LeafDataAlreadyExistsError(Exception):
    pass
class RootDataAlreadyExistsError(Exception):
    pass
class UnexpectedLeafNodeError(Exception):
    pass
class MissingBranchError(Exception):
    pass


class DataTreeNode(BaseModel):
    uuid = models.CharField(default=uuidstr,
                            unique=True, max_length=255)
    root_node = models.ForeignKey('DataTreeNode',
                                  null=True,
                                  blank=True,
                                  related_name='descendants',
                                  on_delete=models.SET_NULL)
    parent = models.ForeignKey(
        'DataTreeNode',
        null=True,
        blank=True,
        related_name = 'children',
        on_delete=models.PROTECT)
    # 0 <= index < self.parent.degree; null if no parent
    index = models.IntegerField(null=True, blank=True)
    # degree is expected number of children; null if leaf, 0 if empty branch
    degree = models.IntegerField(null=True, blank=True)
    data_object = models.ForeignKey('DataObject',
                                    related_name = 'data_tree_nodes',
                                    null=True, # null except on leaves
                                    blank=True)

    EMPTY_BRANCH_VALUE = []

    @classmethod
    def create_from_scalar(self, data_object):
        data_tree_node = DataTreeNode.objects.create()
        data_tree_node.root_node = data_tree_node
        data_tree_node.data_object = data_object
        data_tree_node.index = 0
        data_tree_node.save()
        return data_tree_node

    def add_leaf(self, index, data_object):
        self._check_index(index)
        existing_leaf = self._get_child_by_index(index)
        if existing_leaf is not None:
            raise LeafDataAlreadyExistsError(
                'Leaf data node already exists at this index')
        else:
            return DataTreeNode.objects.create(
                parent=self,
                root_node=self.root_node,
                index=index,
                data_object=data_object)

    def add_branch(self, index, degree):
        self._check_index(index)
        if degree < 0:
            raise DegreeOutOfRangeError(
                'Degree %s is not allowed. Degree must be >= 0' % degree)
        try:
            existing_branch = self.children.get(index=index)
        except ObjectDoesNotExist:
            existing_branch = None
        if existing_branch is not None:
            if existing_branch.data_object is not None:
                raise UnexpectedLeafNodeError('Expected branch but found leaf')
            if existing_branch.degree != degree:
                raise DegreeMismatchError(
                    'Degree of branch conflicts with a value set previously')
            return existing_branch
        else:
            return DataTreeNode.objects.create(
                parent=self,
                root_node=self.root_node,
                index=index,
                degree=degree)

    def add_data_object(self, path, data_object):
        if len(path) == 0:
            self._add_scalar_data_object(data_object)
        else:
            if self.degree is None:
                self.degree = path[0][1]
                self.save()
            self._extend_path_and_add_data_at_leaf(path, data_object)

    def get_data_object(self, path):
        node = self.get_node(path)
        return node._get_value()

    def has_data_object(self, path):
        try:
            data_object = self.get_data_object(path)
        except MissingBranchError:
            return False
        return bool(data_object)

    def get_node(self, path):
        if len(path) == 0:
            return self
        else:
            index = path.pop(0)
            self._check_index(index)
            child = self._get_child_by_index(index)
            if child is None:
                raise MissingBranchError(
                    'Requested branch is missing')
            return child.get_node(path)
        
    def _get_child_by_index(self, index):
        try:
            child = self.children.get(index=index)
        except ObjectDoesNotExist:
            child = None
        return child

    def _get_value(self):
        if self._is_missing_branch():
            raise MissingBranchError(
                'Cannot return DataObject because branch is missing')
        elif self._is_empty_branch():
            return self.EMPTY_BRANCH_VALUE
        else:
            return self.data_object

    def _add_scalar_data_object(self, data_object):
        if not self._is_missing_branch():
            raise RootDataAlreadyExistsError(
                "Failed to add scalar data since the root DataTreeNode is "\
                "already initialized")
        self.data_object = data_object
        self.save()

    def _is_missing_branch(self):
        return (self.degree is None
                and self.data_object is None)

    def _is_empty_branch(self):
        return self.degree==0

    def _extend_path_and_add_data_at_leaf(self, path, data_object):
        index, degree = path.pop(0)
        assert self.degree == degree, 'degree mismatch'
        if len(path) == 0:
            self.add_leaf(index, data_object)
            return
        child_degree = path[0][1]
        child = self.add_branch(index, child_degree)
        child._extend_path_and_add_data_at_leaf(path, data_object)

    def _check_index(self, index):
        if self.degree is None:
            raise UnknownDegreeError(
                'Cannot access child DataTreeNode on a parent with degree of None. '\
                'Set the degree on the parent first.')
        if index < 0 or index >= self.degree:
            raise IndexOutOfRangeError(
                'Out of range index %s. DataTreeNode parent has degree %s, so index '\
                'should be in the range 0 to %s' % (
                    index, self.degree, self.degree-1))

    def _is_leaf(self):
        return self.degree is None and self.data_object is not None

    def push_all(self):
        self.push_by_index(index=[])
    
    def push_by_index(self, index):
        """Notify downstream steps that data is available
        Push all data at or below given index.
        """
        if self.index is not None:
            index.append(self.index)
        if self._is_leaf():
            for input in self.root_node.stepruninput_set.all():
                input.push(index)
        else:
            for child in self.children.all():
                child.push_all(index=index)
