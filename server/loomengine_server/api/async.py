from __future__ import absolute_import, unicode_literals
from celery import shared_task
from celery.decorators import periodic_task
import copy
from datetime import timedelta
from django import db
from django.core.exceptions import ObjectDoesNotExist
import logging
import os
import re
import subprocess
import time

from api import get_setting, get_storage_settings
from api.exceptions import ConcurrentModificationError


"""This module contains asynchronous tasks
and the "execute" helper function for running tasks
"""

logger = logging.getLogger(__name__)

def execute(task_function, *args, **kwargs):
    """Run a task asynchronously
    """

    if get_setting('TEST_DISABLE_ASYNC_DELAY'):
        # Delay disabled, run synchronously
        logger.debug('Running function "%s" synchronously because '\
                     'TEST_DISABLE_ASYNC_DELAY is True'
                     % task_function.__name__)
        return task_function(*args, **kwargs)

    db.connections.close_all()
    task_function.delay(*args, **kwargs)

def execute_with_delay(task_function, *args, **kwargs):
    """Run a task asynchronously after at least delay_seconds
    """
    delay = kwargs.pop('delay', 0)
    if get_setting('TEST_DISABLE_ASYNC_DELAY'):
        # Delay disabled, run synchronously
        logger.debug('Running function "%s" synchronously because '\
                     'TEST_DISABLE_ASYNC_DELAY is True'
                     % task_function.__name__)
        return task_function(*args, **kwargs)

    db.connections.close_all()
    task_function.apply_async(args=args, kwargs=kwargs, countdown=delay)

SYSTEM_CHECK_INTERVAL_MINUTES = get_setting('SYSTEM_CHECK_INTERVAL_MINUTES')

@periodic_task(run_every=timedelta(minutes=SYSTEM_CHECK_INTERVAL_MINUTES))
def check_for_stalled_tasks():
    """Check for tasks that are no longer sending a heartbeat
    """
    from api.models.tasks import Task
    for task in Task.objects.filter(status_is_running=True):
        if not task.is_responsive():
            task.system_error()
        if task.is_timed_out():
            task.timeout_error()

@periodic_task(run_every=timedelta(minutes=SYSTEM_CHECK_INTERVAL_MINUTES))
def check_for_missed_cleanup():
    """Check for TaskAttempts that were never cleaned up
    """
    if get_setting('PRESERVE_ALL'):
        return
    from api.models.tasks import TaskAttempt
    if get_setting('PRESERVE_ON_FAILURE'):
        for task_attempt in TaskAttempt.objects.filter(
                status_is_running=False).filter(
                    status_is_cleaned_up=False).exclude(
                        status_is_failed=True):
            task_attempt.cleanup()
    else:
        for task_attempt in TaskAttempt.objects.filter(
                status_is_running=False).filter(status_is_cleaned_up=False):
            task_attempt.cleanup()

@periodic_task(run_every=timedelta(hours=1))
def clear_expired_logs():
    import elasticsearch
    import curator
    elasticsearch_host = get_setting('ELASTICSEARCH_HOST')
    elasticsearch_port = get_setting('ELASTICSEARCH_PORT')
    elasticsearch_log_expiration_days = get_setting('ELASTICSEARCH_LOG_EXPIRATION_DAYS')
    client = elasticsearch.Elasticsearch([elasticsearch_host], port=elasticsearch_port)
    ilo = curator.IndexList(client)
    ilo.filter_by_regex(kind='prefix', value='logstash-')
    ilo.filter_by_age(source='name', direction='older', timestring='%Y.%m.%d',
                      unit='days', unit_count=elasticsearch_log_expiration_days)
    delete_indices = curator.DeleteIndices(ilo)
    try:
        delete_indices.do_action()
    except curator.exceptions.NoIndices:
        pass

