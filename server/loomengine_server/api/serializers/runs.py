import copy
from rest_framework import serializers
import django.db
from . import CreateWithParentModelSerializer, RecursiveField, strip_empty_values
from api import get_setting, connect_data_nodes_to_parents, \
    match_and_update_by_uuid, reload_models
from api.models.data_nodes import DataNode
from api.models.data_objects import DataObject
from api.models.runs import Run, UserInput, RunInput, RunOutput, RunEvent
from api.models.tasks import Task, TaskInput, TaskOutput, TaskEvent
from api.models.task_attempts import TaskAttempt, TaskAttemptInput, TaskAttemptOutput, \
    TaskAttemptEvent, TaskAttemptLogFile, TaskMembership
from api.models.templates import Template
from api.serializers.templates import TemplateSerializer, URLTemplateSerializer
from api.serializers.tasks import TaskSerializer, URLTaskSerializer
from api.serializers.data_channels import DataChannelSerializer
from api import async


class UserInputSerializer(DataChannelSerializer):

    # type not required because it is inferred from template
    type = serializers.CharField(required=False)

    class Meta:
        model = UserInput
        fields = ('type', 'channel', 'data')


class RunInputSerializer(DataChannelSerializer):

    class Meta:
        model = RunInput
        fields = ('type', 'channel', 'as_channel', 'data', 'mode', 'group')

    mode = serializers.CharField(required=False)
    group = serializers.IntegerField(required=False)
    as_channel = serializers.CharField(required=False)

    def to_representation(self, instance):
        return strip_empty_values(
            super(RunInputSerializer, self).to_representation(instance))


class RunOutputSerializer(DataChannelSerializer):

    class Meta:
        model = RunOutput
        fields = ('type', 'channel', 'as_channel', 'data',
                  'mode', 'source', 'parser')

    mode = serializers.CharField(required=False)
    source = serializers.JSONField(required=False)
    parser = serializers.JSONField(required=False)
    as_channel = serializers.CharField(required=False)

    def to_representation(self, instance):
        return strip_empty_values(
            super(RunOutputSerializer, self).to_representation(instance))


class RunEventSerializer(CreateWithParentModelSerializer):

    class Meta:
        model = RunEvent
        fields = ('event', 'detail', 'timestamp', 'is_error')


class RunSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = Run
	fields = [
            'uuid',
            'url',
            'name',
            'status',
            'datetime_created',
            'datetime_finished',
            'template',
            'postprocessing_status',
            'status_is_finished',
            'status_is_failed',
            'status_is_killed',
            'status_is_running',
            'status_is_waiting',
            'is_leaf',
            'command',
            'interpreter',
            'environment',
            'resources',
            'notification_addresses',
            'notification_context',
            'user_inputs',
            'inputs',
            'outputs',
            'events',
            'steps',
            'tasks',
            'force_rerun',
            'timeout_hours',
        ]

    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='run-detail',
        lookup_field='uuid')
    name = serializers.CharField(required=False)
    datetime_created = serializers.DateTimeField(
        required=False, format='iso-8601')
    datetime_finished = serializers.DateTimeField(
        required=False, format='iso-8601')
    template = URLTemplateSerializer(required=False)
    postprocessing_status = serializers.CharField(required=False)
    status = serializers.CharField(read_only=True)
    status_is_finished = serializers.BooleanField(required=False)
    status_is_failed = serializers.BooleanField(required=False)
    status_is_killed = serializers.BooleanField(required=False)
    status_is_running = serializers.BooleanField(required=False)
    status_is_waiting = serializers.BooleanField(required=False)
    is_leaf = serializers.BooleanField(required=False)
    command = serializers.CharField(required=False,
                                    allow_null=True, allow_blank=True)
    interpreter = serializers.CharField(required=False,
                                        allow_null=True, allow_blank=True)
    environment = serializers.JSONField(required=False, allow_null=True)
    resources = serializers.JSONField(required=False, allow_null=True)
    notification_addresses = serializers.JSONField(
        required=False, allow_null=True)
    notification_context = serializers.JSONField(
        required=False, allow_null=True)
    user_inputs = UserInputSerializer(many=True, required=False)
    inputs = RunInputSerializer(many=True, required=False)
    outputs = RunOutputSerializer(many=True, required=False)
    events = RunEventSerializer(many=True, required=False)
    steps = RecursiveField(many=True, required=False)
    tasks = TaskSerializer(many=True, required=False)
    timeout_hours = serializers.FloatField(required=False, write_only=False)
    force_rerun = serializers.BooleanField(required=False, write_only=True)

    def to_representation(self, instance):
        instance.prefetch()
        return strip_empty_values(
            super(RunSerializer, self).to_representation(instance))

    def validate(self, data):
        run_data = copy.deepcopy(self.initial_data)
        self._unsaved_object_manager = UnsavedObjectManager(
            self.context, self.fields.keys())

        template = self._lookup_template(run_data.get('template'))
        template.prefetch()

        self._unsaved_object_manager.create_unsaved_run(
            template, run_data=run_data)

        return run_data

    def validate_user_inputs(self, value):
        channels = set()
        for item in value:
            if item.get('channel') in channels:
                raise serializers.ValidationError(
                    'Found duplicate of channel "%s"' % item.get('channel'))
            channels.add(item.get('channel'))
        return value

    def _lookup_template(self, template_data):
        # This method should retrieve a template, given either a dict with a UUID
        # or a string/unicode reference. It should never save a new template.
        # This is expected to be called only once and should complete in a small,
        # finite number of db queries.
        try:
            template_data.get('uuid')
            try:
                return Template.objects.get(uuid=template_data.get('uuid'))
            except Template.DoesNotExist:
                raise serializers.ValidationError(
                    'No template found with UUID "%s"'
                    % template_data.get('uuid'))
        except AttributeError:
            pass

        # Not an object. Treat as a string reference.
        if not isinstance(template_data, (str, unicode)):
            raise serializers.ValidationError(
                'Invalid template. Expcted object or string but found "%s"'
                % template_data)

        matches = Template.filter_by_name_or_id_or_tag_or_hash(template_data)
        if len(matches) == 0:
            raise serializers.ValidationError(
                'No template found for identifier "%s"' % template_data)
        elif len(matches) > 1:
            raise serializers.ValidationError(
                'More than one template matched identifier "%s"' % template_data)
        else:
            return matches[0]

    def create(self, instance):
        try:
            run = self._unsaved_object_manager.bulk_create_all()
        except Exception:
            # Cleanup for ValidationError or any unexpected errors
            self._unsaved_object_manager.cleanup()
            raise

        async.execute(async.postprocess_run, run.uuid)
        return run


