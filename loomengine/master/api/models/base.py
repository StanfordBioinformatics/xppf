from django.db import models
import jinja2
import re

from api.exceptions import ConcurrentModificationError, SaveRetriesExceededError


def render_from_template(raw_text, context):
    loader = jinja2.DictLoader({'template': raw_text})
    env = jinja2.Environment(loader=loader, undefined=jinja2.StrictUndefined)
    template = env.get_template('template')
    return template.render(**context)


class FilterHelper(object):
    """
    Many object types are queryable by a user input string that gives name,
    uuid, and/or hash value, 
    e.g. myfile.dat, myfile.data@1ca14b82-df57-437f-b296-dfd6118132ab, 
    or myfile.dat$3c0e6b886ea83d2895fd64fd6619a99f
    This class parses those query strings and searches for matches.
    """

    def __init__(self, Model):
        self.Model = Model

    def filter_by_name_or_id_or_hash(self, query_string):
        assert self.Model.NAME_FIELD, \
            'NAME_FIELD is missing on model %s' % self.Model.__name__
        assert self.Model.HASH_FIELD, \
            'HASH_FIELD is missing on model %s' % self.Model.__name__
        ID_FIELD = 'uuid'
        filter_args = {}
        name, uuid, hash_value = self._parse_as_name_or_id_or_hash(query_string)
        if name is not None:
            filter_args[self.Model.NAME_FIELD] = name
        if hash_value is not None:
            filter_args[self.Model.HASH_FIELD+'__startswith'] = hash_value
        if uuid is not None:
            filter_args[ID_FIELD+'__startswith'] = uuid
        return self.Model.objects.filter(**filter_args)

    def filter_by_name_or_id(self, query_string):
        """Find objects that match the identifier of form {name}@{ID}, {name},
        or @{ID}, where ID may be truncated
        """
        assert self.Model.NAME_FIELD, \
            'NAME_FIELD is missing on model %s' % self.Model.__name__
        ID_FIELD = 'uuid'

        kwargs = {}
        name, uuid = self._parse_as_name_or_id(query_string)
        if name:
            kwargs[self.Model.NAME_FIELD] = name
        if uuid:
            kwargs[ID_FIELD+'__startswith'] = uuid
        return self.Model.objects.filter(**kwargs)

    def _parse_as_name_or_id_or_hash(self, query_string):
        name = None
        uuid = None
        hash_value = None

        # Name comes at the beginning and ends with $, @, or end of string
        name_match = re.match('^(?!\$|@)(.+?)($|\$|@)', query_string)
        if name_match is not None:
            name = name_match.groups()[0]
        # id starts with @ and ends with $ or end of string
        uuid_match = re.match('^.*?@(.*?)($|\$)', query_string)
        if uuid_match is not None:
            uuid = uuid_match.groups()[0]
        # hash starts with $ and ends with @ or end of string
        hash_match = re.match('^.*?\$(.*?)($|@)', query_string)
        if hash_match is not None:
            hash_value = hash_match.groups()[0]
        return name, uuid, hash_value

    def _parse_as_name_or_id(self, query_string):
        name, uuid, hash_value = self._parse_as_name_or_id_or_hash(query_string)
        if hash_value is not None:
            raise Exception('Invalid input "%s". '\
                            'Hash not accepted for models of type "%s"' %
                            (query_string, self.Model.__name__))
        return name, uuid


class _FilterMixin(object):

    NAME_FIELD = None
    HASH_FIELD = None
    ID_FIELD = None

    @classmethod
    def filter_by_name_or_id_or_hash(cls, filter_string):
        helper = FilterHelper(cls)
        return helper.filter_by_name_or_id_or_hash(filter_string)

    @classmethod
    def filter_by_name_or_id(cls, filter_string):
        helper = FilterHelper(cls)
        return helper.filter_by_name_or_id(filter_string)


class BaseModel(models.Model, _FilterMixin):

    _change = models.IntegerField(default=0)

    class Meta:
        abstract = True
        app_label = 'api'

    def save(self, *args, **kwargs):
        """
        This save method protects against two processesses concurrently modifying
        the same object. Normally the second save would silently overwrite the
        changes from the first. Instead we raise a ConcurrentModificationError.
        """
        self.full_clean() # To extend validation, use field validators and Model.clean
        cls = self.__class__
        if self.pk:
            rows = cls.objects.filter(
                pk=self.pk, _change=self._change).update(
                _change=self._change + 1)
            if not rows:
                raise ConcurrentModificationError(cls.__name__, self.pk)
            self._change += 1
        super(BaseModel, self).save(*args, **kwargs)

    def setattrs_and_save_with_retries(self, assignments, max_retries=5):
        """
        If the object is being edited by other processes,
        save may fail due to concurrent modification.
        This method recovers and retries the edit.
        
        assignments is a dict of {attribute: value}
        """
        count = 0
        obj=self
        while True:
            for attribute, value in assignments.iteritems():
                setattr(obj, attribute, value)
            try:
                obj.save()
            except ConcurrentModificationError:
                if  count >= max_retries:
                    raise SaveRetriesExceededError(
                        'Exceeded retries when saving "%s" of id "%s" '\
                        'with assigned values "%s"' %
                        (self.__class__, self.id, assignments))
                count += 1
                obj = self.__class__.objects.get(id=self.id)
                continue
            return obj
