import json
import os
import re
import uuid

from ConfigParser import SafeConfigParser
from loomengine.client.common import *
from loomengine.utils.version import version

"""These functions load and write settings for the Loom client.

Settings are loaded in the following order, with later ones taking precedence:
    1. the [DEFAULT] section from default_settings.ini
    2. the section from default_settings.ini corresponding to the server type (passed as argument to constructor)
    3. user-provided settings file, if any
    4. user-provided command line arguments, if any
"""

DEFAULT_SETTINGS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'default_settings.ini'))
DEPLOY_SETTINGS_FILE_SUFFIX = '_deploy_settings.ini'

def get_default_settings():
    """Return a dict of default settings for the current server type."""
    return read_settings_from_file(settings_file=DEFAULT_SETTINGS_FILE, section=get_server_type())

def get_user_settings(user_settings_file):
    """Load settings from the provided file for the current server type and return the resulting dict. If user_settings_file is None, return an empty dict."""
    if user_settings_file == None:
        return {}
    return read_settings_from_file(settings_file=user_settings_file, section=get_server_type())

def add_user_settings(settings, user_settings_file):
    user_settings = get_user_settings(user_settings_file)
    settings.update(user_settings)
    return settings
    
def get_deploy_settings_filename():
    return os.path.expanduser(os.path.join(LOOM_SETTINGS_PATH, get_server_type() + DEPLOY_SETTINGS_FILE_SUFFIX))

def create_deploy_settings(user_settings_file=None):
    """Load default settings, override with user-provided settings file, if any, and postprocess settings."""
    server_type = get_server_type()
    settings = get_default_settings()

    # Add Google Cloud-specific settings
    if server_type == 'gcloud': 
        settings = add_gcloud_settings(settings)

    # Override defaults with user-provided settings file
    if user_settings_file:
        add_settings_from_file(settings, settings_file=user_settings_file, section=server_type)

    settings = postprocess_settings(settings)
    return settings

def add_gcloud_settings(settings):
    """Add Google Cloud-specific settings to the provided dict and return it."""
    # Add server name from server.ini
    settings['SERVER_NAME'] = get_gcloud_server_name()
    settings['MASTER_URL_FOR_WORKER'] = '%s://%s:%s' % (settings['PROTOCOL'], settings['SERVER_NAME'], settings['EXTERNAL_PORT'])

    # Add service account email
    if settings['CUSTOM_SERVICE_ACCOUNT_EMAIL'] != 'None':
        settings['GCE_EMAIL'] = settings['CUSTOM_SERVICE_ACCOUNT_EMAIL']
    else:
        settings['GCE_EMAIL'] = find_service_account_email(get_gcloud_server_name())
    if not settings['GCE_EMAIL']:
        raise Exception('Invalid service account email: %s' % settings['GCE_EMAIL'])

    # Add other settings 
    settings['GCE_INI_PATH'] = GCE_INI_PATH
    settings['GCE_PROJECT'] = get_gcloud_project()
    settings['GCE_PEM_FILE_PATH'] = GCE_JSON_PATH
    settings['CLIENT_VERSION'] = version()

    # If bucket not provided, default to project id with '-loom' appended
    if settings['GCE_BUCKET'] == 'None':
        settings['GCE_BUCKET'] = settings['GCE_PROJECT'] + '-loom'

    return settings

def postprocess_settings(settings):
    """Write settings that depend on other settings being defined first."""
    if get_server_type() == 'gcloud':
        settings['DOCKER_FULL_NAME'] = '%s/%s:%s' % (settings['DOCKER_REPO'], settings['DOCKER_IMAGE'], settings['DOCKER_TAG'])
        if settings['DOCKER_REGISTRY'] != 'None':
            settings['DOCKER_FULL_NAME'] = '/'.join([settings['DOCKER_REGISTRY'], settings['DOCKER_FULL_NAME']])
    return settings

