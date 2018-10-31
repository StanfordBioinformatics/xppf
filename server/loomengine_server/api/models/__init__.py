from collections import OrderedDict, defaultdict
import hashlib
import json
import jinja2
import uuid
import loomengine_utils.md5calc

def uuidstr():
    return str(uuid.uuid4())

def render_from_template(raw_text, context):
    if not raw_text:
	return ''
    loader = jinja2.DictLoader({'template': raw_text})
    env = jinja2.Environment(loader=loader, undefined=jinja2.StrictUndefined)
    template = env.get_template('template')
    return template.render(**context)

def render_string_or_list(value, context):
    if isinstance(value, list):
	return [render_from_template(member, context)
		for member in value]
    else:
        return render_from_template(value, context)

def calculate_contents_fingerprint(contents):
    if isinstance(contents, dict):
        # Sort keys
        contents_string = json.dumps(
            OrderedDict([(key, calculate_contents_fingerprint(value))
                         for key, value in contents.items()]),
            sort_keys=True,
            separators=(',',':'))
    elif isinstance(contents, list):
        # Sort lexicographically by hash
        contents_string = json.dumps(
            sorted([calculate_contents_fingerprint(item)
                    for item in contents]),
            separators=(',',':'))
    else:
        contents_string = str(contents)
    return hashlib.md5(contents_string).hexdigest()

def flatten_nodes(node, children_fieldname, node_list=None):
    # Converts a tree to a flat list of nodes
    # Returns new list of nodes or appends to existing node_list
    if node_list == None:
        node_list = []
    node_list.append(node)
    for child in getattr(node, children_fieldname).all():
        flatten_nodes(child, children_fieldname, node_list)
    return node_list

def copy_prefetch(
        source_nodes, dest_nodes,
        child_field=None, one_to_x_fields=None):
    # Move prefetch data from source_nodes to dest_nodes.
    # Since prefetch data for one-to-x relationships are not
    # included in _prefetched_objects_cache, specify these separately
    # as a list of field names.
    # If child_field is given, traverse the tree and copy prefetch
    # data to children.
    for instance in dest_nodes:
        uuid = instance.uuid
        matches = filter(lambda n: n.uuid==uuid, source_nodes)
        assert len(matches) == 1, 'no unique match found'
        if hasattr(matches[0], '_prefetched_objects_cache'):
            if not hasattr(instance, '_prefetched_objects_cache'):
                instance._prefetched_objects_cache = {}
            instance._prefetched_objects_cache.update(
                matches[0]._prefetched_objects_cache)
        if one_to_x_fields:
            for field in one_to_x_fields:
                setattr(instance, field, getattr(matches[0], field))
        if child_field:
            children = [child for child in getattr(instance, child_field).all()]
            copy_prefetch(source_nodes, children, child_field=child_field,
                          one_to_x_fields=one_to_x_fields)


class ArrayInputContext(object):
    """This class is used with jinja templates to make the 
    default representation of an array a space-delimited list.
    """

    def __init__(self, items, type):
        if type == 'file':
            self.items = self._rename_duplicates(items)
        else:
            self.items = items

    def _rename_duplicates(self, filenames):

        # Identify filenames that are unique
        seen = set()
        duplicates = set()
        for filename in filenames:
            if filename in seen:
                duplicates.add(filename)
            seen.add(filename)

        new_filenames = []
        filename_counts = {}
        for filename in filenames:
            if filename in duplicates:
                counter = filename_counts.setdefault(filename, 0)
                filename_counts[filename] += 1
                filename = self._add_counter_suffix(filename, counter)
            new_filenames.append(filename)
        return new_filenames

    def _add_counter_suffix(self, filename, count):
        # Add suffix while preserving file extension:
        #   myfile -> myfile.__1__
        #   myfile.txt --> myfile__1__.txt
        #   my.file.txt --> my.file__1__.txt
        parts = filename.split('.')
        assert len(parts) > 0, 'missing filename'
        if len(parts) == 1:
            return parts[0] + '__%s__' % count
        else:
            return '.'.join(parts[0:len(parts)-1]) + '__%s__.' % count + parts[-1]

    def __iter__(self):
        return self.items.__iter__()

    def __getitem__(self, i):
        return self.items[i]

    def __str__(self):
        return ' '.join([str(item) for item in self.items])

class DummyContext(str):
    """This class is used to create dummy context values used to validate 
    jinja templates during Template validation, before actual context values 
    are known. It acts as both a string and a list and attempts to avoid 
    raising any errors for usage that could be valid for some
    particular string or list.
    """

    def __init__(self, *args, **kwargs):
        super(DummyContext, self).__init__(self, *args, **kwargs)
        string = args[0]
        self.items = [letter for letter in string]

    def __iter__(self, *args, **kwargs):
        return self.items.__iter__(*args, **kwargs)

    def __len__(self,*args,**kwargs):
        return self.items.__len__(*args, **kwargs)

    def __getitem__(self, i):
        return 'x'

    def append(self, *args, **kwargs):
        return self.items.append(*args, **kwargs)

    def count(self, *args, **kwargs):
        return self.items.count(*args, **kwargs)

    def extend(self, *args, **kwargs):
        return self.items.extend(*args, **kwargs)

    def index(self, *args, **kwargs):
        return self.items.index(*args, **kwargs)

    def insert(self, *args, **kwargs):
        return self.items.insert(*args, **kwargs)

    def pop(self, *args, **kwargs):
        return self.items.pop(*args, **kwargs)

    def remove(self, *args, **kwargs):
        return self.items.remove(*args, **kwargs)

    def reverse(self, *args, **kwargs):
        return self.items.reverse(*args, **kwargs)

    def sort(self, *args, **kwargs):
        return self.items.sort(*args, **kwargs)

class positiveIntegerDefaultDict(defaultdict):
    def __getitem__(self, i):
        if not int(i) == i:
            raise ValidationError(
                'Index must be an integer. Invalid value "%s"' % i)
        if i < 1:
            raise ValidationError(
                'Index must be an integer greater than 0. '
                'Invalid value "%s"' % i)
        return super(positiveIntegerDefaultDict, self).__getitem__(i)

from .data_objects import *
from .data_nodes import *
from .labels import *
from .runs import *
from .tags import *
from .task_attempts import *
from .tasks import *
from .templates import *
