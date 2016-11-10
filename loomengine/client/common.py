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
import subprocess
import sys
import time
import yaml

import loomengine.client.settings_manager
import loomengine.utils.connection
from loomengine.client import exceptions
from loomengine.utils.exceptions import ServerConnectionError

LOOM_HOME_SUBDIR = '.loom'
LOOM_SETTINGS_PATH = os.path.join('~', LOOM_HOME_SUBDIR)
SERVER_LOCATION_FILE = os.path.join(LOOM_SETTINGS_PATH, 'server.ini')
SSL_CERT_PATH = os.path.expanduser(os.path.join(LOOM_SETTINGS_PATH, 'ssl.crt'))
SSL_KEY_PATH = os.path.expanduser(os.path.join(LOOM_SETTINGS_PATH, 'ssl.key'))
GCE_INI_PATH = os.path.join(LOOM_SETTINGS_PATH, 'gce.ini')
GCE_JSON_PATH = os.path.join(LOOM_SETTINGS_PATH, 'gce_key.json')
GCE_PY_PATH = os.path.join(imp.find_module('loomengine')[1], 'utils', 'gce.py')
SERVER_PATH = os.path.join(imp.find_module('loomengine')[1], 'master')

def get_server_type():
    """Checks server.ini for server type."""
    server_location_file = os.path.expanduser(SERVER_LOCATION_FILE)
    if not os.path.exists(server_location_file):
        raise Exception("%s not found. Please run 'loom server set <servertype>' first." % server_location_file)
    config = ConfigParser.SafeConfigParser()
    config.read(server_location_file)
    server_type = config.get('server', 'type')
    return server_type

def get_gcloud_server_name():
    """Reads and returns gcloud server instance name from server.ini."""
    server_location_file = os.path.expanduser(SERVER_LOCATION_FILE)
    if not os.path.exists(server_location_file):
        raise Exception("%s not found. Please run 'loom server set <servertype>' first." % server_location_file)
    config = ConfigParser.SafeConfigParser()
    config.read(server_location_file)
    server_type = config.get('server', 'type')
    if server_type != 'gcloud':
        raise Exception("Tried to get gcloud instance name, but %s is not configured for gcloud." % server_location_file)
    server_name = config.get('server', 'name')
    return server_name

def validate_gcloud_label(label):
    """Many identifiers in gcloud must conform to RFC 1035."""
    if len(label) > 63 or len(label) < 6:
        raise Exception('Identifier is not 6-63 characters long: %s' % label)
    result = re.match('[a-z]([-a-z0-9]*[a-z0-9])', label)
    if result == None:
        raise Exception('Identifier does not match regular expression [a-z]([-a-z0-9]*[a-z0-9]): %s' % label)

def validate_gcloud_service_account_id(account_id):
    validate_gcloud_label(account_id)

def validate_gcloud_instance_name(name):
    validate_gcloud_label(name)

def get_server_public_ip():
    server_type = get_server_type()
    if server_type == 'local':
        return '127.0.0.1'
    elif server_type == 'gcloud':
        server_instance_name = get_gcloud_server_name()
        return get_gcloud_server_public_ip(server_instance_name)
    else:
        raise Exception("Unknown server type: %s" % server_type)

def get_server_private_ip():
    server_type = get_server_type()
    if server_type == 'local':
        return '127.0.0.1'
    elif server_type == 'gcloud':
        server_instance_name = get_gcloud_server_name()
        return get_gcloud_server_private_ip(server_instance_name)
    else:
        raise Exception("Unknown server type: %s" % server_type)

def get_gcloud_server_public_ip(name):
    inv_hosts = get_gcloud_hosts()
    if name not in inv_hosts:
        raise Exception("%s not found in Ansible dynamic inventory. Current hosts: %s" % (name, inv_hosts.keys()))
    ip = inv_hosts[name]['gce_public_ip'].encode('utf-8')
    return ip

def get_gcloud_server_private_ip(name):
    inv_hosts = get_gcloud_hosts()
    if name not in inv_hosts:
        raise Exception("%s not found in Ansible dynamic inventory. Current hosts: %s" % (name, inv_hosts.keys()))
    ip = inv_hosts[name]['gce_private_ip'].encode('utf-8')
    return ip