def write_deploy_settings_file(user_settings_file=None):
    """Writes deploy settings and returns them. Should only be called when creating the Loom server."""
    settings = create_deploy_settings(user_settings_file)
    write_settings_to_file(settings, get_deploy_settings_filename(), section='deploy')
    return settings

def read_deploy_settings_file():
    try:
        return read_settings_from_file(get_deploy_settings_filename(), section='deploy')
    except:
        raise SettingsError("Could not open server deploy settings at %s. You might need to run \"loom server create\" first." % get_deploy_settings_filename())

def delete_deploy_settings_file():
    os.remove(get_deploy_settings_filename())

def read_settings_from_file(settings_file, section):
    """Read settings from a file and section and return them. If settings_file is unspecified or doesn't exist, returns an error."""
    if not os.path.exists(settings_file):
        raise Exception('Cannot find settings file "%s"' % settings_file)
    try:
        config = SafeConfigParser(allow_no_value=True)
        config.optionxform = lambda option: option.upper() # preserve uppercase in settings names
        config.read(settings_file)
    except Exception as e: 
        raise SettingsError("Failed to open settings file %s: %s" % (settings_file, e))

    #print "Loaded settings from %s." % settings_file
    items = dict(config.items(section))
    return items

def add_settings_from_file(settings, settings_file, section):
    """Add settings from a file and section to a provided dict and return the result. If no settings_file provided, just return the original settings."""
    if settings_file == None:
        return settings
    settings_to_add = read_settings_from_file(settings_file, section)
    settings.update(settings_to_add)
    return settings

def write_settings_to_file(settings, settings_file, section):
    """Write a dict of settings to a file under the specified section."""
    make_settings_directory(settings_file)
    config = SafeConfigParser(allow_no_value=True)
    config.optionxform = lambda option: option.upper() # preserve uppercase in settings names
    config.add_section(section)
    for key in settings:
        config.set(section, key, settings[key])
    with open(settings_file, 'w') as fp:
        config.write(fp)

def make_settings_directory(settings_file):
    if os.path.exists(os.path.dirname(settings_file)):
        return
    else:
        try:
            os.makedirs(os.path.dirname(settings_file))
            print "Created directory %s." % os.path.dirname(settings_file)
        except Exception as e:
            raise SettingsError("Failed to create directory for the settings file %s (%s)" % (os.path.dirname(settings_file), e))

def expand_user_dirs(settings):
    export_settings = {}
    for key,value in settings.items():
        if value is not None:
            if isinstance(value, str) and '~' in value: # Expand user home directory to absolute path
                value = os.path.expanduser(value)
            export_settings[key] = value
    return export_settings

def get_ansible_env():
    """Load settings needed for Ansible into environment variables, where
    they will be read by the Ansible playbook. Start with everything in
    the environment, add items from the deploy settings file, then add other
    variables that shouldn't be in the deploy settings file (such as absolute
    paths containing the user home dir).
    """
    env = os.environ.copy()
    env['DEPLOY_SETTINGS_FILENAME'] = get_deploy_settings_filename()
    deploy_settings = read_deploy_settings_file()
    env.update(deploy_settings)
    env['LOOM_HOME_SUBDIR'] = LOOM_HOME_SUBDIR
    env = expand_user_dirs(env)
    return env

def get_default_setting(section, option):
    settings = read_settings_from_file(DEFAULT_SETTINGS_FILE, section)
    return settings[option]

def add_gcloud_settings_on_server(settings):
    """Write settings that can't be defined prior to having a running server instance."""
    if settings['WORKER_USES_SERVER_INTERNAL_IP'] == 'True':
        settings['MASTER_URL_FOR_WORKER'] = '%s://%s:%s' % (settings['PROTOCOL'], get_gcloud_server_private_ip(settings['SERVER_NAME']), settings['EXTERNAL_PORT'])
    return settings

def has_custom_service_account(settings):
    return settings['CUSTOM_SERVICE_ACCOUNT_EMAIL'] != 'None'


class SettingsError(Exception):
    pass
