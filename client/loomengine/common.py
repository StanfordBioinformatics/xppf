import argparse
import ConfigParser
import distutils
import googleapiclient.discovery
import imp
import io
import json
import oauth2client.client
import os
import re
import requests
from StringIO import StringIO
import subprocess
import sys
import time
import yaml

import loomengine_utils.connection

LOOM_SETTINGS_SUBDIR = '.loom'
LOOM_SETTINGS_HOME = os.path.expanduser(
    os.getenv('LOOM_SETTINGS_HOME', '~/'+LOOM_SETTINGS_SUBDIR))
LOOM_CONNECTION_FILES_DIR = os.path.join(
    LOOM_SETTINGS_HOME, 'connection-files')
LOOM_CONNECTION_SETTINGS_FILE = 'client-connection-settings.conf'
LOOM_TOKEN_FILE = 'token.txt'


def parse_settings_file(settings_file):
    # dummy section name because ConfigParser needs sections
    PARSER_SECTION = 'settings'
    parser = ConfigParser.SafeConfigParser()
    # preserve uppercase in settings names
    parser.optionxform = lambda option: option.upper()
    try:
        with open(settings_file) as stream:
            # Add a section, since ConfigParser requires it
            stream = StringIO("[%s]\n" % PARSER_SECTION + stream.read())
            parser.readfp(stream)
    except IOError:
        raise SystemExit(
            'ERROR! Could not open file to read settings at "%s".'
            % settings_file)
    except ConfigParser.ParsingError as e:
        raise SystemExit(
            'ERROR! Could not parse settings in file "%s".\n %s'
            % (settings_file, e.message))
    if parser.sections() != [PARSER_SECTION]:
        raise SystemExit(
            'ERROR! Found extra sections in settings file: "%s". '
            'Sections are not needed.' % parser.sections())
    return dict(parser.items(PARSER_SECTION))


def write_settings_file(settings_file, settings):
    with open(settings_file, 'w') as f:
        for key, value in sorted(settings.items()):
            f.write('%s=%s\n' % (key, value))


def has_connection_settings():
    return os.path.exists(os.path.join(
        LOOM_SETTINGS_HOME, LOOM_CONNECTION_SETTINGS_FILE))


def verify_has_connection_settings():
    if not has_connection_settings():
        raise SystemExit(
            'ERROR! Not connected to any server. First start a new server '
            'or connect to an existing server.')


def get_server_url():
    connection_settings = parse_settings_file(
        os.path.join(LOOM_SETTINGS_HOME, LOOM_CONNECTION_SETTINGS_FILE))
    return connection_settings.get('LOOM_SERVER_URL')


def is_server_running(url=None):
    if not url:
        url = get_server_url()

    try:
        loomengine_utils.connection.disable_insecure_request_warning()
        response = requests.get(url + '/api/status/', verify=False, timeout=30)
    except requests.exceptions.ConnectionError:
        return False

    if response.status_code == 200:
        return True
    else:
        raise SystemExit(
            'ERROR! Unexpected status code "%s" from server'
            % response.status_code)


def verify_server_is_running(url=None):
    if not is_server_running(url=url):
        raise SystemExit('ERROR! No response from server at %s' % url)


SSL_CERT_PATH = os.path.expanduser(os.path.join(LOOM_SETTINGS_HOME, 'ssl.crt'))
SSL_KEY_PATH = os.path.expanduser(os.path.join(LOOM_SETTINGS_HOME, 'ssl.key'))
GCE_INI_PATH = os.path.join(LOOM_SETTINGS_HOME, 'gce.ini')
GCE_JSON_PATH = os.path.join(LOOM_SETTINGS_HOME, 'gce_key.json')
GCE_PY_PATH = os.path.join(imp.find_module('loomengine')[1], 'utils', 'gce.py')
SERVER_PATH = os.path.join(imp.find_module('loomengine')[1], 'master')


def get_server_type():
    """Checks server.ini for server type."""
    server_location_file = os.path.expanduser(SERVER_LOCATION_FILE)
    if not os.path.exists(server_location_file):
        raise Exception(
            "%s not found. Please run 'loom server set "
            "<servertype>' first." % server_location_file)
    config = ConfigParser.SafeConfigParser()
    config.read(server_location_file)
    server_type = config.get('server', 'type')
    return server_type


def get_gcloud_server_name():
    """Reads and returns gcloud server instance name from server.ini."""
    server_location_file = os.path.expanduser(SERVER_LOCATION_FILE)
    if not os.path.exists(server_location_file):
        raise Exception(
            "%s not found. Please run 'loom server set "
            "<servertype>' first." % server_location_file)
    config = ConfigParser.SafeConfigParser()
    config.read(server_location_file)
    server_type = config.get('server', 'type')
    if server_type != 'gcloud':
        raise Exception(
            "Tried to get gcloud instance name, but %s is not "
            "configured for gcloud." % server_location_file)
    server_name = config.get('server', 'name')
    return server_name


def get_inventory():
    gce_ini_path = os.path.expanduser(GCE_INI_PATH)
    gce_py_path = os.path.expanduser(GCE_PY_PATH)
    env = os.environ.copy()
    env['GCE_INI_PATH'] = gce_ini_path
    if not os.path.exists(gce_ini_path):
        raise Exception(
            "%s not found. Please configure "
            "https://github.com/ansible/ansible/blob/devel"
            "/contrib/inventory/gce.ini and place it at this location."
            % GCE_INI_PATH)

    try:
        inv = subprocess.check_output(
            [sys.executable, gce_py_path], env=env)
        inv = json.loads(inv)
        return inv
    except subprocess.CalledProcessError as e:
        print e


def delete_token():
    token_path = os.path.join(LOOM_SETTINGS_HOME, LOOM_TOKEN_FILE)
    if os.path.exists(token_path):
        os.remove(token_path)


def save_token(token):
    delete_token()
    with open(os.path.join(LOOM_SETTINGS_HOME, LOOM_TOKEN_FILE), 'w') as f:
        f.write(token)


def get_token():
    token_path = os.path.join(LOOM_SETTINGS_HOME, LOOM_TOKEN_FILE)
    if os.path.exists(token_path):
        with open(token_path) as f:
            token = f.read()
    else:
        token = None
    return token
