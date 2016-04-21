#!/usr/bin/env python

import json
import jsonschema
import os
import re

LOOM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

class SettingsManager:
    """
    This class manages loom client, worker, fileserver, and webserver settings.
    Users should interact with this class through 'loom config', with these subcommands:
    - local
    - elasticluster
    - elasticluster_frontend (primarily used by elasticluster setup)
    - savesettings
    - clearsettings

    On first run, settings are saved to the user's home directory in .loom/settings.json.
    By default, this will configure loom for local deployment.
    To switch to elasticluster deployment, run 'loomconfig elasticluster'.
    To switch back to local deployment, run 'loomconfig local'.
    For finer-grained control, .loom/settings.json can be directly edited to set specific values.
    """

    # Instance variables
    settings = None
    settings_file = None
    presets = None
    require_default_settings = False
    verbose = False

    # Constants
    DEFAULT_SETTINGS_FILE = os.path.join(os.getenv('HOME'), '.loom', 'settings.json')
    DEFAULT_REMOTE_USERNAME = 'loom'
    DEFAULT_PRESETS = {
        'CURRENT_PRESET': 'LOCAL_SETTINGS',

        # Client, workers, and master all on local machine
        'LOCAL_SETTINGS': {
            'MASTER_TYPE': 'LOCAL',
            'WEBSERVER_PIDFILE': '/tmp/loom_webserver.pid',
            'BIND_IP': '127.0.0.1',
            'BIND_PORT': '8000',
            'PROTOCOL': 'http',
            'SERVER_WSGI_MODULE': 'loomserver.wsgi',
            'SERVER_PATH': os.path.join(LOOM_ROOT, 'master'),
            'DAEMON_PIDFILE': '/tmp/loom_daemon.pid',
            'ACCESS_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_http_access.log'),
            'ERROR_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_http_error.log'),
            'DJANGO_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_django.log'),
            'WEBSERVER_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_webserver.log'),
            'DAEMON_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_daemon.log'),
            #'LOG_LEVEL': 'INFO',
            'LOG_LEVEL': 'DEBUG',

            # Where to get inputs and place outputs.
            # Valid choices: LOCAL, REMOTE, GOOGLE_CLOUD
            'FILE_SERVER_TYPE': 'LOCAL',
            'FILE_ROOT': os.path.join(os.getenv('HOME'), 'working_dir'),
            'PROJECT_ID': 'unused',
            'BUCKET_ID': 'unused',

            # Info needed by task manager
            'ANSIBLE_PEM_FILE': 'unused',
            'GCE_KEY_FILE': 'unused',
            'WORKER_VM_IMAGE': 'unused',        # image to use when task manager boots up a worker VM
            'WORKER_LOCATION': 'unused',        # location to use when task manager boots up a worker VM
            'WORKER_DISK_TYPE': 'unused',       # worker scratch disk type, pd-ssd or pd-standard
            'WORKER_DISK_SIZE': 'unused',
            'WORKER_DISK_MOUNT_POINT': 'unused',

            # Info needed by workers
            # - MASTER_URL passed as argument to step_runner
            # - FILE_SERVER, FILE_ROOT, WORKER_LOGFILE, and LOG_LEVEL retrieved from
            #   webserver at MASTER_URL by step_runner

            # Workers on same machine as server
            'WORKER_TYPE': 'LOCAL',
            'MASTER_URL_FOR_WORKER': 'http://127.0.0.1:8000',
            'FILE_SERVER_FOR_WORKER': 'localhost',
            'FILE_ROOT_FOR_WORKER': os.path.join(os.getenv('HOME'), 'working_dir'), # Where to create step run directories on the worker
            'WORKER_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_worker.log'),

            # Client on same machine as server
            'CLIENT_TYPE': 'LOCAL',
            'MASTER_URL_FOR_CLIENT': 'http://127.0.0.1:8000',
            'FILE_SERVER_FOR_CLIENT': 'unused', 

            # Needed by both worker and client
            'IMPORT_DIR': 'imported_files',
            'STEP_RUNS_DIR': 'step_runs',
    
            # Not currently used for local mode
            'REMOTE_USERNAME': 'unused'
        },

        # Client, workers, and master all on local machine, fileserver is Google Cloud
        'LOCAL_GOOGLE_STORAGE_SETTINGS': {
            'MASTER_TYPE': 'LOCAL',
            'WEBSERVER_PIDFILE': '/tmp/loom_webserver.pid',
            'BIND_IP': '127.0.0.1',
            'BIND_PORT': '8000',
            'PROTOCOL': 'http',
            'SERVER_WSGI_MODULE': 'loomserver.wsgi',
            'SERVER_PATH': os.path.join(LOOM_ROOT, 'master'),
            'DAEMON_PIDFILE': '/tmp/loom_daemon.pid',
            'ACCESS_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_http_access.log'),
            'ERROR_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_http_error.log'),
            'DJANGO_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_django.log'),
            'WEBSERVER_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_webserver.log'),
            'DAEMON_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_daemon.log'),
            #'LOG_LEVEL': 'INFO',
            'LOG_LEVEL': 'DEBUG',

            # Where to get inputs and place outputs.
            # Valid choices: LOCAL, REMOTE, GOOGLE_CLOUD
            'FILE_SERVER_TYPE': 'GOOGLE_CLOUD',
            'FILE_ROOT': 'loom_working_dir',
            'PROJECT_ID': '<insert-gcloud-project-id-here>',
            'BUCKET_ID': '<insert-gcloud-bucket-id-here>',

            # Info needed by task manager
            'ANSIBLE_PEM_FILE': 'unused',
            'GCE_KEY_FILE': 'unused',
            'WORKER_VM_IMAGE': 'unused',        # image to use when task manager boots up a worker VM
            'WORKER_LOCATION': 'unused',        # location to use when task manager boots up a worker VM
            'WORKER_DISK_TYPE': 'unused',       # worker scratch disk type, pd-ssd or pd-standard
            'WORKER_DISK_SIZE': 'unused',
            'WORKER_DISK_MOUNT_POINT': 'unused',

            # Info needed by workers
            # - MASTER_URL passed as argument to step_runner
            # - FILE_SERVER, FILE_ROOT, WORKER_LOGFILE, and LOG_LEVEL retrieved from
            #   webserver at MASTER_URL by step_runner

            # Workers on same machine as server
            'WORKER_TYPE': 'LOCAL',
            'MASTER_URL_FOR_WORKER': 'http://127.0.0.1:8000',
            'FILE_SERVER_FOR_WORKER': 'unused',
            'FILE_ROOT_FOR_WORKER': os.path.join(os.getenv('HOME'), 'working_dir'),
            'WORKER_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_worker.log'),

            # Client on same machine as server
            'CLIENT_TYPE': 'LOCAL',
            'MASTER_URL_FOR_CLIENT': 'http://127.0.0.1:8000',
            'FILE_SERVER_FOR_CLIENT': 'unused', 

            # Needed by filehandler
            'IMPORT_DIR': 'imported_files',
            'STEP_RUNS_DIR': 'step_runs',
    
            # Not currently used for local mode
            'REMOTE_USERNAME': 'unused'
        },

        # Client on local machine; master, workers, and fileserver in Google Cloud
        'GOOGLE_CLOUD_CLIENT_SETTINGS': {
            'MASTER_TYPE': 'GOOGLE_CLOUD',

            # These are all unused because the master is not on the same machine as the client
            'WEBSERVER_PIDFILE': 'unused',
            'BIND_IP': 'unused',
            'BIND_PORT': '1234567', # not used, but needs a valid value to pass validation
            'PROTOCOL': 'http',     # not used, but needs a valid value to pass validation
            'SERVER_WSGI_MODULE': 'unused',
            'SERVER_PATH': 'unused',
            'DAEMON_PIDFILE': 'unused',
            'ACCESS_LOGFILE': 'unused',
            'ERROR_LOGFILE': 'unused',
            'DJANGO_LOGFILE': 'unused',
            'WEBSERVER_LOGFILE': 'unused',
            'DAEMON_LOGFILE': 'unused',
            #'LOG_LEVEL': 'INFO',
            'LOG_LEVEL': 'DEBUG',

            # Where to get inputs and place outputs.
            # Valid choices: LOCAL, REMOTE, GOOGLE_CLOUD
            'FILE_SERVER_TYPE': 'GOOGLE_CLOUD',
            'FILE_ROOT': 'loom_working_dir',
            'PROJECT_ID': '<insert-gcloud-project-id-here>',
            'BUCKET_ID': '<insert-gcloud-bucket-id-here>',

            # Info needed by task manager; unused because master is on a different machine than client
            'ANSIBLE_PEM_FILE': 'unused',
            'GCE_KEY_FILE': 'unused',
            'WORKER_VM_IMAGE': 'unused',  # image to use when task manager boots up a worker VM
            'WORKER_LOCATION': 'unused',  # location to use when task manager boots up a worker VM
            'WORKER_DISK_TYPE': 'unused', # worker scratch disk type, pd-ssd or pd-standard
            'WORKER_DISK_SIZE': 'unused',
            'WORKER_DISK_MOUNT_POINT': 'unused',

            # Info needed by workers
            # - MASTER_URL passed as argument to step_runner
            # - FILE_SERVER, FILE_ROOT, WORKER_LOGFILE, and LOG_LEVEL retrieved from
            #   webserver at MASTER_URL by step_runner

            # Workers in Google Cloud
            # Valid choices: LOCAL, GOOGLE_CLOUD
            'WORKER_TYPE': 'GOOGLE_CLOUD',
            'MASTER_URL_FOR_WORKER': 'unused',
            'FILE_SERVER_FOR_WORKER': 'unused',
            'FILE_ROOT_FOR_WORKER': 'unused',
            'WORKER_LOGFILE': 'unused',

            # Client outside Google Cloud; master in Google Cloud
            'CLIENT_TYPE': 'unused',
            'MASTER_URL_FOR_CLIENT': 'http://<insert-master-hostname-or-ip-here>',
            'FILE_SERVER_FOR_CLIENT': 'unused', 

            # Needed by filehandler
            'IMPORT_DIR': 'imported_files',
            'STEP_RUNS_DIR': 'step_runs',
            'REMOTE_USERNAME': 'unused'     # Only used by ElasticlusterFileHandler to locate SSH keys on remote host
        },

        # Deploying client and master on same VM in Google Cloud; workers are other VMs in Google Cloud; fileserver is Google Storage
        'GOOGLE_CLOUD_MASTER_SETTINGS': {
            # Info needed by master
            'MASTER_TYPE': 'GOOGLE_CLOUD',
            'WEBSERVER_PIDFILE': '/tmp/loom_webserver.pid',
            'BIND_IP': '0.0.0.0',
            'BIND_PORT': '8000',
            'PROTOCOL': 'http',
            'SERVER_WSGI_MODULE': 'loomserver.wsgi',
            'SERVER_PATH': os.path.join(LOOM_ROOT, 'master'),
            'DAEMON_PIDFILE': '/tmp/loom_daemon.pid',
            'ACCESS_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_http_access.log'),
            'ERROR_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_http_error.log'),
            'DJANGO_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_django.log'),
            'WEBSERVER_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_webserver.log'),
            'DAEMON_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_daemon.log'),
            #'LOG_LEVEL': 'INFO',
            'LOG_LEVEL': 'DEBUG',

            # Info needed by CloudTaskManager
            'ANSIBLE_PEM_FILE': '~/pkey.pem',
            'GCE_KEY_FILE': '~/.ssh/google_compute_engine',
            'WORKER_VM_IMAGE': 'container-vm',  # image to use when task manager boots up a worker VM
            'WORKER_LOCATION': 'us-central1-a', # location to use when task manager boots up a worker VM
            'WORKER_DISK_TYPE': 'pd-ssd',       # worker scratch disk type, pd-ssd or pd-standard
            'WORKER_DISK_SIZE': '10',           # worker scratch disk size in GB
            'WORKER_DISK_MOUNT_POINT': '/mnt/loom_working_dir',

            # Where to get inputs and place outputs.
            # Valid choices: LOCAL, REMOTE, GOOGLE_CLOUD
            'FILE_SERVER_TYPE': 'GOOGLE_CLOUD',
            'FILE_ROOT': 'loom_working_dir',

            # Info needed by workers
            # - MASTER_URL passed as argument to step_runner
            # - FILE_SERVER, FILE_ROOT, WORKER_LOGFILE, and LOG_LEVEL retrieved from
            #   webserver at MASTER_URL by step_runner

            # Workers in Google Cloud
            # Valid choices: LOCAL, GOOGLE_CLOUD
            'WORKER_TYPE': 'GOOGLE_CLOUD',
            'MASTER_URL_FOR_WORKER': 'http://<insert-master-hostname-or-ip-here>',
            'FILE_SERVER_FOR_WORKER': 'unused',
            'FILE_ROOT_FOR_WORKER': '/mnt/loom_working_dir',
            'WORKER_LOGFILE': os.path.join(LOOM_ROOT, 'log', 'loom_worker.log'),

            # Client on same machine as server
            'CLIENT_TYPE': 'LOCAL',
            'MASTER_URL_FOR_CLIENT': 'http://127.0.0.1:8000',
            'FILE_SERVER_FOR_CLIENT': 'unused', 

            # Needed by filehandler
            'IMPORT_DIR': 'imported_files',
            'STEP_RUNS_DIR': 'step_runs',
            'REMOTE_USERNAME': 'unused',     # Only used by ElasticlusterFileHandler to locate SSH keys on remote host

            # Shared by any cloud components
            'PROJECT_ID': '<insert-gcloud-project-id-here>',
            'BUCKET_ID': '<insert-gcloud-bucket-id-here>'
        }
    }

    SETTINGS_SCHEMA = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "type": "object",
        "properties": {
            "MASTER_TYPE": { "enum": ["LOCAL", "GOOGLE_CLOUD"]},
            "BIND_IP": { "type": "string"},
            "BIND_PORT": {"type": "string", "pattern": "^[0-9]+$"},
            "WEBSERVER_PIDFILE": {"type": "string"},
            "PROTOCOL": {"enum": ["http", "https", "HTTP", "HTTPS"]},
            "SERVER_WSGI_MODULE": {"type": "string"},
            "SERVER_PATH": {"type": "string"},
            "DAEMON_PIDFILE": {"type": "string"},
            "ACCESS_LOGFILE": {"type": "string"},
            "ERROR_LOGFILE": {"type": "string"},
            "DJANGO_LOGFILE": {"type": "string"},
            "WEBSERVER_LOGFILE": {"type": "string"},
            "WORKER_LOGFILE": {"type": "string"},
            "DAEMON_LOGFILE": {"type": "string"},
            "LOG_LEVEL": {"type": "string"},
            "WORKER_TYPE": {"type": "string"},
            'MASTER_URL_FOR_WORKER': {"type": "string"},
            'FILE_SERVER_FOR_WORKER': {"type": "string"},
            'FILE_ROOT_FOR_WORKER': {"type": "string"},
            'IMPORT_DIR': {"type": "string"},
            'STEP_RUNS_DIR': {"type": "string"},
            'CLIENT_TYPE': {"type": "string"},
            'MASTER_URL_FOR_CLIENT': {"type": "string"},
            'FILE_SERVER_FOR_CLIENT': {"type": "string"},
            'REMOTE_USERNAME': {"type": "string"},
            'FILE_SERVER_TYPE': {"enum": ["LOCAL", "REMOTE", "GOOGLE_CLOUD"]},
            'FILE_ROOT': {"type": "string"},
            'BUCKET_ID': {"type": "string"},
            'PROJECT_ID': {"type": "string"},
            'ANSIBLE_PEM_FILE': {"type": "string"},
            'GCE_KEY_FILE': {"type": "string"},
            'WORKER_VM_IMAGE': {"type": "string"},
            'WORKER_LOCATION': {"type": "string"},
            'WORKER_DISK_TYPE': {"enum": ["pd-ssd", "pd-standard", "unused"]},
            'WORKER_DISK_SIZE': {"type": "string"},
            'WORKER_DISK_MOUNT_POINT': {"type": "string"},
        },
        "additionalProperties": False
    }

    PRESETS_SCHEMA = {
        "$schema": "http://json-schema.org/draft-04/schema#",
        "type": "object",
        "properties": {
            "CURRENT_PRESET": {"type": "string"},
            "LOCAL_SETTINGS": {"type": "object"},
            "LOCAL_GOOGLE_STORAGE_SETTINGS": {"type": "object"},
            "GOOGLE_CLOUD_CLIENT_SETTINGS": {"type": "object"},
            "GOOGLE_CLOUD_MASTER_SETTINGS": {"type": "object"},
        },
        "additionalProperties": False
    }
    

    def __init__(self, **kwargs):
        if not self._do_skip_init(**kwargs):
            self._initialize(**kwargs)

    def _do_skip_init(self, **kwargs):
        try:
            skip_init = kwargs.pop('skip_init')
        except KeyError:
            skip_init = False
        return skip_init

    def _initialize(self, settings_file=None, require_default_settings=False, verbose=False, save_settings=True):
        self.verbose = verbose
        self.settings_file = settings_file
        self.require_default_settings = require_default_settings

        if self.settings_file is None:
            self.settings_file = SettingsManager.DEFAULT_SETTINGS_FILE

        if os.path.exists(self.settings_file) and not self.require_default_settings:
            self.load_settings_from_file()
        else:
            self.load_settings_from_presets(SettingsManager.DEFAULT_PRESETS)
            if save_settings:
                self.save_settings_to_file()

        # Get IP's from elasticluster if needed
        if self.settings['CLIENT_TYPE'] == 'OUTSIDE_ELASTICLUSTER':
            self._update_elasticluster_frontend_ip()

    def load_settings_from_presets(self, dirty_presets):
            self.presets = SettingsManager._clean_presets(dirty_presets)
            dirty_settings = SettingsManager._get_current_preset(self.presets)
            self.settings = SettingsManager._clean_settings(dirty_settings)

    def load_settings_from_file(self):
        try:
            with open(self.settings_file, 'r') as f:
                self.load_settings_from_presets(json.load(f))
                if self.verbose:
                    print "Loaded settings from %s." % self.settings_file
        except IOError as e:
            raise Exception("Failed to open the settings file %s" % self.settings_file)
        except ValueError:
            raise Exception("Failed to parse the settings file because it is not in valid JSON format.")

    @staticmethod
    def _get_current_preset(presets):
        """Look up and return the current preset from a dict of presets."""
        current_preset_key = presets['CURRENT_PRESET']
        return presets[current_preset_key].copy()

    @staticmethod
    def _get_default_settings():
        settings = SettingsManager._get_current_preset(SettingsManager.PRESETS)
        return settings

    def _update_elasticluster_frontend_ip(self):
        """Update settings with the elasticluster frontend IP, and also write to presets."""
        frontend_ip = self._get_elasticluster_frontend_ip()
        self.settings['FILE_SERVER_FOR_CLIENT'] = frontend_ip
        self.settings['MASTER_URL_FOR_CLIENT'] = "http://%s:8000" % frontend_ip
        
        current_preset_key = self.presets['CURRENT_PRESET']
        self.presets[current_preset_key] = self.settings

    @staticmethod
    def _get_elasticluster_frontend_ip():
        """Gets external IP of frontend node from Ansible inventory file.

        Preconditions:
        - Inventory file is in default location ($HOME/.elasticluster/storage)
        - User only has one cluster running through elasticluster (TODO: support multiple clusters by taking cluster name as input)
        - LOOM webserver and fileserver are on frontend001
        """
        inventory_search_path = os.path.join(os.getenv('HOME'), '.elasticluster', 'storage', 'ansible-inventory.*')
        import glob
        inventory_files = glob.glob(inventory_search_path)

        if len(inventory_files) > 1:
            raise Exception("More than one running cluster found, don't know which to target!")
        if len(inventory_files) < 1:
            raise Exception("Ansible inventory file not found in default location %s" % inventory_search_path)
        
        inventory_file = inventory_files[0]
        
        with open(inventory_file) as f:
            for line in f:
                match = re.match(r"frontend001 ansible_ssh_host=([\d.]+)", line) # matches IP address of frontend node
                if match:
                    ip = match.group(1) 
                    return ip
            raise Exception("No entry for frontend001 found in Ansible inventory file %s" % inventory_file)

    @staticmethod
    def _clean_settings(settings):
        jsonschema.validate(settings, SettingsManager.SETTINGS_SCHEMA)
        return settings

    @staticmethod
    def _clean_presets(presets):
        jsonschema.validate(presets, SettingsManager.PRESETS_SCHEMA)
        return presets

    def get_server_url_for_worker(self):
        return self.settings['MASTER_URL_FOR_WORKER']
        #return "%s://%s:%s" % (
        #    self.SETTINGS['PROTOCOL'], 
        #    self.SETTINGS['BIND_IP'], 
        #    self.SETTINGS['BIND_PORT']
        #)

    def get_server_url_for_client(self):
        return self.settings['MASTER_URL_FOR_CLIENT']

    def get_server_wsgi_module(self):
        return self.settings['SERVER_WSGI_MODULE']

    def get_bind_ip(self):
        return self.settings['BIND_IP']

    def get_bind_port(self):
        return self.settings['BIND_PORT']

    def get_access_logfile(self):
        return self.settings['ACCESS_LOGFILE']

    def get_error_logfile(self):
        return self.settings['ERROR_LOGFILE']

    def get_log_level(self):
        return self.settings['LOG_LEVEL']

    def get_webserver_pidfile(self):
        return self.settings['WEBSERVER_PIDFILE']

    def get_webserver_pid(self):
        return self._get_pid(self.get_webserver_pidfile())

    def get_daemon_logfile(self):
        return self.settings['DAEMON_LOGFILE']

    def get_daemon_pidfile(self):
        return self.settings['DAEMON_PIDFILE']

    def get_daemon_pid(self):
        return self._get_pid(self.get_daemon_pidfile())

    def get_file_server_type(self):
        return self.settings['FILE_SERVER_TYPE']

    def get_file_server_for_worker(self):
        return self.settings['FILE_SERVER_FOR_WORKER']

    def get_file_server_for_client(self):
        return self.settings['FILE_SERVER_FOR_CLIENT']

    def get_file_root(self):
        return self.settings['FILE_ROOT']

    def get_import_dir(self):
        return self.settings['IMPORT_DIR']

    def get_client_type(self):
        return self.settings['CLIENT_TYPE']

    def _get_pid(self, pidfile):
        if not os.path.exists(pidfile):
            return None
        try:
            with open(pidfile) as f:
                pid = f.read().strip()
                self._validate_pid(pid)
                return pid
        except:
            return None

    def _validate_pid(self, pid):
        if not re.match('^[0-9]*$', pid):
            raise Exception('Invalid pid "%s" found in pidfile %s' % (pid, pidfile))

    def get_remote_username(self):
        return self.settings['REMOTE_USERNAME']

    def get_server_path(self):
        return self.settings['SERVER_PATH']

    
    def save_settings_to_file(self):
        self.make_settings_directory()
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.presets, f, sort_keys=True, indent=2, separators=(',', ': '))
                if self.verbose:
                    print "Saved settings to file %s." % self.settings_file
        except Exception as e:
            print "Failed to save settings to %s. (%s)." % (self.settings_file, e)


    def make_settings_directory(self):
        if os.path.exists(os.path.dirname(self.settings_file)):
            return
        else:
            try:
                os.makedirs(os.path.dirname(self.settings_file))
                if self.verbose:
                    print "Created directory %s." % os.path.dirname(self.settings_file)
            except Exception as e:
                raise Exception("Failed to create directory for the settings file %s (%s)" % (os.path.dirname(self.settings_file), e))

    def delete_saved_settings(self):
        try:
            if self.settings_file is None:
                self.settings_file = SettingsManager.DEFAULT_SETTINGS_FILE
            os.remove(self.settings_file)
            if self.verbose:
                print "Removed settings file %s." % settings_file
            self.remove_dir_if_empty(os.path.dirname(self.settings_file))
        except OSError as e:
            raise Exception("No settings file to delete at %s. (%s)" % (self.settings_file, e))

    def remove_dir_if_empty(self, dirpath):
        if os.listdir(dirpath) == []:
            os.rmdir(dirpath)
            if self.verbose:
                print "Removed empty directory %s." % dirpath

    def get_django_env_settings(self):
        """
        These are settings that will be passed out as environment variables before launching 
        the webserver. This allows master/loomserver/settings.py to use these settings.
        Passing settings this way only works if the webserver is on the same machine as the
        client launching it.

        TODO: decide how to pass settings to Django server when client is on a different machine
        """
        export_settings = {}
        setting_keys_to_export = [
            'DJANGO_LOGFILE',
            'WEBSERVER_LOGFILE',
            'WORKER_LOGFILE',
            'LOG_LEVEL',
            'WORKER_TYPE',
            'MASTER_URL_FOR_WORKER',
            'FILE_SERVER_FOR_WORKER',
            'FILE_ROOT_FOR_WORKER',
            'MASTER_URL_FOR_CLIENT',
            'FILE_SERVER_FOR_CLIENT',
            'FILE_SERVER_TYPE',
            'FILE_ROOT',
            'IMPORT_DIR',
            'STEP_RUNS_DIR',
            'BUCKET_ID',
            'PROJECT_ID',
            'ANSIBLE_PEM_FILE',
            'GCE_KEY_FILE',
            'WORKER_VM_IMAGE',
            'WORKER_LOCATION',
            'WORKER_DISK_TYPE',
            'WORKER_DISK_SIZE',
            'WORKER_DISK_MOUNT_POINT',
            ]
        for key in setting_keys_to_export:
            value = self.settings.get(key)
            if value is not None:
                export_settings[key] = value
        return export_settings

    def set_local(self):
        self.presets['CURRENT_PRESET'] = 'LOCAL_SETTINGS'
        self.save_settings_to_file()

    def set_local_gcloud(self):
        self.presets['CURRENT_PRESET'] = 'LOCAL_GOOGLE_STORAGE_SETTINGS'
        self.save_settings_to_file()

    def set_gcloud_master(self):
        """ Intended for deploying Loom master in Google Cloud."""
        self.presets['CURRENT_PRESET'] = 'GOOGLE_CLOUD_MASTER_SETTINGS'
        self.save_settings_to_file()

    def set_gcloud_client(self):
        self.presets['CURRENT_PRESET'] = 'GOOGLE_CLOUD_CLIENT_SETTINGS'
        self.save_settings_to_file()
