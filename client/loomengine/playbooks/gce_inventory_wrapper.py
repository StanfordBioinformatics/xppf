#!/usr/bin/env python
import os
import subprocess
import copy
import json
import random
import sys
import time

inventory_file = os.path.join(os.path.dirname(
    os.path.abspath(__file__)),
                              'gce.py')

env = copy.deepcopy(os.environ)


def get_required_setting(setting):
    try:
        return env[setting]
    except KeyError:
        raise Exception('Missing setting %s' % setting)


LOOM_SETTINGS_HOME = get_required_setting('LOOM_SETTINGS_HOME')
LOOM_RESOURCE_DIR = get_required_setting('LOOM_RESOURCE_DIR')
LOOM_GCE_PEM_FILE = get_required_setting('LOOM_GCE_PEM_FILE')

GCE_PEM_FILE_PATH = os.path.join(LOOM_SETTINGS_HOME,
                                 LOOM_RESOURCE_DIR, LOOM_GCE_PEM_FILE)

if not os.path.exists(GCE_PEM_FILE_PATH):
    raise Exception(
        GCE_PEM_FILE_PATH + ' not found. Did you forget the '
        '--resource-dir argument? If not, please provide the '
        'full path to the credential file in settings.')

with open(GCE_PEM_FILE_PATH, 'r') as f:
    key_json = json.load(f)

GCE_EMAIL = key_json.get('client_email')
GCE_PROJECT = key_json.get('project_id')


# get pem file path from variables "settings-dir",
# "admin-files", "gce_pem_file"
# extract email
# extract project

env.update({
    'GCE_PROJECT': GCE_PROJECT,
    'GCE_PEM_FILE_PATH': GCE_PEM_FILE_PATH,
    'GCE_EMAIL': GCE_EMAIL,
})

max_retries = 10
attempt = 0

while True:
    try:
        inventory = subprocess.check_output([inventory_file], env=env)
        # Make sure the result is a valid JSON, otherwise raises ValueError
        json.loads(inventory)
        print inventory
        sys.exit(0)
    except Exception as e:
        attempt += 1
        if attempt > max_retries:
            raise
        # Exponential backoff on retry delay as suggested by
        # https://cloud.google.com/storage/docs/exponential-backoff
        delay = 2**attempt + random.random()
        sys.stderr.write('Error executing inventory file %s: %s\n' % (
            inventory_file, str(e)))
        sys.stderr.write('Retry number %s of %s in %s seconds\n' % (
            attempt, max_retries, delay))
        time.sleep(delay)
