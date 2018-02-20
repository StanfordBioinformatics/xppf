from django.core.exceptions import ObjectDoesNotExist
from django.db import models
import rest_framework.serializers


def strip_empty_values(data):
    return dict((k, v) for k, v in data.iteritems() if v not in [None, '', []])

def match_and_update_by_uuid(unsaved_models, field, saved_models):
    for unsaved_model in unsaved_models:
        uuid = getattr(unsaved_model, field).uuid
        match = filter(lambda m: m.uuid==uuid, saved_models)
        assert len(match) == 1
        setattr(unsaved_model, field, match[0])
    return unsaved_models

def reload_models(ModelClass, models):
    # bulk_create doesn't give PK's, so we have to reload the models.
    # We can look them up by uuid, which is also unique
    uuids = [model.uuid for model in models]
    models = ModelClass.objects.filter(uuid__in=uuids)
    return models

def flatten_nodes(node, children_fieldname, node_list=None):
    if node_list == None:
        node_list = []
    node_list.append(node)
    for child in getattr(node, children_fieldname).all():
        flatten_nodes(child, children_fieldname, node_list)
    return node_list

def replace_nodes(instance, nodes, children_fieldname, one_to_x_fields=None):
    uuid = instance.uuid
    matches = filter(lambda n: n.uuid==uuid, nodes)
    assert len(matches) == 1, 'no unique match found'
    instance._prefetched_objects_cache.update(matches[0]._prefetched_objects_cache)
    if one_to_x_fields:
        for field in one_to_x_fields:
            if hasattr(instance, field):
                setattr(instance, field, getattr(matches[0], field))
    for child in getattr(instance, children_fieldname).all():
        replace_nodes(child, nodes, children_fieldname, one_to_x_fields)
    return instance


class RecursiveField(rest_framework.serializers.Serializer):

    def to_representation(self, value):
        serializer = self.parent.parent.__class__(value, context=self.context)
        return serializer.data


class CreateWithParentModelSerializer(
        rest_framework.serializers.HyperlinkedModelSerializer):
    """Use this when a child has a required ForeignKey or OneToOne pointer 
    to the parent such that the parent has to be saved before creating 
    the child.

    Make sure this Mixin is listed before other inherited serializers
    so that the create method will override.
    """

    def create(self, validated_data):
        """ This is a standard method called indirectly by calling
        'save' on the serializer.

        This method expects the 'parent_field' and 'parent_instance' to
        be included in the Serializer context.
        """
        if self.context.get('parent_field') \
            and self.context.get('parent_instance'):
            validated_data.update({
                self.context.get('parent_field'):
                self.context.get('parent_instance')})
        instance = self.Meta.model(**validated_data)
        instance.full_clean()
        instance.save()
        return instance


from .data_objects import *
from .data_nodes import *
from .labels import *
from .runs import *
from .tags import *
from .task_attempts import *
from .tasks import *
from .templates import *
from .users import *