def get_inventory():
    gce_ini_path = os.path.expanduser(GCE_INI_PATH)
    gce_py_path = os.path.expanduser(GCE_PY_PATH)
    env = os.environ.copy()
    env['GCE_INI_PATH'] = gce_ini_path
    if not os.path.exists(gce_ini_path):
        raise Exception("%s not found. Please configure https://github.com/ansible/ansible/blob/devel/contrib/inventory/gce.ini and place it at this location." % GCE_INI_PATH)

    try:
        inv = subprocess.check_output([sys.executable, gce_py_path], env=env)
        inv = json.loads(inv)
        return inv
    except subprocess.CalledProcessError as e:
        print e

def get_gcloud_hosts():
    inv = get_inventory()
    inv_hosts = inv['_meta']['hostvars']
    return inv_hosts

def get_server_url():
    # TODO: add PROTOCOL and EXTERNAL PORT to server.ini since they are required to construct a URL to reach the server
    # Consider how to keep in sync with user-provided settings, default_settings.ini, and _deploy_settings.ini
    # Would remove dependency on settings_manager from other components
    try:
        settings = loomengine.client.settings_manager.read_deploy_settings_file()
    except:
        raise Exception("Could not open server deploy settings. Do you need to run \"loom server create\" first?")
    protocol = settings['PROTOCOL']
    if settings.get('CLIENT_USES_SERVER_INTERNAL_IP') == 'True':
        ip = get_server_private_ip()
    else:
        ip = get_server_public_ip()
    port = settings['EXTERNAL_PORT']
    return '%s://%s:%s' % (protocol, ip, port)

def is_server_running():
    try:
        loomengine.utils.connection.disable_insecure_request_warning()
        #response = requests.get(get_server_url() + '/api/status/', cert=(SSL_CERT_PATH, SSL_KEY_PATH)) 
        response = requests.get(get_server_url() + '/api/status/', verify=False)
    except requests.exceptions.ConnectionError:
        return False

    if response.status_code == 200:
        return True
    else:
        raise Exception("Unexpected status code %s from server" % response.status_code)

def verify_server_is_running():
    if not is_server_running():
        raise exceptions.ServerConnectionError('The Loom server is not currently running at %s. Try launching the web server with "loom server start".' % get_server_url())

def get_gcloud_project():
    """Queries gcloud CLI for current project."""
    check_for_gcloud()
    gcloud_output = subprocess.check_output(['gcloud', 'config', 'list'])
    gcloud_output_fp = io.StringIO(unicode(gcloud_output))
    config = ConfigParser.SafeConfigParser()
    try:
        config.readfp(gcloud_output_fp)
        project = str(config.get('core', 'project'))
        return project
    except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
        print 'Could not retrieve project id from gcloud. Please run "gcloud init" or "gcloud config set project <project_id>".'

def check_for_gcloud():
    """Check if gcloud CLI is installed."""
    if not distutils.spawn.find_executable('gcloud'):
        raise Exception('Google Cloud SDK not found. Please install it from: https://cloud.google.com/sdk/')

def create_gce_ini(email=None):
    if not is_gce_json_valid():
        raise Exception('Credential %s does not exist or is not valid for the current project. Please run "gcloud init" and ensure that the correct project is selected.' % GCE_JSON_PATH)
    project = get_gcloud_project()
    server_name = get_gcloud_server_name()
    if email==None:
        service_account_email = find_service_account_email(server_name)
    else:
        service_account_email = email

    print 'Creating %s...' % GCE_INI_PATH
    config = ConfigParser.SafeConfigParser()
    config.add_section('gce')
    config.set('gce', 'gce_project_id', project)
    config.set('gce', 'gce_service_account_email_address', service_account_email)
    config.set('gce', 'gce_service_account_pem_file_path', GCE_JSON_PATH)
    with open(os.path.expanduser(GCE_INI_PATH), 'w') as configfile:
        config.write(configfile)
    delete_libcloud_cached_credential() # Ensures that downstream steps get a new token with updated service account

