from collections import defaultdict
import copy
import django.core.exceptions
from jinja2.exceptions import UndefinedError
from rest_framework import serializers

from . import RecursiveField, strip_empty_values, match_and_update_by_uuid, \
    reload_models
from .data_channels import DataChannelSerializer
from api import async
from api.models import render_from_template, render_string_or_list, \
    positiveIntegerDefaultDict
from api.models.templates import Template, TemplateInput, TemplateMembership
from api.models.data_channels import DataChannel
from api.serializers import DataNodeSerializer


DEFAULT_INPUT_GROUP = 0
DEFAULT_INPUT_MODE = 'no_gather'
DEFAULT_OUTPUT_MODE = 'no_scatter'
DEFAULT_INTERPRETER = '/bin/bash -euo pipefail'

def _set_leaf_input_defaults(input):
    input.setdefault('group', DEFAULT_INPUT_GROUP)
    input.setdefault('mode', DEFAULT_INPUT_MODE)

def _set_leaf_template_defaults(data):
    # Apply defaults for certain settings if missing
    if data.get('outputs', []):
        for output in data.get('outputs', []):
            output.setdefault('mode', DEFAULT_OUTPUT_MODE)
    data.setdefault('interpreter', DEFAULT_INTERPRETER)

def _convert_template_id_to_dict(data):
    # If data is a string instead of a dict value,
    # set that as _template_id
    if isinstance(data, (str, unicode)):
        return {'_template_id': data}
    if data.get('steps'):
        data['steps'] = [_convert_template_id_to_dict(step) for step in data['steps']]
    return data


class TemplateInputSerializer(DataChannelSerializer):

    class Meta:
        model = TemplateInput
        fields = ('type', 'channel', 'as_channel', 'data', 'hint', 'mode', 'group')

    hint = serializers.CharField(required=False, allow_blank=True)
    mode = serializers.CharField(required=False, allow_blank=True)
    group = serializers.IntegerField(required=False, allow_null=True)
    # Override data to make it non-required
    data = serializers.JSONField(required=False, allow_null=True) 
    as_channel = serializers.CharField(required=False, allow_null=True)


class TemplateSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = Template
        fields = (
            'uuid',
            'url',
            '_template_id',
            'name',
            'md5',
            'datetime_created',
            'command',
            'import_comments',
            'imported_from_url',
            'timeout_hours',
            'is_leaf',
            'interpreter',
            'environment',
            'resources',
            'inputs',
            'outputs',
            'steps',
        )

    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
            view_name='template-detail',
            lookup_field='uuid')
    _template_id = serializers.CharField(write_only=True, required=False)
    name = serializers.CharField(required=False)
    datetime_created = serializers.DateTimeField(format='iso-8601', required=False)
    command = serializers.CharField(required=False)
    import_comments = serializers.CharField(required=False)
    imported_from_url = serializers.CharField(required=False)
    is_leaf = serializers.BooleanField(required=False)
    interpreter = serializers.CharField(required=False)
    environment = serializers.JSONField(required=False)
    resources = serializers.JSONField(required=False)
    inputs = TemplateInputSerializer(many=True, required=False)
    outputs  = serializers.JSONField(required=False)
    steps = RecursiveField(many=True, required=False)

    def to_representation(self, instance):
        instance.prefetch()
        return strip_empty_values(
            super(TemplateSerializer, self).to_representation(instance))

    def to_internal_value(self, data):
        """Because we allow template ID string values, where
        serializers normally expect a dict
        """
        converted_data = _convert_template_id_to_dict(data)
        return super(TemplateSerializer, self)\
            .to_internal_value(converted_data)

    def validate(self, data):
        # No validation if data is a template_ID. Only validate on create
        # to avoid an extra database hit.
        template_id = data.get('_template_id')
        if template_id:
            return data

        if data.get('uuid'):
            try:
                t = Template.objects.get(uuid=data.get('uuid'))
                self._root_template_uuid = t.uuid
                self._preexisting_templates = [t,]
                self._unsaved_templates = []
                self._unsaved_inputs = []
                self._unsaved_m2m_relationships = []
                return data
            except Template.DoesNotExist:
                pass

        # Did not find template by UUID. Create a new one.

        self._validate_template_data_fields(self.initial_data)

        # We have to use bulk_create for performance, so create all templates
        # before saving.
        # We need these to validate, and we'll cache them to reuse on create.
        self._preexisting_templates = []
        self._unsaved_templates = []
        self._unsaved_inputs = []
        self._unsaved_m2m_relationships = []        
        template_data = copy.deepcopy(self.initial_data)
        root_template = self._create_unsaved_models(
            [template_data,], self._unsaved_templates,
            self._unsaved_inputs, self._unsaved_m2m_relationships,
            self._preexisting_templates)
        self._root_template_uuid = root_template.uuid
        for model in self._unsaved_templates:
            try:
                model.full_clean()
            except django.core.exceptions.ValidationError as e:
                raise serializers.ValidationError(e.message_dict)
        self._validate_template_data(template_data, root=True)
        return data

    def _validate_template_data_fields(self, template_data):
        data_keys = template_data.keys()
        serializer_keys = self.fields.keys()
        extra_fields = filter(lambda key: key not in serializer_keys, data_keys)
        if extra_fields:
            raise serializers.ValidationError(
                'Unrecognized fields %s' % extra_fields)

    def _validate_template_data(self, data, root=False):
        self._validate_channels(data, root=root)
        self._validate_jinja_templates(data)
        for step in data.get('steps', []):
            self._validate_template_data(step)

    def _validate_jinja_templates(self, data):
        input_context = self._get_dummy_input_context(data)
        for output in data.get('outputs', []):
            if output.get('source'):
                self._validate_output_source(
                    output.get('source'), input_context)
        self._validate_command(data)

    def _validate_command(self, data):
        if not data.get('command'):
            return
        try:
            render_from_template(
                data.get('command'),
                self._get_dummy_full_context(data))
        except Exception as e:
            raise serializers.ValidationError({
                'command':
                'Error "%s" when parsing command "%s"' %
                (e, data.get('command'))})

    def _get_dummy_input_context(self, data):
        context = {}
        # Return 1 if key is a positive integer, else raise ValidationError
        context['index'] = positiveIntegerDefaultDict(lambda: 1)
        context['size'] = positiveIntegerDefaultDict(lambda: 1)
        for input in data.get('inputs', []):
            if input.get('as_channel'):
                channel = input.get('as_channel')
            else:
                channel = input.get('channel')
            context[channel] = DummyContext('value')
        return context

    def _get_dummy_output_context(self, data):
        context = {}
	for output in data.get('outputs', []):
            if output.get('as_channel'):
                channel = output.get('as_channel')
            else:
                channel = output.get('channel')
            context[channel] = DummyContext('value')
        return context

    def _get_dummy_full_context(self, data):
        context = self._get_dummy_input_context(data)
        context.update(self._get_dummy_output_context(data))
        return context

    def _validate_output_source(self, output_source, input_context):
        try:
            render_from_template(
                output_source.get('filename'), input_context)
            render_string_or_list(
                output_source.get('filenames'),
                input_context)
            render_from_template(
                output_source.get('glob'), input_context)
        except UndefinedError as e:
            raise serializers.ValidationError({
                'source':
                'Error "%s" in output source "%s"' %
                (e, output_source)})

    def _validate_channels(self, data, root=False):
        self._expand_steps(data)
        self._validate_channels_no_duplicates(data)
        self._validate_channels_no_duplicate_sources(data)
        self._validate_channels_check_duplicate_inputs(data)
        self._validate_channels_valid_source(data, root=root)
        self._validate_input_dimensions(data)
        self._validate_no_cycles(data)

    def _expand_steps(self, data):
        # In order to validate channels, we need to lookup and expand any steps
        # that are referenced as _template_id. This lets us check if child
        # input/output channel names line up with the parent.
        for i in range(len(data.get('steps', []))):
            template_id = data['steps'][i].get('_template_id')
            if template_id:
                step = self._lookup_by_id(template_id)
                data['steps'][i] = TemplateSerializer(step, context=self.context).data

    def _validate_channels_no_duplicates(self, data):
        # Same channel name should never appear twice in a step
        visited_channels = set()
        for input in data.get('inputs', [])+data.get('outputs', []):
            channel = input.get('channel')
            if channel in visited_channels:
                raise serializers.ValidationError(
                    'Duplicate channel "%s" in template "%s"'
                    % (channel, data.get('name')))
            visited_channels.add(channel)

    def _validate_channels_no_duplicate_sources(self, data):
        # Same channel should not be both input of a step
        # and output of one of its children
        visited_channels = set()
        for input in data.get('inputs', []):
            channel=input.get('channel')
            if channel in visited_channels:
                raise serializers.ValidationError(
                    'Duplicate source channel "%s" in template "%s"'
                    % (channel, data.get('name')))
            visited_channels.add(channel)
        for step in data.get('steps', []):
            for output in step.get('outputs', []):
                channel = output.get('channel')
                if channel in visited_channels:
                    raise serializers.ValidationError(
                        'Duplicate source channel "%s" in template "%s"'
                        % (channel, data.get('name')))
                visited_channels.add(channel)

    def _validate_channels_check_duplicate_inputs(self, data):
        # If two siblings have the same channel, the channel must have a source,
        # either on the parent or on a sibling's output.
        sources = set()
        for input in data.get('inputs', []):
            sources.add(input.get('channel'))
        for step in data.get('steps', []):
            for output in step.get('outputs', []):
                sources.add(output.get('channel'))
        child_inputs = set()
        for step in data.get('steps', []):
            for input in step.get('inputs', []):
                channel = input.get('channel')
                if channel in child_inputs and channel not in sources:
                    raise serializers.ValidationError(
                        'Because the input channel "%s" exists on multiple child '\
                        'steps, it must have a shared source' % channel)
                child_inputs.add(channel)

    def _validate_channels_valid_source(self, data, root=False):
        if data.get('is_leaf') or data.get('_template_id'):
            # _template_id field indicates that this is a preexisting template
            # that should already be validated. Nested children are not loaded,
            # so cannot re-validate.
            # is_leaf indicates no children, so skip this validation step.
            return

        # Every channel should have a valid data source.
        # For inputs on root node of template, source can be given at runtime.
        sources = {}
        for input in data.get('inputs', []):
            sources[input.get('channel')] = input.get('type')
        for step in data.get('steps', []):
            for output in step.get('outputs', []):
                sources[output.get('channel')] = output.get('type')

        # Every output on a non-leaf node must have a source
        for output in data.get('outputs', []):
            if output.get('channel') in sources:
                if not output.get('type') == sources[output.get('channel')]:
                    raise serializers.ValidationError(
                        'Type mismatch on channel "%s", step "%s"'
                        % (output.get('channel'), step.get('name')))
            else:
                if not output.get('data'):
                    raise serializers.ValidationError(
                        'No source for output channel "%s" on step "%s".'
                        % (output.get('channel'), data.get('name')))

        # Every input on a child node must have a source
        for step in data.get('steps', []):
            for input in step.get('inputs', []):
                if input.get('channel') in sources:
                    if not input.get('type') == sources[input.get('channel')]:
                        raise serializers.ValidationError(
                            'Type mismatch on channel "%s", step "%s"'
                            % (input.get('channel'), step.get('name')))
                else:
                    # No external source, ok if it has fixed data.
                    if not input.get('data'):
                        raise serializers.ValidationError(
                            'No source for input channel "%s" on step "%s".'
                            % (input.get('channel'), step.get('name')))

    def _validate_input_dimensions(self, data):
        # Group settings only apply to leaf
        if not data.get('is_leaf'):
            return
        
        groups = {}
        for input in data.get('inputs', []):
            group = input.get('group')
            groups.setdefault(group, [])
            groups[group].append(input)
        for (group, inputs) in groups.iteritems():
            group_dimensions = None
            for input in inputs:
                if input.get('data'):
                    contents = input.get('data').get('contents')
                    dimensions = self._get_data_dimensions(contents, [])
                    if group_dimensions is None:
                        group_dimensions = dimensions
                    else:
                        if group_dimensions != dimensions:
                            raise serializers.ValidationError(
                                'Dimensions mismatch on input data '\
                                'in group "%s", step "%s"'
                                % (group, data.get('name')))

    def _get_data_dimensions(self, contents, path):
        if not isinstance(contents, list):
            return path
        else:
            paths = []
            for item in contents:
                paths.append(self._get_data_dimensions(item, copy.deepcopy(path)))
            return paths

    def _validate_no_cycles(self, data):
        CycleDetector(data.get('steps', [])).dfs()

    def create(self, validated_data):
        # If template_id is present, just look it up
        template_id = validated_data.get('_template_id')
        if template_id:
            return self._lookup_by_id(template_id)
        try:
            bulk_templates = Template.objects.bulk_create(self._unsaved_templates)
            # self._new_templates includes pk's needed for cleanup on failure
            self._new_templates = reload_models(Template, bulk_templates)
            templates = [template for template in self._new_templates]
            templates.extend(self._preexisting_templates)

            # Refresh unsaved objects with their saved counterparts
            match_and_update_by_uuid(
                self._unsaved_inputs, 'template', templates)
            match_and_update_by_uuid(
                self._unsaved_m2m_relationships, 'parent_template', templates)
            match_and_update_by_uuid(
                self._unsaved_m2m_relationships, 'child_template', templates)

            # We can clean now that relationships have been defined.
            # Convert any model ValidationError
            # to serializer ValidationError to raise 400 http code.
            try:
                for instance in self._unsaved_inputs:
                    instance.full_clean()
                for instance in self._unsaved_m2m_relationships:
                    instance.full_clean()
            except django.core.exceptions.ValidationError as e:
                raise serializers.ValidationError(e.message_dict)

            TemplateInput.objects.bulk_create(self._unsaved_inputs)
            TemplateMembership.objects.bulk_create(self._unsaved_m2m_relationships)
                
            root_template = filter(
                lambda t: t.uuid==self._root_template_uuid, templates)
            assert len(root_template) == 1, '1 template should match uuid of root'
            return root_template[0]

        except:
            self._cleanup()
            raise

    def _cleanup(self):
        # Deleting the templates will cascade to delete
        # any TemplateInput or TemplateMembership
        if hasattr(self, '_new_templates'):
            self._new_templates.delete()

    def _lookup_by_id(self, template_id):
        matches = Template.filter_by_name_or_id_or_tag_or_hash(template_id)
        if matches.count() < 1:
            raise serializers.ValidationError(
                'No template found that matches value "%s"' % template_id)
        elif matches.count() > 1:
            match_id_list = ['%s@%s' % (match.name, match.uuid)
                             for match in matches]
            match_id_string = ('", "'.join(match_id_list))
            raise serializers.ValidationError(
                'Multiple templates were found matching value "%s": "%s". '\
                'Use a more precise identifier to select just one template.' % (
                    template_id, match_id_string))
        return matches.first()
    
    def _create_unsaved_models(
            self,
            templates_data,
            template_models,
            input_models,
            m2m_relationship_models,
            preexisting_templates,
            parent_model=None):
        for i in range(len(templates_data)):
            template_data = templates_data[i]
            template = self._handle_if_existing_template(
                template_data, preexisting_templates, m2m_relationship_models,
                parent_model=parent_model)
            if template:
                # Replace the template reference with the full
                # template structure
                templates_data[i] = TemplateSerializer(
                    template, context=self.context).data
                continue
            template = self._create_unsaved_template(
                template_data, template_models, input_models,
                m2m_relationship_models, parent_model=parent_model)
            children = template_data.get('steps', [])
            has_children = bool(children)
            if has_children:
                # recurse
                self._create_unsaved_models(
                    children,
                    template_models,
                    input_models,
                    m2m_relationship_models,
                    preexisting_templates,
                    parent_model=template)
        return template

    def _handle_if_existing_template(self, template_data, preexisting_templates,
                                     m2m_relationship_models, parent_model=None):
                                     
        existing_template = None
        # If a model already exists with this UUID, use the saved model
        if template_data.get('_template_id'):
            #if isinstance(template_data, (unicode, str)):
            # template_id is a string reference to an existing template.
            #template_id = template_data
            template_id = template_data.get('_template_id')
            # Use the serializer to retrive the instance
            serializer = TemplateSerializer(
                data=template_id)
            serializer.is_valid(raise_exception=True)
            # No new template created here, just a lookup
            existing_template = serializer.save()
        elif template_data.get('uuid'):
            try:
                existing_template = Template.objects.get(uuid=template_data.get('uuid'))
            except Template.DoesNotExist:
                pass
        if existing_template:
            self._add_unsaved_model_from_reference(
                existing_template, parent_model, preexisting_templates,
                m2m_relationship_models)
                
            return existing_template
        else:
            return None

    def _create_unsaved_template(self, template_data, template_models, input_models,
                                 m2m_relationship_models, parent_model=None):
        # template_data is a dict and does not match any existing template
        self._validate_template_data_fields(template_data)

        # Children will be processed by recursion
        has_children = bool(template_data.get('steps', []))

        self._set_template_data_defaults(template_data, has_children)

        inputs = template_data.get('inputs', [])

        template_copy = copy.deepcopy(template_data)
        template_copy.pop('steps', None)
        template_copy.pop('inputs', None)
        template_copy.pop('url', None)
        template = Template(**template_copy)
        template_models.append(template)

        for input_data in inputs:
            # create unsaved inputs
            if template.is_leaf:
                _set_leaf_input_defaults(input_data)
            input_copy = copy.deepcopy(input_data)
            input_copy['template'] = template
            data = input_copy.pop('data', None)
            if data:
                s = DataNodeSerializer(
                    data=data,
                    context={'type': input_copy.get('type')}
                )
                s.is_valid(raise_exception=True)
                input_copy['data_node'] = s.save()
            input_models.append(TemplateInput(**input_copy))
        if parent_model:
            # create unsaved link to parent
            m2m_relationship_models.append(
                TemplateMembership(
                    parent_template=parent_model,
                    child_template=template))
        return template

    def _add_unsaved_model_from_reference(
            self, template, parent_model, preexisting_templates,
            m2m_relationship_models):
        preexisting_templates.append(template)
        # Link to parent if any
        if parent_model:
            m2m_relationship_models.append(
                TemplateMembership(
                    parent_template=parent_model,
                    child_template=template)
            )
            # Do not call full_clean yet.
            # Relationships must be added first.
        return template

    def _set_template_data_defaults(self, template_data, has_children):
        if template_data.get('is_leaf') is None:
            template_data['is_leaf'] = not has_children
        if template_data['is_leaf']:
            _set_leaf_template_defaults(template_data)
        if not template_data.get('imported'):
            template_data['imported'] = bool(
                template_data.get('imported_from_url'))


