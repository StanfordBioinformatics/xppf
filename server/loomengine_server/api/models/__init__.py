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