def create_gce_json(email=None):
    project = get_gcloud_project()
    if email==None:
        service_account_email = find_service_account_email(get_gcloud_server_name())
    else:
        service_account_email = email

    print 'Creating %s...' % GCE_JSON_PATH
    create_service_account_key(project, service_account_email, GCE_JSON_PATH)

def create_service_account_key(project, email, path):
    """Creates a service account key in the provided project, using the provided
    service account email, and saves it to the provided path.
    """
    iam_service = get_iam_service()
    request = iam_service.projects().serviceAccounts().keys().create(name='projects/%s/serviceAccounts/%s' % (project, email), body={})
    response = request.execute()
    credential_filestring = response['privateKeyData'].decode('base64')
    with open(os.path.expanduser(path), 'w') as credential_file:
        credential_file.write(credential_filestring)

def is_gce_ini_valid():
    """Makes sure that gce.ini exists, and that its project id matches gcloud CLI's."""
    if not os.path.exists(os.path.expanduser(GCE_INI_PATH)):
        return False

    config = ConfigParser.SafeConfigParser()
    config.read(os.path.expanduser(GCE_INI_PATH))
    ini_project = config.get('gce', 'gce_project_id')
    current_project = get_gcloud_project()

    if current_project == ini_project:
        return True
    else:
        return False

def is_gce_json_valid():
    """Makes sure that gce_key.json exists, and that its project id matches gcloud CLI's."""
    if not os.path.exists(os.path.expanduser(GCE_JSON_PATH)):
        return False

    json_project = json.load(open(os.path.expanduser(GCE_JSON_PATH)))['project_id']
    current_project = get_gcloud_project()

    if current_project == json_project:
        return True
    else:
        return False

def is_dev_install():
    """Checks if the client is installed in development mode by looking for a
    Dockerfile in the parent dir of the loom package. This means:
    - we can build a Loom Docker image
    - we have setup.py
    - we have /doc/examples
    - we are probably a Git checkout
    """ 
    dockerfile_path = os.path.join(os.path.dirname(imp.find_module('loomengine')[1]), 'Dockerfile')
    return os.path.exists(dockerfile_path)

def create_service_account(account_id):
    """Creates a service account in the current project using the provided id.
    """
    validate_gcloud_service_account_id(account_id)

    iam_service = get_iam_service()
    project = get_gcloud_project()
    display_name = account_id               # Note: display name is not guaranteed to be unique in project
    request_body =  {"serviceAccount": { "displayName": display_name}, "accountId": account_id}

    request = iam_service.projects().serviceAccounts().create(name='projects/%s' % project, body=request_body)
    response = request.execute()
    return response

def delete_service_account(account_email):
    """Deletes the service account in the current project with the provided email."""
    iam_service = get_iam_service()
    project = get_gcloud_project()

    request = iam_service.projects().serviceAccounts().delete(name='projects/%s/serviceAccounts/%s' % (project, account_email))
    response = request.execute()
    return response

def list_service_accounts():
    """Lists service accounts in the current project."""
    iam_service = get_iam_service()
    project = get_gcloud_project()

    request = iam_service.projects().serviceAccounts().list(name='projects/%s' % project)
    response = request.execute()
    return response['accounts']

def find_service_account_email(account_id=None):
    """Looks for a service account email in the current project using the
    provided account id. If none provided, defaults to current instance name.
    Matches the specified ID to the email username (before the @). If more than
    one match, raise an error since we don't know which email is the right one. 
    """
    if account_id == None:
        account_id = get_gcloud_server_name()
    accounts = list_service_accounts()
    emails = []
    for account in accounts:
        email = account['email']
        if email.split('@')[0] == account_id:
            emails.append(email)
    if len(emails) == 1:
        return emails[0]
    elif len(emails) > 1:
        raise Exception('More than one service account email matches account ID: %s' % account_id)
    elif len(emails) < 1:
        return None

def get_serviceaccount_policy(email=None):
    """Gets the IAM policy for the provided service account email in the current
    project. If no email provided, defaults to account for the current instance.
    """
    if email == None:
        email = find_service_account_email()

    iam_service = get_iam_service()
    project = get_gcloud_project()
    request = iam_service.projects().serviceAccounts().getIamPolicy(resource='projects/%s/serviceAccounts/%s' % (project, email))
    response = request.execute()
    return response