class URLTemplateSerializer(TemplateSerializer):

    # readable
    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='template-detail',
        lookup_field='uuid')
    name = serializers.CharField(required=False)
    md5 = serializers.CharField(required=False)
    datetime_created = serializers.DateTimeField(
        format='iso-8601', required=False)
    is_leaf = serializers.BooleanField(required=False)

    # write-only
    _template_id = serializers.CharField(write_only=True, required=False)
    command = serializers.CharField(required=False, write_only=True)
    import_comments = serializers.CharField(required=False, write_only=True)
    imported_from_url = serializers.CharField(required=False, write_only=True)
    interpreter = serializers.CharField(required=False, write_only=True)
    environment = serializers.JSONField(required=False, write_only=True)
    resources = serializers.JSONField(required=False, write_only=True)
    inputs = TemplateInputSerializer(many=True, required=False, write_only=True)
    outputs  = serializers.JSONField(required=False, write_only=True)
    steps = RecursiveField(many=True, required=False, write_only=True)
    timeout_hours = serializers.FloatField(required=False, write_only=True)

    def to_representation(self, instance):
        return strip_empty_values(
            super(TemplateSerializer, self).to_representation(instance))


class CycleDetector(object):

    def __init__(self, steps):
        self.white = []
        self.gray = []
        self.black = []
        self.edges = {}
        self.backtrack = {}
        for step in steps:
            if step['name'] in self.white:
                raise serializers.ValidationError(
                    'Duplicate step was found: "%s"' % step['name'])
            self.white.append(step['name'])
            self.edges.setdefault(step['name'], [])
        for step in steps:
            for output in step.get('outputs', []):
                channel = output['channel']
                for dest in steps:
                    for input in dest.get('inputs', []):
                        if input.get('channel') == channel:
                            self.edges[step['name']].append(dest['name'])

    def dfs(self):
        while self.white:
            self._visit(self.white[0], None)

    def _visit(self, vertex, sender):
        if vertex in self.white:
            self.white.remove(vertex)
            self.gray.append(vertex)
            self.backtrack[vertex] = sender
            for neighbor in self.edges[vertex]:
                self._visit(neighbor, vertex)
            self.gray.remove(vertex)
            self.black.append(vertex)
        elif vertex in self.gray:
            # cycle detected
            cycle_steps = [vertex]
            next_step = sender
            while next_step != vertex and next_step != None:
                cycle_steps.append(next_step)
                next_step = self.backtrack[next_step]
            raise serializers.ValidationError(
                'Cycle detected in steps "%s"' % '", "'.join(cycle_steps))
        elif vertex in self.black:
            return


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