class URLRunSerializer(RunSerializer):

    # readable fields
    uuid = serializers.UUIDField(required=False)
    url = serializers.HyperlinkedIdentityField(
        view_name='run-detail',
        lookup_field='uuid')
    name = serializers.CharField(required=False)
    datetime_created = serializers.DateTimeField(
        required=False, format='iso-8601')
    datetime_finished = serializers.DateTimeField(
        required=False, format='iso-8601')
    status = serializers.CharField(read_only=True)
    is_leaf = serializers.BooleanField(required=False)

    # write-only fields
    template = URLTemplateSerializer(required=False, write_only=True)
    postprocessing_status = serializers.CharField(required=False, write_only=True)
    status_is_finished = serializers.BooleanField(required=False, write_only=True)
    status_is_failed = serializers.BooleanField(required=False, write_only=True)
    status_is_killed = serializers.BooleanField(required=False, write_only=True)
    status_is_running = serializers.BooleanField(required=False, write_only=True)
    status_is_waiting = serializers.BooleanField(required=False, write_only=True)
    command = serializers.CharField(required=False, write_only=True)
    interpreter = serializers.CharField(required=False, write_only=True)
    environment = serializers.JSONField(required=False, write_only=True)
    resources = serializers.JSONField(required=False, write_only=True)
    notification_addresses = serializers.JSONField(
        required=False, write_only=True, allow_null=True)
    notification_context = serializers.JSONField(
        required=False, write_only=True, allow_null=True)
    user_inputs = UserInputSerializer(
        many=True, required=False, write_only=True)
    inputs = RunInputSerializer(many=True, required=False, write_only=True)
    outputs = RunOutputSerializer(many=True, required=False, write_only=True)
    events = RunEventSerializer(many=True, required=False, write_only=True)
    steps = RecursiveField(many=True, required=False, write_only=True)
    tasks = TaskSerializer(many=True, required=False, write_only=True)
    timeout_hours = serializers.FloatField(required=False, write_only=True)
    force_rerun = serializers.BooleanField(required=False, write_only=True)

    def to_representation(self, instance):
        return strip_empty_values(
            super(RunSerializer, self).to_representation(instance))