def get_project_policy(project=None):
    """Gets the IAM policy for the specified project. If none specified,
    defaults to current project.
    """
    if project == None:
        project = get_gcloud_project()

    crm_service = get_crm_service()
    request = crm_service.projects().getIamPolicy(resource='%s' % project, body={})
    response = request.execute()
    return response

def set_project_policy(policy, project=None):
    """Sets the IAM policy for the specified project. If no project specified,
    defaults to current project.
    """
    if project == None:
        project = get_gcloud_project()

    crm_service = get_crm_service()
    request = crm_service.projects().setIamPolicy(resource='%s' % project, body=policy)
    response = request.execute()
    return response

def grant_roles(roles, email=None):
    """Grants the specified roles to the specified service account in the current 
    project. If no email provided, defaults to account for the current instance.
    """
    if email == None:
        email = find_service_account_email()

    project = get_gcloud_project()

    # Set policy on service account

    # iam_service = get_iam_service()

    # bindings = []
    # for role in roles:
    #     bindings.append({"role": role, "members": ["serviceAccount:%s" % email]})

    # request_body = {"policy": {"bindings": bindings}}
    # request = iam_service.projects().serviceAccounts().setIamPolicy(resource='projects/%s/serviceAccounts/%s' % (project, email), body=request_body)
    # response = request.execute()

    # Set policy on project
    policy = get_project_policy(project)
    jsonfilename = os.path.expanduser(os.path.join(LOOM_SETTINGS_PATH, 'policy-%s.json' % time.strftime("%Y%m%d-%H%M%S")))
    with open(jsonfilename, 'w') as jsonfile:
        json.dump(policy, jsonfile)
    print 'Current project policy saved to %s' % jsonfilename
    added_roles = []
    for binding in policy['bindings']:
        if binding['role'] in roles:
            binding['members'].append('serviceAccount:%s' % email)
            added_roles.append(binding['role']) # mark as added
    # if any specified roles not added, create and add new binding
    for role in roles:
        if role not in added_roles:
            policy['bindings'].append({"role":role, "members": ["serviceAccount:%s" % email]})
    set_project_policy({"policy": policy}, project)
    
def get_iam_service():
    try:
        credentials = oauth2client.client.GoogleCredentials.get_application_default()
    except oauth2client.client.ApplicationDefaultCredentialsError:
        raise Exception('Could not get credentials from Google Cloud SDK. Please run "gcloud init" first.')

    iam_service = googleapiclient.discovery.build('iam', 'v1', credentials=credentials)
    return iam_service

def get_crm_service():
    try:
        credentials = oauth2client.client.GoogleCredentials.get_application_default()
    except oauth2client.client.ApplicationDefaultCredentialsError:
        raise Exception('Could not get credentials from Google Cloud SDK. Please run "gcloud init" first.')

    crm_service = googleapiclient.discovery.build('cloudresourcemanager', 'v1', credentials=credentials)
    return crm_service

def delete_libcloud_cached_credential():
    project = get_gcloud_project()
    credential = os.path.expanduser('~/.google_libcloud_auth.%s' % project)
    if os.path.exists(credential):
        print 'Deleting %s...' % credential
        os.remove(credential)

def parse_as_json_or_yaml(text):
    def read_as_json(json_text):
        try:
            return json.loads(json_text)
        except:
            return None

    # Try as YAML. If that fails due to bad format, try as JSON
    try:
        data = yaml.load(text)
    except yaml.parser.ParserError:
        data = read_as_json(text)
        if data is None:
            raise exceptions.InvalidFormatError('Text is not valid YAML or JSON format')
    except yaml.scanner.ScannerError as e:
        data = read_as_json(text)
        if data is None:
            raise exceptions.InvalidFormatError(e.message)
    return data

def read_as_json_or_yaml(file):
    try:
        with open(file) as f:
            text = f.read()
    except IOError:
        raise exceptions.NoFileError('Could not find or could not read file %s' % file)

    try:
        return parse_as_json_or_yaml(text)
    except exceptions.InvalidFormatError:
        raise exceptions.InvalidFormatError('Input file "%s" is not valid YAML or JSON format' % file)