@shared_task
def delete_file_resource(file_resource_id):
    from api.models import FileResource
    from loomengine_utils.file_utils import File
    file_resource = FileResource.objects.get(id=file_resource_id)
    file_resource.setattrs_and_save_with_retries({'upload_status': 'deleting'})

    if not file_resource.link:
        # Replace start of URL with path inside Docker container.
        file_url = file_resource.file_url
        if file_url.startswith('file:///'):
            file_url = re.sub(
                '^'+get_setting('STORAGE_ROOT_WITH_PREFIX'),
                get_setting('INTERNAL_STORAGE_ROOT_WITH_PREFIX'),
                file_url)

        file = File(file_url, get_storage_settings(), retry=True)
        file.delete(pruneto=get_setting('INTERNAL_STORAGE_ROOT'))

    file_resource.delete()

@periodic_task(run_every=timedelta(minutes=14))
def cleanup_orphaned_file_resources():
    if get_setting('DISABLE_DELETE'):
        return

    from api.models import FileResource
    queryset = FileResource.objects.filter(data_object__isnull=True)
    count = queryset.count()
    logger.info('Periodic cleanup of unused files. %s files found.' % count)
    for file_resource in queryset.all():
        _delete_file_resource(file_resource.id)

@periodic_task(run_every=timedelta(minutes=13))
def cleanup_orphaned_task_attempts():
    if get_setting('DISABLE_DELETE'):
        return

    from api.models import TaskAttempt, DataNode
    orphaned_task_attempts = TaskAttempt.objects.filter(
        tasks=None, status_is_initializing=False)
    logger.info('Periodic cleanup of unused files. %s files found.'
                % orphaned_task_attempts.count())
    nodes_to_delete = set()
    for task_attempt in orphaned_task_attempts:
        input_data_nodes = DataNode.objects.filter(
            taskattemptinput__task_attempt__uuid=task_attempt.uuid)
        output_data_nodes = DataNode.objects.filter(
            taskattemptoutput__task_attempt__uuid=task_attempt.uuid)
        for item in input_data_nodes:
            nodes_to_delete.add(item)
        for item in output_data_nodes:
            nodes_to_delete.add(item)
        task_attempt.delete()
    for item in nodes_to_delete:
        try:
            item.delete()
        except models.ProtectedError:
            pass

# Runs

@shared_task
def send_notifications(run_uuid):
    from api.models import Run
    run = Run.objects.get(uuid=run_uuid)
    context = run.notification_context
    if not context:
        context = {}
    server_url = context.get('server_url')
    context.update({
        'run_url': '%s/#/runs/%s/' % (server_url, run.uuid),
        'run_api_url': '%s/api/runs/%s/' % (server_url, run.uuid),
        'run_status': run.status,
        'run_name_and_id': '%s@%s' % (run.name, run.uuid[0:8])
    })
    notification_addresses = []
    if run.notification_addresses:
        notification_addresses = run.notification_addresses
    if get_setting('NOTIFICATION_ADDRESSES'):
        notification_addresses = notification_addresses\
                                 + get_setting('NOTIFICATION_ADDRESSES')
    email_addresses = filter(lambda x: '@' in x, notification_addresses)
    urls = filter(lambda x: '@' not in x, notification_addresses)
    run._send_email_notifications(email_addresses, context)
    run._send_http_notifications(urls, context)

@shared_task
def kill_run(run_uuid, kill_message):
    # Used by views to avoid delaying requests.
    # Async Not needed otherwise -- use Run.kill directly
    from api.models.runs import Run
    run = Run.objects.get(uuid=run_uuid)
    try:
        run.kill(detail=kill_message)
    except Exception as e:
        logger.debug('Failed to kill run.uuid=%s.' % run.uuid)
        raise

@shared_task
def postprocess_run(run_uuid):
    from api.models.runs import Run
    run = Run.objects.get(uuid=run_uuid)
    run.prefetch()
    for step in run.get_leaves():
	for task in step.tasks.all():
            fingerprint = task.get_fingerprint()
            fingerprint.update_task_attempt_maybe(task.task_attempt)
    if not run.has_terminal_status():
        run.push_all_inputs()

