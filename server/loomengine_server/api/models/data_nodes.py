import copy
import json
from django.core.exceptions import ObjectDoesNotExist
import django.db
from django.db import models

from . import calculate_contents_fingerprint, flatten_nodes, \
    copy_prefetch
from .base import BaseModel
from .data_objects import DataObject
from api import get_setting, reload_models, connect_data_nodes_to_parents
from api.models import uuidstr
from api.models import validators


"""DataNodes allow DataObjects to be organized into trees.

This is useful in two contexts:

1. To define an array of data as input or output to an
analysis step

2. To organize data produced by parallel analysis. By organizing
data into a tree instead of an array, it is possible to nest
parallel workflows to create scatter-scatter-gather-gather patterns.

Trees of DataNodes may be cloned without duplicating the underlying
DataObjects
"""


class IndexOutOfRangeError(Exception):
    pass
class DegreeMismatchError(Exception):
    pass
class UnknownDegreeError(Exception):
    pass
class NodeAlreadyExistsError(Exception):
    pass
class DataAlreadyExistsError(Exception):
    pass
class UnexpectedLeafNodeError(Exception):
    pass
class MissingBranchError(Exception):
    pass
class DataOnNonLeafError(Exception):
    pass
class DegreeMismatchException(Exception):
    pass


class DataNode(BaseModel):

    uuid = models.CharField(default=uuidstr,
                            unique=True, max_length=255)
    tree_id = models.CharField(default=uuidstr, max_length=255)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        db_index=True,
        related_name = 'children',
        on_delete=models.CASCADE)
    # 0 <= index < self.parent.degree; null if no parent
    index = models.IntegerField(null=True, blank=True)
    # degree is expected number of children; null if leaf, 0 if empty branch
    degree = models.IntegerField(null=True, blank=True,
                                 validators=[validators.validate_ge0])
    data_object = models.ForeignKey('DataObject',
                                    related_name = 'data_nodes',
                                    null=True, # null except on leaves
                                    blank=True,
                                    on_delete=models.PROTECT)
    type = models.CharField(
        max_length=255,
        choices=DataObject.DATA_TYPE_CHOICES)

    EMPTY_BRANCH_VALUE = []

    def save(self, *args, **kwargs):
        if self.parent:
            self.tree_id = self.parent.tree_id
        super(DataNode, self).save(*args, **kwargs)

    @property
    def contents(self):
        # Dummy placeholder for serializer
        pass

    def get_children(self):
        if hasattr(self, '_cached_children'):
            children = self._cached_children
        else:
            children = self.children.all()
        return sorted(children, key=lambda n: n.index)

    def _add_unsaved_child(self, child):
        child.tree_id = self.tree_id
        if not hasattr(self, '_cached_children'):
            self._cached_children = []
        self._cached_children.append(child)
        
    def add_leaf(self, index, data_object, save=False):
        """Adds a new leaf node at the given index with the given data_object
        """
        assert self.type == data_object.type, 'data type mismatch'
        if self._get_child_by_index(index) is not None:
            raise NodeAlreadyExistsError(
                'Leaf data node already exists at this index')
        else:
            data_node = DataNode(
                parent=self,
                index=index,
                data_object=data_object,
                type=self.type)
            if save:
                data_node.full_clean()
                data_node.save()
            self._add_unsaved_child(data_node)
            return data_node

    def add_blank(self, index, save=False):
        if self._get_child_by_index(index):
            raise NodeAlreadyExistsError()
        data_node = DataNode(
            parent=self,
            index=index,
            type=self.type)
        if save:
            data_node.full_clean()
            data_node.save()
        self._add_unsaved_child(data_node)
        return data_node

    def add_branch(self, index, degree, save=False):
        existing_branch = self._get_branch_by_index(index, degree)
        if existing_branch is not None:
            return existing_branch
        else:
            data_node = DataNode(
                parent=self,
                index=index,
                degree=degree,
                type=self.type)
            if save:
                data_node.full_clean()
                data_node.save()
            self._add_unsaved_child(data_node)
            return data_node

    def add_data_object(self, data_path, data_object, save=False):
        # 'data_path' is a list of (index, degree) pairs
        if not data_path:
            # Set the data object on this node
            if self.data_object is not None:
                raise DataAlreadyExistsError(
                    'Failed to add new data to data node %s because '\
                    'data_node is already set' % self.uuid)
            if save:
                self.setattrs_and_save_with_retries({'data_object': data_object})
            else:
                self.data_object = data_object
        else:
            if self.degree is None:
                if save:
                    self.setattrs_and_save_with_retries({'degree': data_path[0][1]})
                else:
                    self.degree = data_path[0][1]
            data_path = copy.deepcopy(data_path)
            self._extend_to_data_path(data_path, leaf_data=data_object, save=save)

    def get_data_object(self, data_path):
        node = self.get_node(data_path)
        return node._get_value()

    def has_data_object(self, data_path):
        try:
            data_object = self.get_data_object(data_path)
        except MissingBranchError:
            return False
        return bool(data_object)

    def get_ready_data_nodes(self, seed_path, gather_depth):
        """Returns a list [(path1,data_node1),...]
        with entries only for existing nodes with DataObjects where is_ready==True.
        Missing nodes or those with non-ready or non-existing data are ignored.
        """
        try:
            seed_node = self.get_node(seed_path)
        except MissingBranchError:
            return []
        all_paths = seed_node._get_all_paths(seed_path, gather_depth)
        ready_data_nodes = []
        for path in all_paths:
            if self.is_ready(data_path=path):
                ready_data_nodes.append((path, self.get_node(path)))
        return ready_data_nodes

    def _get_all_paths(self, seed_path, gather_depth):
        if self.is_leaf:
            path = copy.copy(seed_path)
            # If depth exceeds height of tree, just gather to the tree height.
            if gather_depth > len(path):
                gather_depth = len(path)
            if gather_depth == 0:
                return [path,]
            else:
                # Truncate the last 'gather_depth' elements in path
                return [path[:-gather_depth],]
        else:
            # Recursively get paths to leaf nodes
            paths = []
            last_paths = None
            for child in self.get_children():
                path = seed_path + [(child.index, self.degree),]
                new_paths = child._get_all_paths(path, gather_depth)
                if not new_paths == last_paths:
                    # Skip duplicates, otherwise add to list
                    paths.extend(new_paths)
                    last_paths = new_paths
            # Convert to set to remove duplicates created by gathering
            return paths

    def is_ready(self, data_path=None):
        # True if all data at or below the given index is ready.
        if data_path is not None:
            # Look at the node designated by data_path to see if it is ready
            try:
                node = self.get_node(data_path)
            except MissingBranchError:
                return False
            return node.is_ready()
        else:
            if self.is_leaf:
                # A leaf node is ready if it has data and that data is ready.
                if self.data_object:
                    return self.data_object.is_ready
                else:
                    return  False
            else:
                # A branch node is ready if all its children are ready
                return all([self._is_child_ready_by_index(i)
                            for i in range(self.degree)])

    def _is_child_ready_by_index(self, index):
        # True if child of given index is ready
        child = self._get_child_by_index(index)
        if child:
            return child.is_ready()
        else:
            return False

    def get_node(self, data_path):
        # 'data_path' is a list of (index, degree) pairs
        if not data_path:
            return self
        if self._is_blank_node():
            raise MissingBranchError(
                'Node is incomplete')
        else:
            data_path = copy.deepcopy(data_path)
            (index, degree) = data_path.pop(0)
            if self.degree != degree:
                raise DegreeMismatchError()
            child = self._get_child_by_index(index)
            if child is None:
                raise MissingBranchError(
                    'Requested branch is missing')
            return child.get_node(data_path)

    def get_or_create_node(self, data_path, save=False):
        if not data_path:
            return self
        data_path = copy.deepcopy(data_path)
        return self._extend_to_data_path(data_path, save=save)

    def _get_child_by_index(self, index):
        self._check_index(index)
        # Don't use filter or get to avoid extra db query
        matches = filter(lambda c: c.index==index, self.get_children())
        assert len(matches) <= 1, "Duplicate children with the same index"
        if len(matches) == 1:
            return matches[0]
        return None

    def _get_branch_by_index(self, index, degree):
        branch = self._get_child_by_index(index)
        if branch is not None:
            if branch.is_leaf:
                raise UnexpectedLeafNodeError('Expected branch but found leaf')
            if branch.degree != degree:
                raise DegreeMismatchError(
                    'Degree of branch conflicts with a value set previously')
        return branch

    def _get_value(self):
        if self._is_empty_branch():
            return self.EMPTY_BRANCH_VALUE
        else:
            return self.data_object

    def _is_empty_branch(self):
        return self.degree==0

    def _extend_to_data_path(self, data_path, leaf_data=None, save=False):
        # 'data_path' is a list of (index, degree) pairs
        index, degree = data_path.pop(0)
        if self.degree:
            if not self.degree == degree:
                raise DegreeMismatchException()
        else:
            if save:
                self.setattrs_and_save_with_retries({'degree': degree})
            else:
                self.degree = degree
        if len(data_path) == 0:
            if leaf_data:
                return self.add_leaf(index, leaf_data, save=save)
            else:
                try:
                    return self.add_blank(index, save=save)
                except NodeAlreadyExistsError:
                    return self._get_child_by_index(index)
        child_degree = data_path[0][1]
        child = self.add_branch(index, child_degree, save=save)
        return child._extend_to_data_path(data_path, leaf_data=leaf_data, save=save)

    def _check_index(self, index):
        """Verify that the given index is consistent with the degree of the node.
        """
        if self.degree is None:
            raise UnknownDegreeError(
                'Cannot access child DataNode on a parent with degree of None. '\
                'Set the degree on the parent first.')
        if index < 0 or index >= self.degree:
            raise IndexOutOfRangeError(
                'Out of range index %s. DataNode parent has degree %s, so index '\
                'should be in the range 0 to %s' % (
                    index, self.degree, self.degree-1))

    @property
    def is_leaf(self):
        return self.degree is None

    def _is_blank_node(self):
        # Could be a leaf missing data, or a branch missing sub-nodes
        return (self.degree is None is self.data_object is None)

    def _render_as_data_object_list(self):
        if self.is_leaf:
            if self.data_object is None:
                raise Exception(
                    'Failed to render as data object array because data is missing')
            return [self.data_object]
        else:
            data_object_list = []
            for child in self.get_children():
                data_object_list += child._render_as_data_object_list()
            return data_object_list

    @property
    def substitution_value(self):
        if self.is_leaf:
            return self.data_object.substitution_value
        else:
            return [child.substitution_value for child
                    in self.get_children()]

    @property
    def downstream_run_inputs(self):
        assert not self.parent, "RunInputs are connected to the root node"
        return self.runinput_set

    def clone(self, parent=None, seed=None, save=False):
        assert not (parent and seed)

        if seed is not None:
            clone = seed
            assert clone.type == self.type, 'type mismatch'
            assert clone.degree is None, '"degree" already set on DataNode clone target'
            assert clone.data_object is None, '"data_object" already set on DataNode clone target'
            # clone.index may be set because the seed
            # might be connected to a parent.
            if save:
                clone.setattrs_and_save_with_retries({
                    'degree': self.degree,
                    'data_object': self.data_object})
            else:
                clone.degree = self.degree
                clone.data_object = self.data_object
        else:
            clone = DataNode(
                parent=parent,
                index=self.index,
                degree=self.degree,
                data_object=self.data_object,
                type=self.type)
            if save:
                clone.full_clean()
                clone.save()
            if parent:
                parent._add_unsaved_child(clone)

        for child in self.get_children():
            child.clone(parent=clone, save=save)

        return clone

    def flattened_clone(self, save=False):
        if self.is_leaf:
            return self.clone(save=save)

        leaves = self._get_leaves()

        clone = DataNode(
            degree=len(leaves),
            type=self.type)
        if save:
            clone.full_clean()
            clone.save()

        index_counter = 0
        for leaf in leaves:
            data_node = DataNode(
                parent=clone,
                index=index_counter,
                data_object=leaf.data_object,
                type=leaf.type)
            if save:
                data_node.full_clean()
                data_node.save()
            index_counter += 1
            clone._add_unsaved_child(data_node)
        return clone

    def _get_leaves(self):
        if self.is_leaf:
            return [self]

        leaves = []
        for child in self.get_children():
            leaves.extend(child._get_leaves())
        return leaves

    def calculate_contents_fingerprint(self):
        return calculate_contents_fingerprint(
            self.get_fingerprintable_contents())

    def get_fingerprintable_contents(self):
        return {'contents': self._get_fingerprintable_data_node_struct()}

    def _get_fingerprintable_data_node_struct(self):
        assert not self._is_blank_node(), 'Node not ready. No fingerprint.'
        assert not self._is_empty_branch(), 'Node not ready. No fingerprint.'
        if self.is_leaf:
            return self.data_object.get_fingerprintable_contents()
        else:
            # Passing the list to calculate_contents_fingerprint
            # does not preserve order, so we freeze the list in the correct
            # order as a string to be hashed.
            return json.dumps(
                [calculate_contents_fingerprint(
                    n._get_fingerprintable_data_node_struct())
                 for n in self.get_children()],
                separators=(',',':'))

    def prefetch(self):
        if hasattr(self, '_prefetched_objects_cache'):
            return
        self.prefetch_list([self,])

    @classmethod
    def prefetch_list(cls, instances):
        # Since we are prefetching, delete _cached_children to avoid conflicts
        for instance in instances:
            if hasattr(instance, '_cached_children'):
                del instance._cached_children
        instances = list(filter(lambda i: i is not None, instances))
        instances = list(filter(
            lambda i: not hasattr(i, '_prefetched_objects_cache'), instances))
        queryset = DataNode\
                   .objects\
                   .filter(uuid__in=[i.uuid for i in instances])
        MAXIMUM_TREE_DEPTH = get_setting('MAXIMUM_TREE_DEPTH')
        # Prefetch 'children', 'children__children', etc. up to max depth
        # This incurs 1 query per level up to actual depth.
        # No extra queries incurred if we go too deep.)
        for i in range(1, MAXIMUM_TREE_DEPTH+1):
            queryset = queryset.prefetch_related('__'.join(['children']*i))
        # Transfer prefetched children to original instances
        queried_data_nodes_1 = [node for node in queryset]
        copy_prefetch(queried_data_nodes_1, instances)
        # Flatten tree so we can simultaneously prefetch related models on all nodes
        node_list = []
        for instance in instances:
            node_list.extend(flatten_nodes(instance, 'children'))
        queryset = DataNode.objects.filter(uuid__in=[n.uuid for n in node_list])\
            .prefetch_related('data_object')\
            .prefetch_related('data_object__file_resource')
        # Transfer prefetched data to child nodes on original instances
        queried_data_nodes_2 = [data_node for data_node in queryset]
        copy_prefetch(queried_data_nodes_2, instances, child_field='children',
                      one_to_x_fields=['data_object',])

    def save_with_children(self):
        self.save_list_with_children([self,])
        self.prefetch()
        return self

    @classmethod
    def save_list_with_children(cls, root_instances):
        unsorted_data_nodes, parent_child_relationships \
            = cls._strip_parent_child_relationships(root_instances)
        unsaved_data_nodes = {}
        preexisting_data_nodes = {}
        for data_node in unsorted_data_nodes.values():
            if data_node.id is not None:
                preexisting_data_nodes[data_node.uuid] = data_node
            else:
                unsaved_data_nodes[data_node.uuid] = data_node
        bulk_data_nodes = DataNode.objects.bulk_create(unsaved_data_nodes.values())
        new_data_nodes = reload_models(DataNode, bulk_data_nodes)
        all_data_nodes = [n for n in new_data_nodes]
        all_data_nodes.extend(preexisting_data_nodes.values())
        connect_data_nodes_to_parents(all_data_nodes, parent_child_relationships)
        cls._update_degree(preexisting_data_nodes)
        cls._update_data_object(preexisting_data_nodes)
        return all_data_nodes

    @classmethod
    def _update_degree(cls, preexisting_data_nodes):
        params = []
        for node in preexisting_data_nodes.values():
            if node.degree is not None:
                params.append((node.id, node.degree))
        if params:
            case_statement = ' '.join(
                ['WHEN id="%s" THEN %s' % pair for pair in params])
            id_list = ', '.join(['%s' % pair[0] for pair in params])
            sql = 'UPDATE api_datanode SET degree= CASE %s END WHERE id IN (%s)'\
                                                   % (case_statement, id_list)
            with django.db.connection.cursor() as cursor:
                cursor.execute(sql)

    @classmethod
    def _update_data_object(cls, preexisting_data_nodes):
        params = []
        for node in preexisting_data_nodes.values():
            if node.data_object is not None:
                params.append((node.id, node.data_object.id))
        if params:
            case_statement = ' '.join(
                ['WHEN id="%s" THEN %s' % pair for pair in params])
            id_list = ', '.join(['%s' % pair[0] for pair in params])
            sql = \
                  'UPDATE api_datanode SET data_object_id= '\
                  'CASE %s END WHERE id IN (%s)'\
                  % (case_statement, id_list)
            with django.db.connection.cursor() as cursor:
                cursor.execute(sql)

    @classmethod
    def _strip_parent_child_relationships(cls, instances):
        flattened_instances = {}
        parent_child_relationships = []
        if isinstance(instances, list):
            for item in instances:
                item_instances, item_relationships \
                    = cls._strip_parent_child_relationships(item)
                flattened_instances.update(item_instances)
                parent_child_relationships.extend(item_relationships)
        else:
            parent = instances
            flattened_instances[parent.uuid] = parent
            children = parent.get_children()
            for child in children:
                child_instances, child_relationships \
                    = cls._strip_parent_child_relationships(child)
                flattened_instances.update(child_instances)
                parent_child_relationships.extend(child_relationships)
                parent_child_relationships.append((parent.uuid, child.uuid))
                child.parent = None
        return flattened_instances, parent_child_relationships