class UnsavedObjectManager(object):

    def __init__(self, serializer_context, serializer_fields):
        self._serializer_context = serializer_context
        self._serializer_fields = serializer_fields

        # For all models related to the imported run, we check to see if they
        # already exist in the database, then sort them to 
        # _preexisting_* and _unsaved_* before calling bulk_create.
        self._preexisting_runs = {}
        self._preexisting_data_objects = {}
        self._preexisting_data_nodes = {}
        self._preexisting_task_attempts = {}
        self._unsaved_runs = {}
        self._unsaved_run_events = []
        self._unsaved_run_outputs = []
        self._unsaved_run_inputs = []
        self._unsaved_run_user_inputs = []
        self._unsaved_data_objects = {}
        self._unsaved_data_nodes = {}
        self._unsaved_root_data_nodes = {}
        self._unsaved_tasks = []
        self._unsaved_task_inputs = []
        self._unsaved_task_outputs = []
        self._unsaved_task_events = []
        self._unsaved_task_attempts = {}
        self._unsaved_task_attempt_inputs = []
        self._unsaved_task_attempt_outputs = []
        self._unsaved_task_attempt_events = []
        self._unsaved_task_attempt_log_files = []
        self._unsaved_task_to_all_task_attempts_m2m_relationships = []

        # Certain relationships that can be created only by editing models
        # after bulk_create saves them
        self._task_to_task_attempt_relationships = []
        self._run_parent_child_relationships = []
        self._data_node_parent_child_relationships = []

        # Since we have to reload objects after bulk_create,
        # remember which run is the root
        self._root_run_uuid = None

    def bulk_create_all(self):
        bulk_data_objects = DataObject.objects.bulk_create(
            self._unsaved_data_objects.values())
        self._new_data_objects = reload_models(DataObject, bulk_data_objects)
        all_data_objects = [data_object for data_object in self._new_data_objects]
        all_data_objects.extend(self._preexisting_data_objects.values())

        match_and_update_by_uuid(
            self._unsaved_data_nodes.values(), 'data_object', all_data_objects)
        bulk_data_nodes = DataNode.objects.bulk_create(
            self._unsaved_data_nodes.values())
        self._new_data_nodes = reload_models(DataNode, bulk_data_nodes)
        all_data_nodes = [data_node for data_node in self._new_data_nodes]
        all_data_nodes.extend(self._preexisting_data_nodes.values())

        connect_data_nodes_to_parents(
            self._new_data_nodes, self._data_node_parent_child_relationships)

        bulk_runs = Run.objects.bulk_create(self._unsaved_runs.values())
        self._new_runs = reload_models(Run, bulk_runs)
        all_runs = [run for run in self._new_runs]
        all_runs.extend(self._preexisting_runs.values())

        match_and_update_by_uuid(
            self._unsaved_run_inputs, 'run', self._new_runs)
        match_and_update_by_uuid(
            self._unsaved_run_inputs, 'data_node', all_data_nodes)
        RunInput.objects.bulk_create(self._unsaved_run_inputs)

        match_and_update_by_uuid(
            self._unsaved_run_outputs, 'run', self._new_runs)
        match_and_update_by_uuid(
            self._unsaved_run_outputs, 'data_node', all_data_nodes)
        RunOutput.objects.bulk_create(self._unsaved_run_outputs)

        match_and_update_by_uuid(self._unsaved_run_user_inputs,
                                 'run', self._new_runs)
        match_and_update_by_uuid(
            self._unsaved_run_user_inputs, 'data_node', all_data_nodes)
        UserInput.objects.bulk_create(self._unsaved_run_user_inputs)

        match_and_update_by_uuid(
            self._unsaved_run_events, 'run', self._new_runs)
        RunEvent.objects.bulk_create(self._unsaved_run_events)

        match_and_update_by_uuid(
            self._unsaved_tasks, 'run', self._new_runs)
        bulk_tasks = Task.objects.bulk_create(self._unsaved_tasks)
        self._new_tasks = reload_models(Task, bulk_tasks)

        match_and_update_by_uuid(
            self._unsaved_task_inputs, 'task', self._new_tasks)
        match_and_update_by_uuid(
            self._unsaved_task_inputs, 'data_node', all_data_nodes)
        TaskInput.objects.bulk_create(self._unsaved_task_inputs)

        match_and_update_by_uuid(self._unsaved_task_outputs,
                                 'task', self._new_tasks)
        match_and_update_by_uuid(
            self._unsaved_task_outputs, 'data_node', all_data_nodes)
        TaskOutput.objects.bulk_create(self._unsaved_task_outputs)

        match_and_update_by_uuid(self._unsaved_task_events,
                                 'task', self._new_tasks)
        TaskEvent.objects.bulk_create(self._unsaved_task_events)

        bulk_attempts = TaskAttempt.objects.bulk_create(
            self._unsaved_task_attempts.values())
        self._new_task_attempts = reload_models(TaskAttempt, bulk_attempts)
        all_task_attempts = [task_attempt for task_attempt
                             in self._new_task_attempts]
        all_task_attempts.extend(self._preexisting_task_attempts.values())
        match_and_update_by_uuid(self._unsaved_task_attempt_inputs,
                                 'task_attempt', self._new_task_attempts)

        match_and_update_by_uuid(
            self._unsaved_task_attempt_inputs, 'data_node', all_data_nodes)
        TaskAttemptInput.objects.bulk_create(
            self._unsaved_task_attempt_inputs)

        match_and_update_by_uuid(self._unsaved_task_attempt_outputs,
                                 'task_attempt',self._new_task_attempts)
        match_and_update_by_uuid(
            self._unsaved_task_attempt_outputs, 'data_node', all_data_nodes)
        TaskAttemptOutput.objects.bulk_create(
            self._unsaved_task_attempt_outputs)

        match_and_update_by_uuid(self._unsaved_task_attempt_events,
                                 'task_attempt', self._new_task_attempts)
        TaskAttemptEvent.objects.bulk_create(
            self._unsaved_task_attempt_events)

        match_and_update_by_uuid(self._unsaved_task_attempt_log_files,
                                 'data_object', all_data_objects)
        match_and_update_by_uuid(self._unsaved_task_attempt_log_files,
                                 'task_attempt', self._new_task_attempts)
        TaskAttemptLogFile.objects.bulk_create(self._unsaved_task_attempt_log_files)

        self._connect_tasks_to_active_task_attempts(
            self._new_tasks, all_task_attempts)

        match_and_update_by_uuid(
            self._unsaved_task_to_all_task_attempts_m2m_relationships,
            'parent_task', self._new_tasks)
        match_and_update_by_uuid(
            self._unsaved_task_to_all_task_attempts_m2m_relationships,
            'child_task_attempt', all_task_attempts)
        TaskMembership.objects.bulk_create(
            self._unsaved_task_to_all_task_attempts_m2m_relationships)

        self._connect_runs_to_parents(all_runs)

        # Reload
        matches = filter(
            lambda r: r.uuid==self._root_run_uuid, all_runs)
        assert len(matches) == 1, '1 run should match uuid of root'
        return matches[0]

    def create_unsaved_run(self, template, run_data=None, parent=None):
        # In case we are building a run from template only,
        # initialize a blank run_data dict
        if run_data is None:
            run_data = {}

        self._validate_run_data_fields(run_data)

        run_data['template'] = template

        # Pop read-only values
        run_data.pop('url', None)
        run_data.pop('status', None)

        # Set values not given in run_data
        default_timeout_hours = template.timeout_hours
        if default_timeout_hours is None and parent is not None:
            default_timeout_hours = parent.timeout_hours
        run_data.setdefault('timeout_hours', default_timeout_hours)

        run_data['notification_context'] = self._get_notification_context()

        force_rerun_default = False
        if parent:
            force_rerun_default = parent.force_rerun
        run_data.setdefault('force_rerun', force_rerun_default)

        run_data.setdefault('name', template.name)
        run_data.setdefault('is_leaf', template.is_leaf)
        run_data.setdefault('command', template.command)
        run_data.setdefault('interpreter', template.interpreter)
        run_data.setdefault('environment', template.environment)
        run_data.setdefault('resources', template.resources)
        
        # Pop related objects to be handled separately
        steps = run_data.pop('steps', [])
        inputs = run_data.pop('inputs', [])
        user_inputs = run_data.pop('user_inputs', [])
        outputs = run_data.pop('outputs', [])
        tasks = run_data.pop('tasks', [])
        events = run_data.pop('events', [])

        run = Run(**run_data)

        if parent:
            run._cached_parent = parent
        else:
            run._cached_parent = None

        run._cached_tasks = []
        for task in tasks:
            run._cached_tasks.append(
                self._create_unsaved_task(task, run))

        run._cached_events = []
        for event in events:
            event['run'] = run
            run._cached_events.append(RunEvent(**event))

        run._cached_user_inputs = []
        for user_input_data in user_inputs:
            matches = filter(
                lambda i: i.channel==user_input_data.get('channel'),
                template.inputs.all())
            if len(matches) != 1:
                raise serializers.ValidationError(
                    'User input channel "%s" does not match any template inputs'
                    % user_input_data.get('channel'))
            template_input = matches[0]
            user_input_data['run'] = run
            user_input_data['type'] = template_input.type
            data = user_input_data.pop('data', None)
            user_input_data['data_node'] = self._create_unsaved_data_node(
                data, template_input.type)
            user_input = UserInput(**user_input_data)
            run._cached_user_inputs.append(user_input)

        run._cached_inputs = []
        for template_input in template.inputs.all():
            matches = filter(
                lambda i: i.get("channel")==template_input.channel, inputs)
            assert len(matches) < 2, \
                'Too many inputs with channel "%s"' % template_input.channel
            if len(matches) == 1:
                run_input_data = matches[0]
                run_input_data['run'] = run
                data = run_input_data.pop('data', None)
                run_input_data['data_node'] = self._create_unsaved_data_node(
                    data, template_input.type)
                run_input = RunInput(**run_input_data)
            else:
                run_input = self._create_unsaved_run_input(template_input, run)
            run._cached_inputs.append(run_input)

        run._cached_outputs = []
        for template_output in template.outputs:
            matches = filter(
                lambda o: o.get("channel")==template_output.get('channel'),
                outputs)
            assert len(matches) < 2, \
                'Too many outputs with channel "%s"' % template_output.get('channel')
            if len(matches) == 1:
                run_output_data = matches[0]
                run_output_data['run'] = run
                data = run_output_data.pop('data', None)
                run_output_data['data_node'] = self._create_unsaved_data_node(
                    data, template_output.get('type'))
                run_output = RunOutput(**run_output_data)
            else:
                run_output = self._create_unsaved_run_output(template_output, run)
            run._cached_outputs.append(run_output)

        # If run steps are not given in run_data, assume this is a new run
        # and create new run steps from template.
        run._cached_steps = []
        if steps:
            for step in steps:
                # Get the matching template for this step, without
                # triggering new database queries
                matches = filter(lambda s: s.name==step.get('name'),
                                 template.steps.all())
                if len(matches) == 0:
                    raise serializers.ValidationError(
                        'No template found for step "%s"' % step.get('name'))
                assert len(matches) == 1, \
                    'Too many template matches for step "%s"' % step.get('name')
                template_step = matches[0]
                if step.get('template'):
                    if step['template'].get('uuid') != template_step.uuid:
                        raise serializers.ValidationError(
                            'Template "%s" in run step "%s" does not match the'\
                            'template step found from the parent template "%s"'
                            % (template_step.uuid, step.get('name'), template.uuid))
                run._cached_steps.append(
                    self.create_unsaved_run(
                        template_step, run_data=step, parent=run)
                    )
        else:
            for template_step in template.steps.all():
                run._cached_steps.append(
                    self.create_unsaved_run(template_step, parent=run)
                )

        # Special tasks for the root run only
        if parent is None:
            self._root_run_uuid = run.uuid
            self._connect_inputs_outputs(run)
            self._sort_preexisting_and_unsaved_models(run)

        return run

    def _sort_preexisting_and_unsaved_models(self, root_run):
        # Check database for existing objects, and move them from
        # self._unsaved_* to to self._preexisting_*
        all_runs = self._flatten_cached_runs(root_run)
        all_run_uuids = [r.uuid for r in all_runs]
        preexisting_run_uuids = [
            r.uuid for r in Run.objects.filter(
                uuid__in=all_run_uuids)]
        for run in all_runs:
            if run.uuid in preexisting_run_uuids:
                if self._preexisting_runs.get(run.uuid):
                    raise serializers.ValidationError(
                        'Encountered run more than once: "%s"' % run.uuid)
                self._preexisting_runs[run.uuid] = run
            else:
                if self._unsaved_runs.get(run.uuid):
                    raise serializers.ValidationError(
                        'Encountered run more than once: "%s"' % run.uuid)
                self._unsaved_runs[run.uuid] = run

        for run in self._unsaved_runs.values():
            self._process_unsaved_run(run)

        # not quite "all" task_attempts--we've eliminated those
        # from preexisting runs.
        all_task_attempts = []
        for task in self._unsaved_tasks:
            all_task_attempts.extend(task._cached_task_attempts)
        all_task_attempt_uuids = [ta.uuid for ta in all_task_attempts]
        for ta in TaskAttempt.objects.filter(
                uuid__in=all_task_attempt_uuids):
            self._preexisting_task_attempts[ta.uuid] = ta
        for task in self._unsaved_tasks:
            for task_attempt in task._cached_task_attempts:
                if task_attempt.uuid in self._preexisting_task_attempts.keys():
                    # Use old TaskAttempt if it exists
                    continue
                elif task_attempt.uuid in self._unsaved_task_attempts.keys():
                    # Sometimes a run makes double-use of the same task_attempt
                    continue
                else:
                    self._process_unsaved_task_attempt(task_attempt)

        self._process_preexisting_and_unsaved_data_nodes()

    def _process_preexisting_and_unsaved_data_nodes(self):
        # All DataNodes are in self._unsaved_data_nodes, but
        # we need to remove any of these that are preexisting.
        data_node_uuids = self._unsaved_root_data_nodes.keys()
        preexisting_data_nodes = DataNode.objects.filter(uuid__in=data_node_uuids)
        for node in preexisting_data_nodes:
            self._preexisting_data_nodes[node.uuid] = node
            self._unsaved_root_data_nodes.pop(node.uuid)
        # This steps converts from a root node with tree data cached (if parallel)
        # to nested nodes, each with cached contents for one scalar data object
        for data_node in self._unsaved_root_data_nodes.values():
            self._expand_data_node_contents(data_node, data_node._cached_contents)

        file_references = {}
        for data_node in self._unsaved_data_nodes.values():
            # Process DataObject
            contents = data_node._cached_expanded_contents
            if not contents:
                continue
            if isinstance(contents, dict):
                data_node.data_object = self._create_unsaved_data_object(contents)
                self._unsaved_data_objects[
                    data_node.data_object.uuid] = data_node.data_object
            elif data_node.type == 'file':
                nodes_with_this_reference = file_references.setdefault(contents, [])
                nodes_with_this_reference.append(data_node)
            else:
                # For non-file values, create a new node
                data_node.data_object = DataObject(
                    type=data_node.type,
                    data={'value': contents})
                self._unsaved_data_objects[
                    data_node.data_object.uuid] = data_node.data_object
        file_lookups = DataObject.filter_multiple_by_name_or_id_or_tag_or_hash(
            file_references.keys())
        for reference, data_objects in file_lookups.iteritems():
            if len(data_objects) == 0:
                raise serializers.ValidationError(
                    'No file found for reference "%s"' % reference)
            if len(data_objects) > 1:
                raise serializers.ValidationError(
                    'Found %s files for reference "%s", expected 1.'
                    % (len(dataobjects), reference))
            for data_node in file_references[reference]:
                data_node.data_object = data_objects[0]
                self._preexisting_data_objects[
                    data_objects[0].uuid] = data_objects[0]

        data_object_uuids = self._unsaved_data_objects.keys()
        preexisting_data_objects = DataObject.objects.filter(
            uuid__in=data_object_uuids)
        for data_object in preexisting_data_objects:
            self._preexisting_data_objects[data_object.uuid] = data_object
            self._unsaved_data_objects.pop(data_object.uuid)

    def _expand_data_node_contents(
            self, data_node, contents, parent=None, index=None):
        # If contents is a scalar, we simply assign it to _cached_expanded_contents
        # If it is a list, recursively create child DataNodes, assign their
        # contents, and
        data_node.index = index
        self._unsaved_data_nodes[data_node.uuid] = data_node
        if parent:
            self._data_node_parent_child_relationships.append(
                (parent.uuid, data_node.uuid))
            data_node.tree_id = parent.tree_id
        if isinstance(contents, list):
            data_node._cached_expanded_contents = None
            data_node.degree = len(contents)
            for i in range(len(contents)):
                child = DataNode(type=data_node.type)
                self._expand_data_node_contents(
                    child, contents[i], parent=data_node, index=i)
        else:
            data_node._cached_expanded_contents = contents

    def _process_unsaved_run(self, run):
        self._unsaved_run_inputs.extend(run._cached_inputs)
        self._unsaved_run_outputs.extend(run._cached_outputs)
        self._unsaved_run_user_inputs.extend(run._cached_user_inputs)

        self._get_unsaved_data_nodes_from_data_channels(run._cached_inputs)
        self._get_unsaved_data_nodes_from_data_channels(run._cached_outputs)
        self._get_unsaved_data_nodes_from_data_channels(run._cached_user_inputs)
        
        if run._cached_parent:
            self._run_parent_child_relationships.append(
                (run._cached_parent.uuid, run.uuid))
        self._unsaved_run_events.extend(run._cached_events)

        for task in run._cached_tasks:
            self._process_unsaved_task(task)

    def _process_unsaved_task(self, task):
        # Tasks from unsaved runs should never be preexisting, since
        # tasks can't have multiple parents
        self._unsaved_tasks.append(task)
        self._unsaved_task_inputs.extend(task._cached_inputs)
        self._unsaved_task_outputs.extend(task._cached_outputs)
        self._get_unsaved_data_nodes_from_data_channels(task._cached_inputs)
        self._get_unsaved_data_nodes_from_data_channels(task._cached_outputs)
        self._unsaved_task_events.extend(task._cached_events)
        if task._cached_active_task_attempt_uuid:
            self._task_to_task_attempt_relationships.append(
                (task.uuid, task._cached_active_task_attempt_uuid))
        for task_attempt in task._cached_task_attempts:
            self._unsaved_task_to_all_task_attempts_m2m_relationships.append(
                TaskMembership(parent_task=task, child_task_attempt=task_attempt))

    def _process_unsaved_task_attempt(self, task_attempt):
        self._unsaved_task_attempts[task_attempt.uuid] = task_attempt
        self._unsaved_task_attempt_inputs.extend(task_attempt._cached_inputs)
        self._unsaved_task_attempt_outputs.extend(task_attempt._cached_outputs)
        self._get_unsaved_data_nodes_from_data_channels(task_attempt._cached_inputs)
        self._get_unsaved_data_nodes_from_data_channels(task_attempt._cached_outputs)
        self._unsaved_task_attempt_events.extend(task_attempt._cached_events)
        self._unsaved_task_attempt_log_files.extend(task_attempt._cached_log_files)

    def _flatten_cached_runs(self, run):
        runs = [run]
        for step in run._cached_steps:
            runs.extend(self._flatten_cached_runs(step))
        return runs

    def _get_unsaved_data_nodes_from_data_channels(self, data_channels):
        for channel in data_channels:
            node = channel.data_node
            # Overwrite is ok
            self._unsaved_root_data_nodes[node.uuid] = node

    def _validate_run_data_fields(self, run_data):
        data_keys = run_data.keys()
        serializer_keys = self._serializer_fields
        extra_fields = filter(
            lambda key: key not in serializer_keys, data_keys)
        if extra_fields:
            raise serializers.ValidationError(
                'Unrecognized fields %s' % extra_fields)

    def _get_notification_context(self):
        context = {
            'server_name': get_setting('SERVER_NAME')}
        request = self._serializer_context.get('request')
        if request:
            context.update({
                'server_url': '%s://%s' % (
                    request.scheme,
		    request.get_host()),
	    })
        return context

    def _create_unsaved_task(self, task_data, run):
        task_attempts = task_data.pop('all_task_attempts', [])
        active_task_attempt = task_data.pop('task_attempt', None)
        inputs = task_data.pop('inputs', [])
        outputs = task_data.pop('outputs', [])
        events = task_data.pop('events', [])
        task_data.pop('url', None)
        task_data.pop('status', None)
        task_data['run'] = run
        task = Task(**task_data)
        task._cached_inputs = []
        for input_data in inputs:
            # create unsaved inputs
            input_data['task'] = task
            data = input_data.pop('data', None)
            if data:
                input_data['data_node'] = self._create_unsaved_data_node(
                    data, input_data.get('type'))
            task._cached_inputs.append(TaskInput(**input_data))
        task._cached_outputs = []
        for output_data in outputs:
            output_data['task'] = task
            data = output_data.pop('data', None)
            if data:
                output_data['data_node'] = self._create_unsaved_data_node(
                    data, output_data.get('type'))
            task._cached_outputs.append(TaskOutput(**output_data))
        task._cached_events = []
        for event in events:
            event['task'] = task
            task._cached_events.append(TaskEvent(**event))
        task._cached_active_task_attempt_uuid = None
        if active_task_attempt:
            task._cached_active_task_attempt_uuid = active_task_attempt.get('uuid')
        task._cached_task_attempts = []
        for task_attempt in task_attempts:
            task._cached_task_attempts.append(
                self._create_unsaved_task_attempt(task_attempt, task))
        return task

    def _create_unsaved_task_attempt(self, task_attempt_data, task):
        inputs = task_attempt_data.pop('inputs', [])
        outputs = task_attempt_data.pop('outputs', [])
        events = task_attempt_data.pop('events', [])
        log_files = task_attempt_data.pop('log_files', [])
        task_attempt_data.pop('url', None)
        task_attempt_data.pop('status', None)
        task_attempt = TaskAttempt(**task_attempt_data)
        task_attempt._cached_inputs = []
        for input_data in inputs:
            input_data['task_attempt'] = task_attempt
            data = input_data.pop('data', None)
            if data:
                input_data['data_node'] = self._create_unsaved_data_node(
                    data, input_data.get('type'))
            task_attempt._cached_inputs.append(
                TaskAttemptInput(**input_data))
        task_attempt._cached_outputs = []
        for output_data in outputs:
            output_data['task_attempt'] = task_attempt
            data = output_data.pop('data', None)
            if data:
                output_data['data_node'] = self._create_unsaved_data_node(
                    data, output_data.get('type'))
            task_attempt._cached_outputs.append(
                TaskAttemptOutput(**output_data))
        task_attempt._cached_log_files = []
        for log_file in log_files:
            log_file['task_attempt'] = task_attempt
            data_object = log_file.pop('data_object', None)
            log_file.pop('url')
            if data_object:
                log_file['data_object'] = self._create_unsaved_data_object(
                    data_object)
                self._unsaved_data_objects[
                    log_file['data_object'].uuid] = log_file['data_object']
            task_attempt._cached_log_files.append(
                TaskAttemptLogFile(**log_file))
        task_attempt._cached_events = []
        for event in events:
            event['task_attempt'] = task_attempt
            task_attempt._cached_events.append(
                TaskAttemptEvent(**event))
        return task_attempt

    def _connect_tasks_to_active_task_attempts(self, tasks, task_attempts):
        params = []
        for task_uuid, task_attempt_uuid in self._task_to_task_attempt_relationships:
            task = filter(lambda t: t.uuid==task_uuid, tasks)[0]
            task_attempt = filter(
                lambda ta: ta.uuid==task_attempt_uuid, task_attempts)[0]
            params.append((task.id, task_attempt.id))
        if params:
            case_statement = ' '.join(
                ['WHEN id=%s THEN %s' % pair for pair in params])
            id_list = ', '.join(['%s' % pair[0] for pair in params])
            sql = 'UPDATE api_task SET task_attempt_id= CASE %s END WHERE id IN (%s)'\
                                                        % (case_statement, id_list)
            with django.db.connection.cursor() as cursor:
                cursor.execute(sql)

    def _create_unsaved_data_object(self, contents):
        contents.pop('url')
        if 'value' in contents.keys():
            value = contents.pop('value')
            contents['data'] = {'value': value}
        data_object = DataObject(**contents)
        return data_object
                
    def _create_unsaved_data_node_from_contents(self, contents, data_type):
        return self._create_unsaved_data_node({'contents': contents}, data_type)

    def _create_unsaved_data_node(self, data, data_type):
        data.pop('url', None) # pop read-only data
        contents = data.pop('contents') # handle contents separately
        data['type'] = data_type
        data_node = DataNode(**data)
        data_node._cached_contents = contents
        return data_node

    def _create_unsaved_run_input(self, template_input, run):
        run_input = {}
        run_input['run'] = run
        run_input['type'] = template_input.type
        run_input['mode'] = template_input.mode
        run_input['group'] = template_input.group
        run_input['channel'] = template_input.channel
        run_input['as_channel'] = template_input.as_channel
        run_input_model = RunInput(**run_input)
        return run_input_model

    def _create_unsaved_run_output(self, template_output, run):
        run_output = {}
        run_output['run'] = run
        if template_output.get('type'):
            run_output['type'] = template_output.get('type')
        if template_output.get('mode'):
            run_output['mode'] = template_output.get('mode')
        if template_output.get('source'):
            run_output['source'] = template_output.get('source')
        if template_output.get('parser'):
            run_output['parser'] = template_output.get('parser')
        if template_output.get('channel'):
            run_output['channel'] = template_output.get('channel')
        if template_output.get('as_channel'):
            run_output['as_channel'] = template_output.get('as_channel')
        run_output_model = RunOutput(**run_output)
        return run_output_model

    def _connect_runs_to_parents(self, runs):
        params = []
        for parent_uuid, child_uuid in self._run_parent_child_relationships:
            child = filter(
                lambda r: r.uuid==child_uuid, runs)[0]
            parent = filter(
                lambda r: r.uuid==parent_uuid, runs)[0]
            params.append((child.id, parent.id))
        if params:
            case_statement = ' '.join(
                ['WHEN id=%s THEN %s' % pair for pair in params])
            id_list = ', '.join(['%s' % pair[0] for pair in params])
            sql = 'UPDATE api_run SET parent_id= CASE %s END WHERE id IN (%s)'\
                                                 % (case_statement, id_list)
            with django.db.connection.cursor() as cursor:
                cursor.execute(sql)

    def _connect_inputs_outputs(self, run):
        parent = None
        self._connect_outputs(run, parent)
        self._connect_inputs(run, parent)

    def _connect_outputs(self, run, parent):
        run._connectors = {}

        # Depth-first
        for step in run._cached_steps:
            self._connect_outputs(step, run)

        # Connect run._connectors to outputs, or initialize with new node
        # Add outputs to parent._connectors
        for output in run._cached_outputs:
            if output.data_node is None:
                if run._connectors.get(output.channel):
                    output.data_node = run._connectors[output.channel]
                else:
                    data_node = self._create_unsaved_data_node_from_contents(
                        None, output.type)
                    output.data_node = data_node
            if parent:
                if parent._connectors.get(output.channel):
                    raise serializers.ValidationError(
                        'Too many sources for channel "%s"' % output.channel)
                parent._connectors[output.channel] = output.data_node

    def _connect_inputs(self, run, parent):
        # Connect inputs using template, run_inputs, or parent connectors
        # Add inputs to run._connectors
        for input in run._cached_inputs:
            if run._connectors.get(input.channel):
                raise serializers.ValidationError(
                    'Too many sources for channel "%s"' % input.channel)

            matches = filter(lambda i: i.channel==input.channel,
                             run._cached_user_inputs)
            if len(matches) > 1:
                raise serializers.ValidationError(
                    'More than one UserInput matched channel "%s"' % input.channel)
            if len(matches) == 1:
                user_input = matches[0]
            else:
                user_input = None

            if user_input and parent:
                raise serializers.ValidationError(
                    'Invalid user input on channel "%s". User inputs are '\
                    'not supported on children' % input.channel)
            if user_input:
                data_node = user_input.data_node
            elif parent and parent._connectors.get(input.channel):
                data_node = parent._connectors[input.channel]
            else:
                template_input = run.template.get_input(input.channel)
                if template_input.data_node:
                    data_node = template_input.data_node
                else:
                    data_node = self._create_unsaved_data_node_from_contents(
                        None, input.type)
            input.data_node = data_node

            run._connectors[input.channel] = input.data_node

        # Breadth-first
        for step in run._cached_steps:
            self._connect_inputs(step, run)

    def cleanup(self):
        try:
            async.execute(
                async.roll_back_new_run,
                [r.uuid for r in self._new_runs],
                [ta.uuid for ta in self._new_task_attempts],
                [n.uuid for n in self._new_data_nodes],
                [o.uuid for o in self._new_data_objects])
        except:
            pass
