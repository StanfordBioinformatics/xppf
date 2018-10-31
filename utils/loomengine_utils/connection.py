import datetime
import os
import json
import logging
import requests
import time
import urllib

from .exceptions import LoomengineUtilsError, ServerConnectionError, \
    ServerConnectionHttpError, ResourceCountError

logger = logging.getLogger(__name__)

def disable_insecure_request_warning():
    """Suppress warning about untrusted SSL certificate."""
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class Connection(object):
    """Connection class is a wrapper for the Loom server's HTTP API.
    It includes CRUD operations for objects stored in the database.
    It also handles authentication headers.
    """

    def __init__(self, master_url, token=None, verify=False):
        self.api_root_url = os.path.join(master_url, 'api/')
        self.token = token
        self.verify = verify

    def _add_auth_token_to_headers(self, headers):
        if self.token is not None:
            headers['Authorization'] = 'Token %s' % self.token
        return headers

    def _post(self, data, relative_url, auth=None, timeout=30):
        url = self.api_root_url + relative_url
        if not self.verify:
            disable_insecure_request_warning()
        return self._make_request_to_server(
            lambda: requests.post(
                url,
                data=json.dumps(data),
                headers=self._add_auth_token_to_headers(
                    {'content-type': 'application/json'}),
                verify=self.verify,
                auth=auth,
                timeout=timeout
            ))

    def _put(self, data, relative_url, timeout=30):
        url = self.api_root_url + relative_url
        if not self.verify:
            disable_insecure_request_warning()
        return self._make_request_to_server(
            lambda: requests.put(
                url,
                data=json.dumps(data),
                headers=self._add_auth_token_to_headers(
                    {'content-type': 'application/json'}),
                verify=self.verify,
                timeout=timeout))

    def _patch(self, data, relative_url, timeout=30):
        url = self.api_root_url + relative_url
        if not self.verify:
            disable_insecure_request_warning()
        return self._make_request_to_server(
            lambda: requests.patch(
                url,
                data=json.dumps(data),
                headers=self._add_auth_token_to_headers(
                    {'content-type': 'application/json'}),
                verify=self.verify,
                timeout=timeout))

    def _get(self, relative_url, raise_for_status=True, params=None, timeout=30):
        if params is None:
            params = {}
        url = self.api_root_url + relative_url
        if not self.verify:
            disable_insecure_request_warning()
        return self._make_request_to_server(
            lambda: requests.get(
                url,
                verify=self.verify, # Don't fail on unrecognized SSL certificate
                params=params,
                headers=self._add_auth_token_to_headers({}),
                timeout=timeout), 
            raise_for_status=raise_for_status)

    def _delete(self, relative_url, raise_for_status=True, timeout=30):
        url = self.api_root_url + relative_url
        if not self.verify:
            disable_insecure_request_warning()
        return self._make_request_to_server(
            lambda: requests.delete(
                url,
                headers=self._add_auth_token_to_headers(
                    {'content-type': 'application/json'}),
                verify=self.verify,
                timeout=30
            ),
            raise_for_status=raise_for_status
        )

    def _make_request_to_server(self, query_function, raise_for_status=True,
                                time_limit_seconds=2, retry_delay_seconds=0.2):
        """Retry sending request until timeout or until receiving a response.
        """
        start_time = datetime.datetime.now()
        while datetime.datetime.now() - start_time < datetime.timedelta(
                0, time_limit_seconds):
            error = None
            response = None
            try:
                response = query_function()
            except requests.exceptions.ConnectionError as e:
                error = ServerConnectionError(
                    "No response from server.\n%s" % e)
            except:
                if response:
                    logger.info(response.text)
                raise
            if response is not None and raise_for_status:
                # raises requests.exceptions.HTTPError
                self._raise_for_status(response)
            if error:
                time.sleep(retry_delay_seconds)
                continue
            else:
                return response
        raise error

    def _raise_for_status(self, response):
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                raise ServerConnectionHttpError(
                    '(403) Permission denied. '\
                    'Have you logged in with "loom auth login"?')
            elif e.response.status_code >= 500:
                message = "(%s) %s" % (e.response.status_code, e)
                raise ServerConnectionHttpError(message)
            elif e.response.status_code >= 400:
                try:
                    message = e.response.json()
                    import pdb; pdb.set_trace()
                except:
                    message = e.response.text
                if isinstance(message, list):
                    message = '; '.join(message)
                    raise ServerConnectionHttpError(message)
                else:
                    raise ServerConnectionHttpError(message)

    def _post_resource(self, object_data, relative_url):
        return self._post(object_data, relative_url).json()

    def _patch_resource(self, object_data, relative_url):
        return self._patch(object_data, relative_url).json()

    def _delete_resource(self, relative_url):
        response = self._delete(relative_url, raise_for_status=True)
        try:
            return response.json()
        except ValueError:
            # ValueError triggered because some delete views return no text
            return None

    def _get_resource(self, relative_url, params=None):
        """Convenience function for retrieving a resource.
        If resource does not exist, return None.
        """
        response = self._get(relative_url, params=params, raise_for_status=False)
        if response.status_code == 404:
            return None
        self._raise_for_status(response)
        return response.json()

    def _get_index(self, relative_url, params=None):
        response = self._get(relative_url, params=params)
        response.raise_for_status()
        return response.json()

    # ------------------ Resource-specific methods ---------------------

    # DataNode

    def get_data_node(self, data_node_id, expand=False):
        params = {}
        if expand:
            params['expand'] = '1'
        return self._get_resource(
            'data-nodes/%s/' % data_node_id, params=params)

    def get_data_node_index(self):
        return self._get_index('data-nodes/')

    # DataObject

    def post_data_object(self, data):
        return self._post_resource(data, 'data-objects/')

    def get_data_object(self, data_object_id):
        return self._get_resource(
            'data-objects/%s/' % data_object_id)

    def update_data_object(self, data_object_id, data_update):
        return self._patch_resource(
            data_update,
            'data-objects/%s/' % data_object_id)

    def delete_data_object(self, data_object_id):
        return self._delete_resource('data-objects/%s/' % data_object_id)

    def _check_min_max(self, resources, label, min, max):
        if len(resources) < min:
            raise ResourceCountError(
                'Found %s %s, expected at least %s' \
                % (len(resources), label, min))
        if len(resources) > max:
            raise ResourceCountError(
                'Found %s %s, expected at most %s' \
                % (len(resources), label, max))

    def get_data_object_index(
            self, query_string=None, source_type=None,
            labels=None,
            type=None, min=0, max=float('inf')):
        url = 'data-objects/'
        params = {}
        if query_string:
            params['q'] = query_string
        if source_type:
            params['source_type'] = source_type
        if type:
            params['type'] = type
        if labels:
            params['labels'] = ','.join(labels)
        data_objects =  self._get_index(url, params=params)
        self._check_min_max(data_objects, 'DataObjects', min, max)
        return data_objects

    def get_data_object_index_with_limit(
            self, query_string=None, source_type=None,
            labels=None,
            type=None,
            limit=10, offset=0):
        url = 'data-objects/'
        params = {}
        if query_string:
            params['q'] = query_string
        if source_type:
            params['source_type'] = source_type
        if type:
            params['type'] = type
        if labels:
            params['labels'] = ','.join(labels)
        params['limit'] = limit
        params['offset'] = offset
        data = self._get_index(url, params=params)
        return data

    def get_data_object_dependencies(self, data_object_id):
        return self._get_resource(
            'data-objects/%s/dependencies/' % data_object_id)
    
    def post_data_tag(self, data_object_id, data):
        return self._post_resource(
            data,
            'data-objects/%s/add-tag/' % data_object_id)

    def remove_data_tag(self, data_object_id, data):
        return self._post_resource(
            data,
            'data-objects/%s/remove-tag/' % data_object_id)

    def list_data_tags(self, data_object_id):
        return self._get_resource('data-objects/%s/tags/' % data_object_id)

    def post_data_label(self, data_object_id, data):
        return self._post_resource(
            data,
            'data-objects/%s/add-label/' % data_object_id)

    def remove_data_label(self, data_id, data):
        return self._post_resource(
            data,
            'data-objects/%s/remove-label/' % data_id)

    def list_data_labels(self, data_id):
        return self._get_resource(
            'data-objects/%s/labels/' % data_id)

    # Template
    
    def post_template(self, template):
        return self._post_resource(
            template,
            'templates/')

    def get_template(self, template_id, expand=False):
        params = {}
        if expand:
            params['expand'] = '1'
        return self._get_resource(
            'templates/%s/' % template_id, params=params
        )

    def delete_template(self, template_id):
        return self._delete_resource('templates/%s/' % template_id)

    def get_template_index(self, query_string='', parent_only=False,
                           labels=None, min=0, max=float('inf')):
        url = 'templates/'
        params = {}
        if query_string:
            params['q'] = query_string
        if parent_only:
            params['parent_only'] = '1'
        if labels:
            params['labels'] = ','.join(labels)
        templates = self._get_index(url, params=params)
        self._check_min_max(templates, 'Templates', min, max)
        return templates

    def get_template_index_with_limit(self, query_string=None, parent_only=False,
                                 labels=None, limit=10, offset=0):
        url = 'templates/'
        params = {}
        if query_string:
            params['q'] = query_string
        if parent_only:
            params['parent_only'] = '1'
        if labels:
            params['labels'] = ','.join(labels)
        params['limit'] = limit
        params['offset'] = offset
        return self._get_index(url, params=params)

    def get_template_dependencies(self, template_id):
        return self._get_resource('templates/%s/dependencies/' % template_id)
            
    def post_template_tag(self, template_id, data):
        return self._post_resource(
            data,
            'templates/%s/add-tag/' % template_id)

    def remove_template_tag(self, template_id, data):
        return self._post_resource(
            data,
            'templates/%s/remove-tag/' % template_id)

    def list_template_tags(self, template_id):
        return self._get_resource('templates/%s/tags/' % template_id)

    def post_template_label(self, template_id, data):
        return self._post_resource(
            data,
            'templates/%s/add-label/' % template_id)

    def list_template_labels(self, template_id):
        return self._get_resource('templates/%s/labels/' % template_id)

    def remove_template_label(self, template_id, data):
        return self._post_resource(
            data,
            'templates/%s/remove-label/' % template_id)
    # Run
    def post_run(self, run):
        return self._post_resource(run, 'runs/')

    def get_run(self, run_id, expand=False):
        params = {}
        if expand:
            params['expand'] = 1
        return self._get_resource('runs/%s/' % run_id, params=params)

    def delete_run(self, run_id):
        return self._delete_resource('runs/%s/' % run_id)

    def get_run_index(self, query_string=None, parent_only=False,
                      labels=None,
                      min=0, max=float('inf')):
        url = 'runs/'
        params = {}
        if query_string:
            params['q'] = query_string
        if parent_only:
            params['parent_only'] = '1'
        if labels:
            params['labels'] = ','.join(labels)
        runs = self._get_index(url, params=params)
        self._check_min_max(runs, 'Runs', min, max)
        return runs

    def get_run_index_with_limit(self, query_string=None, parent_only=False,
                                 labels=None, limit=10, offset=0):
        url = 'runs/'
        params = {}
        if query_string:
            params['q'] = query_string
        if parent_only:
            params['parent_only'] = '1'
        if labels:
            params['labels'] = ','.join(labels)
        params['limit'] = limit
        params['offset'] = offset
        return self._get_index(url, params=params)

    def kill_run(self, run_id):
        return self._post_resource({}, 'runs/%s/kill/' % run_id)

    def get_run_dependencies(self, run_id):
        return self._get_resource('runs/%s/dependencies/' % run_id)

    def post_run_tag(self, run_id, data):
        return self._post_resource(
            data,
            'runs/%s/add-tag/' % run_id)
    def remove_run_tag(self, run_id, data):
        return self._post_resource(
            data,
            'runs/%s/remove-tag/' % run_id)

    def list_run_tags(self, run_id):
        return self._get_resource('runs/%s/tags/' % run_id)

    def post_run_label(self, run_id, data):
        return self._post_resource(
            data,
            'runs/%s/add-label/' % run_id)

    def remove_run_label(self, run_id, data):
        return self._post_resource(
            data,
            'runs/%s/remove-label/' % run_id)
    def list_run_labels(self, run_id):
        return self._get_resource(
            'runs/%s/labels/' % run_id)

    # Task

    def get_task(self, task_id):
        return self._get_resource('tasks/%s/' % task_id)

    # TaskAttempt

    def get_task_attempt(self, task_attempt_id):
        return self._get_resource('task-attempts/%s/' % task_attempt_id)

    def update_task_attempt(self, task_attempt_id, task_attempt_update):
        return self._patch_resource(
            task_attempt_update,
            'task-attempts/%s/' % task_attempt_id)

    def get_task_attempt_output(self, task_attempt_output_id):
        return self._get_resource('outputs/%s/' % task_attempt_output_id)

    def update_task_attempt_output(self, task_attempt_output_id,
                                   task_attempt_output_update):
        return self._patch_resource(
            task_attempt_output_update,
            'outputs/%s/' % task_attempt_output_id)

    def post_task_attempt_log_file(self, task_attempt_id, task_attempt_log_file):
        return self._post_resource(
            task_attempt_log_file,
            'task-attempts/%s/log-files/' % task_attempt_id
        )
    
    def post_task_attempt_log_file_data_object(
            self, task_attempt_log_file_id, data_object):
        return self._post_resource(
            data_object,
            'log-files/%s/data-object/' % task_attempt_log_file_id
        )

    def post_task_attempt_event(self, task_attempt_id, task_attempt_event):
        return self._post_resource(
            task_attempt_event,
            'task-attempts/%s/events/' % task_attempt_id
        )

    def post_task_attempt_system_error(self, task_attempt_id):
        # details should be reported with post_task_attempt_event
        return self._post_resource(
            {},
            'task-attempts/%s/system-error/' % task_attempt_id)

    def post_task_attempt_analysis_error(self, task_attempt_id):
        # details should be reported with post_task_attempt_event
        return self._post_resource(
            {},
            'task-attempts/%s/analysis-error/' % task_attempt_id)

    def finish_task_attempt(self, task_attempt_id):
        return self._post_resource(
            {},
            'task-attempts/%s/finish/' % task_attempt_id)

    def get_task_attempt_settings(self, attempt_id):
        return self._get_resource('task-attempts/%s/settings/' % attempt_id)

    # User

    def post_user(self, data):
        return self._post_resource(data, 'users/')

    def update_user(self, user_id, data_update):
        return self._patch_resource(
            data_update,
            'users/%s/' % user_id)

    def delete_user(self, user_id):
        return self._delete_resource('users/%s/' % user_id)

    def get_user_index(self, query_string=None):
        url = 'users/'
        params = {}
        if query_string:
            params['q'] = query_string
        return self._get_index(url, params=params)

    # Token

    def create_token(self, username=None, password=None):
        response = self._post(
            {}, 'tokens/', auth=(username, password))
        return response.json().get('token')

    # Data/Template/Run Tag Indexes

    def get_data_tag_index(self):
        return self._get_index('data-tags/')

    def get_template_tag_index(self):
        return self._get_index('template-tags/')

    def get_run_tag_index(self):
        return self._get_index('run-tags/')

    # Data/Template/Run Label Indexes

    def get_data_label_index(self):
        return self._get_index('data-labels/')

    def get_template_label_index(self):
        return self._get_index('template-labels/')

    def get_run_label_index(self):
        return self._get_index('run-labels/')

    # Info/Version/Settings

    def get_info(self):
        """Return server info if available, else return None
        """
        response = self._get('info/')
        info = response.json()
        return info

    def get_version(self):
        info = self.get_info()
        return info.get('version')

    def get_storage_settings(self):
        return self._get_resource(
            'storage-settings/'
        )
