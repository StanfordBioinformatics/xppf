from django.db import models

from .base import BaseModel
from api.models.data_objects import DataObject
from api.models.data_trees import DataTreeNode


"""
InputOutputNodes are connected to facilitate the flow of data in a workflow, e.g. from 
a WorkflowRunInput to the StepRunInput of a StepRun nested in that Workflow, or from a 
StepRunOutput to the StepRunInput of a subsequent Step.

InputOutputNode is inherited by all input/output classes that may need to handle 
data trees with height > 1 (RunRequestInput, WorkflowRunInput/Output, 
StepRunInput/Output) but not by TaskRuns, TaskRunAttempts, or TaskDefinitions since 
these only contain data as scalars or 1-dimensional arrays.
"""


class ConnectError(Exception):
    pass


class InputOutputNode(BaseModel):
    channel = models.CharField(max_length=255)
    data_root = models.ForeignKey('DataTreeNode',
                                  # related_name would cause conflicts on children
                                  null=True,
                                  blank=True)

    type = models.CharField(
        max_length=255,
        choices=DataObject.DATA_TYPE_CHOICES)

    @property
    def data(self):
        # Dummy attribute required by serializers.
        # DataTreeNodeSerializer is needed to render this field.
        # We don't implement that as a model method here to avoid
        # circular dependencies between models and serializers.
        # To access data directly use the data_root field instead.
        return

    def get_data_as_scalar(self):
        # This function is a temporary patch to run without parallel
        # workflows enabled.
        if not self.data_root:
            return None
        return self.data_root.data_object

    def add_data_as_scalar(self, data_object):
        self.add_data_object([], data_object)

    def has_scalar(self):
        return self.data_root.has_data_object([])

    def get_data_object(self, path):
        # Get the data object at the given path.
        return self.data_root.get_data_object(path)

    def _initialize_data_root(self):
        self.data_root = DataTreeNode.objects.create()
        self.data_root.root_node = self.data_root
        self.data_root.save()
        self.save()

    def add_data_object(self, path, data_object):
        # 'path' is a list of (index, degree) pairs that define a path from root to
        # leaf. For example, in this data
        # '[["file1.txt@id1", "file2.txt@id2"], ["file3.txt@id3", "file4.txt@id4"]]'
        # the path [(0, 2),(1, 2)], corresponds with the first (index 0) of 2 branches,
        # and the second of 2 leaves on that branch, i.e. 'file2.txt@id2'.
        # If path is length 0, data is assumed to be scalar
        if self.data_root is None:
            self._initialize_data_root()
        self.data_root.add_data_object(path, data_object)

    def is_connected(self, connected_node):
        if self.data_root is None or connected_node.data_root is None:
            return False
        return self.data_root.id == connected_node.data_root.id

    def connect(self, connected_node):
        # Nodes that share the same data should be connected,
        # e.g. a StepOutput that feeds into the StepInput of a subsequent step.

        if self.is_connected(connected_node):
            return

        # Both nodes are already initialized
        if connected_node.data_root is not None and self.data_root is not None:
            raise ConnectError('Failed to connect because nodes are already '\
                               'initialized with non-matching data')

        # If neither is initialized, initialize and connect
        if connected_node.data_root is None and self.data_root is None:
            connected_node._initialize_data_root()
            self.data_root = connected_node.data_root
            self.save()

        # If one is initialized, connect the other
        if self.data_root is None:
            self.data_root = connected_node.data_root
            self.save()
        elif connected_node.data_root is None:
            connected_node.data_root = self.data_root
            connected_node.save()

    class Meta:
        abstract = True
        app_label = 'api'
