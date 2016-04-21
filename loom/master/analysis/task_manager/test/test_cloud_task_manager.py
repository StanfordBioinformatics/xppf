#!/usr/bin/env python
import socket
import sys
import unittest
from collections import namedtuple

from django.conf import settings

from loom.master.analysis.task_manager.cloud import CloudTaskManager
from loom.master.analysis.task_manager.cloud import CloudTaskManagerError
from loom.common.cloud import on_gcloud_vm


@unittest.skipIf(not on_gcloud_vm(), 'not running on Google Compute Engine VM')
class TestCloudTaskManager(unittest.TestCase):

    class Resources:
        cores=''
        memory=''

    class TaskRun:
        _id=''

    resources=Resources()

    @classmethod
    def setUpClass(cls):
        if not settings.configured:
            settings.configure()

    @classmethod
    def tearDownClass(cls):
        #CloudTaskManager._delete_node('unittest-cloud-task-manager-run')
        pass
        
    def setUp(self):
        myip = socket.gethostbyname(socket.getfqdn())
        settings.MASTER_URL_FOR_WORKER = 'http://' + myip
        settings.PROJECT_ID = 'gbsc-gcp-project-scgs-dev'
        settings.ANSIBLE_PEM_FILE = '~/key.pem'
        settings.GCE_KEY_FILE = '~/.ssh/google_compute_engine'
        settings.WORKER_TYPE = 'GOOGLE_CLOUD'
        settings.WORKER_VM_IMAGE = 'container-vm'
        settings.WORKER_LOCATION = 'us-central1-a'
        settings.WORKER_DISK_TYPE = 'pd-ssd'
        settings.WORKER_DISK_SIZE = '100'
        settings.WORKER_DISK_MOUNT_POINT = '/mnt/loom_working_dir'
        self.resources.cores=1
        self.resources.memory=1

    def tearDown(self):
        pass

    def test_invalid_cloud_type(self):
        settings.WORKER_TYPE = 'INVALID_CLOUD_TYPE'

        with self.assertRaises(CloudTaskManagerError):
            CloudTaskManager._run('task-run-id', 'task-run-location-id', self.resources)

    def test_get_gcloud_pricelist(self):
        pricelist = CloudTaskManager._get_gcloud_pricelist()
        self.assertIsInstance(pricelist, dict)

    def test_get_cheapest_instance_type(self):
        """ May need to be updated if prices change.""" 
        cheapest_type = CloudTaskManager._get_cheapest_instance_type(cores=1, memory=4)
        self.assertEquals(cheapest_type, 'n1-standard-2')
        
    def test_huge_instance_request(self):
        """ May need to be updated if Google starts offering supercomputer instances.""" 
        with self.assertRaises(CloudTaskManagerError):
            CloudTaskManager._get_cheapest_instance_type(cores=sys.maxint, memory=sys.float_info.max)

    def test_setup_ansible_gce(self):
        CloudTaskManager._setup_ansible_gce()
        import secrets
        self.assertIsInstance(secrets.GCE_PARAMS, tuple)
        self.assertIsInstance(secrets.GCE_KEYWORD_PARAMS, dict)

    #@unittest.skip('Skipping VM task run test')
    def test_run(self):
        CloudTaskManager._run(task_run_id='unittest-task-run-id', task_run_location_id='unittest-task-run-location-id', requested_resources=self.resources)

if __name__ == '__main__':
    unittest.main()