@shared_task
def finish_task_attempt(task_attempt_uuid):
    from api.models import TaskAttempt
    # Used by views to avoid delaying requests.
    # Async Not needed otherwise -- use TaskAttempt.finish() directly
    task_attempt = TaskAttempt.objects.get(uuid=task_attempt_uuid)
    task_attempt.finish()

def _run_cleanup_task_attempt_playbook(task_attempt):
    env = copy.copy(os.environ)
    env['LOOM_TASK_ATTEMPT_DOCKER_IMAGE'] = task_attempt.environment.get('docker_image')
    playbook = os.path.join(
        get_setting('PLAYBOOK_PATH'),
        get_setting('CLEANUP_TASK_ATTEMPT_PLAYBOOK'))
    cmd_list = ['ansible-playbook',
                '-i', get_setting('ANSIBLE_INVENTORY'),
                playbook,
                # Without this, ansible uses /usr/bin/python,
                # which may be missing needed modules
                '-e', 'ansible_python_interpreter="/usr/bin/env python"',
    ]

    if get_setting('DEBUG'):
        cmd_list.append('-vvvv')

    new_vars = {'LOOM_TASK_ATTEMPT_ID': str(task_attempt.uuid),
                'LOOM_TASK_ATTEMPT_STEP_NAME': task_attempt.name
                }
    env.update(new_vars)

    p = subprocess.Popen(
        cmd_list, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    terminal_output, err_is_empty = p.communicate()
    if p.returncode != 0:
        msg = 'Cleanup failed for task_attempt.uuid="%s" with returncode="%s".' % (
            task_attempt.uuid, p.returncode)
        logger.error(msg)
        task_attempt.add_event(msg,
                               detail=terminal_output,
                               is_error=True)
        raise Exception(msg)

@shared_task
def cleanup_task_attempt(task_attempt_uuid):
    from api.models.tasks import TaskAttempt
    if get_setting('TEST_NO_TASK_ATTEMPT_CLEANUP'):
        return
    task_attempt = TaskAttempt.objects.get(uuid=task_attempt_uuid)
    _run_cleanup_task_attempt_playbook(task_attempt)
    task_attempt.add_event('Cleaned up',
                           is_error=False)
    task_attempt.setattrs_and_save_with_retries({
        'status_is_cleaned_up': True })

@shared_task
def execute_task(task_uuid, force_rerun=False):
    # If task has been run before, old TaskAttempt will be rendered inactive
    from api.models.tasks import Task
    task = Task.objects.get(uuid=task_uuid)
    # Do not run again if already running
    if task.task_attempt and task.is_responsive() and not task.is_timed_out():
        return

    # Use TaskFingerprint to see if a valid TaskAttempt for this fingerprint
    # already exists, or to flag the new TaskAttempt to be reused by other
    # tasks with this fingerprint
    fingerprint = task.get_fingerprint()

    task_attempt = None
    if not force_rerun:
        # By skipping this, a new TaskAttempt will always be created.
        # Use existing TaskAttempt if a valid one exists with the same fingerprint
        if fingerprint.active_task_attempt \
           and fingerprint.active_task_attempt.might_succeed():
            task.activate_task_attempt(fingerprint.active_task_attempt)
            return

    task_attempt = task.create_and_activate_task_attempt()
    fingerprint.update_task_attempt_maybe(task_attempt)
    if get_setting('TEST_NO_RUN_TASK_ATTEMPT'):
        return
    return task_attempt.run_with_heartbeats()

@shared_task
def roll_back_new_run(
        run_uuids, task_attempt_uuids, data_node_uuids, data_object_uuids):
    from api.models import Run, TaskAttempt, DataNode, DataObject
    Run.objects.filter(uuid__in=run_uuids).delete()
    TaskAttempt.objects.filter(uuid__in=task_attempt_uuids).delete()
    DataNode.objects.filter(uuid__in=data_node_uuids).delete()
    DataObject.objects.filter(uuid__in=data_object_uuids).delete()

