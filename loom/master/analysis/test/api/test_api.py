from datetime import datetime
import json
import os
import requests
import sys
import time

from django.conf import settings
from django.test import TestCase

from analysis.models import WorkflowRun
from loom.common import fixtures
from loom.common.testserver import TestServer


class TestLoomRun(TestCase):

    def setUp(self):
        self.test_server = TestServer()
        self.test_server.start()

    def tearDown(self):
        self.test_server.stop()
        
    """
    def test_create_show_index_immutable(self):
        # Test create
        r = requests.post(self.test_server.server_url+'/api/workflows/', data=json.dumps(fixtures.hello_world_workflow_struct))
        r.raise_for_status()
        self.assertTrue('{"message": "created workflow", "_id":' in r.text)

        # Test show
        id = r.json().get('_id')
        r = requests.get(self.test_server.server_url+'/api/workflows/%s/' % str(id))
        r.raise_for_status()
        self.assertEqual(r.json()['_id'], str(id))

        # Test index
        r = requests.get(self.test_server.server_url+'/api/workflows/')
        r.raise_for_status()
        ids = map(lambda x:x['_id'], r.json()['workflows'])
        self.assertTrue(id in ids)

    def test_create_show_index_update_mutable(self):
        # Test create
        r = requests.post(self.test_server.server_url+'/api/file_storage_locations/', data=json.dumps(fixtures.server_file_storage_location_struct))
        r.raise_for_status()
        self.assertEqual(r.json()['message'], "created file_storage_location")

        # Test show
        id = r.json()['_id']
        r = requests.get(self.test_server.server_url+'/api/file_storage_locations/%s/' % id)
        r.raise_for_status()
        self.assertEqual(r.json()['_id'], id)

        # Test index
        r = requests.get(self.test_server.server_url+'/api/file_storage_locations/')
        r.raise_for_status()
        ids = map(lambda x:x['_id'], r.json()['file_storage_locations'])
        self.assertTrue(id in ids)

        # Test update
        r = requests.post(self.test_server.server_url+'/api/file_storage_locations/%s/' % id, 
                          data='{"file_path": "/new/file/path"}')
        r.raise_for_status()
        r = requests.get(self.test_server.server_url+'/api/file_storage_locations/%s/' % id)
        r.raise_for_status()
        self.assertEqual(r.json()['file_path'], '/new/file/path')

    """
