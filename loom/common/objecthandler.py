import json
import requests
from loom.common.exceptions import *

class ObjectHandler(object):
    """ObjectHandler provides functions to create and work with objects in the 
    Loom database via the HTTP API
    """

    def __init__(self, master_url):
        self.api_root_url = master_url + '/api/'

    # ---- General methods ----
    
    def _post(self, data, relative_url, raise_for_status=False):
        url = self.api_root_url + relative_url
        return self._make_request_to_server(lambda: requests.post(url, data=json.dumps(data)), raise_for_status=raise_for_status)

    def _get(self, relative_url, raise_for_status=False):
        url = self.api_root_url + relative_url
        return self._make_request_to_server(lambda: requests.get(url), raise_for_status=raise_for_status)
    
    def _make_request_to_server(self, query_function, raise_for_status=False):
        """Verifies server connection and handles response errors
        for either get or post requests
        """
        try:
            response = query_function()
        except requests.exceptions.ConnectionError as e:
            raise ServerConnectionError("No response from server.\n%s" % e.message)
        if raise_for_status:
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                raise BadResponseError("%s\n%s" % (e.message, response.text))
        return response

    def _post_object(self, object_data, relative_url):
        return self._post(object_data, relative_url, raise_for_status=True).json()['object']

    def _get_object(self, relative_url, raise_for_status=False):
        response = self._get(relative_url)
        if response.status_code == 404:
            return None
        elif response.status_code == 200:
            return response.json()
        else:
            raise BadResponseError("Status code %s." % response.status_code)

    def _get_object_index(self, relative_url, raise_for_status=False):
        response = self._get(relative_url)
        if response.status_code == 200:
            return response.json()
        else:
            raise BadResponseError("Status code %s." % response.status_code)

    def get_server_time(self):
        """Use this, not local system time,  when generating a time stamp in the client
        """
        response = self._get('servertime/')
        return response.json()['time']

    # ---- Post/Get [object_type] methods ----

    def post_data_object(self, data_object):
        return self._post_object(
            data_object,
            'data_objects/')

    def get_data_object_array(self, array_id):
        return self._get_object(
            'data_object_arrays/%s/' % array_id)

    def post_data_object_array(self, data_object_array):
        return self._post_object(
            data_object_array,
            'data_object_arrays/')

    def get_file_data_object(self, file_id):
        return self._get_object(
            'file_data_objects/%s/' % file_id)

    def get_file_data_object_index(self, query_string='', min=0, max=float('inf')):
        if query_string:
            url = 'file_data_objects/?q='+query_string
        else:
            url = 'file_data_objects/'
        file_data_objects =  self._get_object_index(url)['file_data_objects']
        if len(file_data_objects) < min:
            raise IdMatchedTooFewFileDataObjectsError('Found %s File Data Objects, expected at least %s' %(len(file_data_objects), min))
        if len(file_data_objects) > max:
            raise IdMatchedTooManyFileDataObjectsError('Found %s File Data Objects, expected at most %s' %(len(file_data_objects), max))
        return file_data_objects

    def get_file_storage_locations_by_file(self, file_id):
        return self._get_object(
            'file_data_objects/'+file_id+'/file_storage_locations/'
        )['file_storage_locations']

    def post_file_storage_location(self, file_storage_location):
        return self._post_object(
            file_storage_location,
            'file_storage_locations/')

    def post_data_source_record(self, data_source_record):
        return self._post_object(
            data_source_record,
            'data_source_records/'
        )

    def get_source_records_by_file(self, file_id):
        return self._get_object_index(
            'file_data_objects/' + file_id + '/data_source_records/'
        )['data_source_records']
    
    def get_workflow(self, workflow_id):
        return self._get_object(
            'workflows/%s/' % workflow_id
        )

    def get_workflow_index(self, query_string='', min=0, max=float('inf')):
        if query_string:
            url = 'workflows/?q='+query_string
        else:
            url = 'workflows/'
        workflows = self._get_object_index(url)['workflows']
        if len(workflows) < min:
            raise Error('Found %s workflows, expected at least %s' %(len(workflows), min))
        if len(workflows) > max:
            raise Error('Found %s workflows, expected at most %s' %(len(workflows), max))
        return workflows

    def post_workflow(self, workflow):
        return self._post_object(
            workflow,
            'workflows/')

    def get_workflow_run(self, workflow_run_id):
        return self._get_object(
            'workflow_runs/%s/' % workflow_run_id
        )

    def get_workflow_run_index(self, query_string='', min=0, max=float('inf')):
        if query_string:
            url = 'workflow_runs/?q='+query_string
        else:
            url = 'workflow_runs/'
        workflow_runs = self._get_object_index(url)['workflow_runs']
        if len(workflow_runs) < min:
            raise Error('Found %s workflow runs, expected at least %s' %(len(workflow_runs), min))
        if len(workflow_runs) > max:
            raise Error('Found %s workflow runs, expected at most %s' %(len(workflow_runs), max))
        return workflow_runs

    def post_workflow_run(self, workflow_run):
        return self._post_object(
            workflow_run,
            'workflow_runs/')

    def update_task_run(self, task_run):
        return self._post_object(
            task_run,
            'task_runs/%s/' % task_run['_id'])
