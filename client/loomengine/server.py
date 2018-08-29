#!/usr/bin/env python

import argparse
import ConfigParser
import copy
import errno
import glob
import jinja2
import os
import shutil
import subprocess
import urlparse
import warnings

from loomengine.common import *
from loomengine.settings_validator import validate
import loomengine_utils.version
from . import to_bool

STOCK_PLAYBOOK_DIR = os.path.join(
    os.path.join(imp.find_module('loomengine')[1], 'playbooks'))
LOOM_PLAYBOOK_DIR = 'playbooks'
LOOM_RESOURCE_DIR = 'resources'
LOOM_SERVER_SETTINGS_FILE = 'server-settings.conf'

LOOM_SETTINGS_HOME_TEMP_BACKUP = LOOM_SETTINGS_HOME + '.tmp'


class ServerControls(object):
    """Class for managing the Loom server.
    """
    def __init__(self, args=None, silent=False):
        if args is None:
            args = _get_args()
        self.args = args
        self.silent = silent
        self._set_run_function()

    def _print(self, text):
        if not self.silent:
            print text

    def _set_run_function(self):
        # Map user input command to method
        commands = {
            'status': self.status,
            'start': self.start,
            'stop': self.stop,
            'connect': self.connect,
            'disconnect': self.disconnect,
            'delete': self.delete,
        }
        self.run = commands[self.args.command]

    def status(self):
        verify_has_connection_settings()
        if is_server_running():
            self._print('OK, the server is up at %s' % get_server_url())
        else:
            raise SystemExit(
                'No response from server at %s' % get_server_url())

    def start(self):
        if self._has_server_settings():
            if self._user_provided_settings():
                raise SystemExit(
                    'ERROR! Server settings already exist in "%s". '
                    'The "--settings-file" and "--extra-settings" '
                    'flags are not allowed now because new settings '
                    'and existing settings may conflict.'
                    % os.path.join(
                        LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE))
            else:
                settings = parse_settings_file(
                    os.path.join(
                        LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE))
                self._print('Found settings for a Loom server named "%s". '
                            'Restarting it now.' % self._get_required_setting(
                                'LOOM_SERVER_NAME', settings))

        elif has_connection_settings():
            raise SystemExit(
                'ERROR! You are already connected to a server. '
                'That lets you view or manage workflows, but you do not have '
                'the settings needed to manage the server. If you want to '
                'start a new server, first disconnect using '
                '"loom server disconnect".')

        else:
            # Create new settings from defaults and user input

            # Default settings that may be overridden by the user
            settings = {
                'LOOM_SERVER_NAME': 'loom-server',
                'LOOM_LOG_LEVEL': 'INFO',
                'LOOM_DOCKER_IMAGE':
                'loomengine/loom:%s' % loomengine_utils.version.version(),
                'LOOM_MODE': 'local',
                'LOOM_ANSIBLE_HOST_KEY_CHECKING': 'false',
            }

            # Get settings from user or from running server
            settings.update(self._get_server_settings())

            # Default values depend on user settings
            settings.setdefault('LOOM_STORAGE_TYPE',
                                self._get_default_storage_type(settings))
            settings.setdefault('LOOM_STORAGE_ROOT',
                                self._get_default_storage_root(settings))
            settings.setdefault('LOOM_ANSIBLE_INVENTORY',
                                self._get_default_ansible_inventory(settings))
            settings.setdefault('LOOM_LOGIN_REQUIRED',
                                self._get_default_login_required(settings))
            self._set_default_mysql_settings(settings)

            # For environment variables with an effect on third-party software,
            # remove "LOOM_" prefix from the setting name.
            # In the settings file or command line args, either form is ok.
            # In environment variables, only "LOOM_*" will be detected.
            settings = self._copy_setting_without_loom_prefix(
                settings, 'ANSIBLE_HOST_KEY_CHECKING')

            # Hard-coded settings that should not come from the user:
            settings.update({
                'LOOM_PLAYBOOK_DIR': LOOM_PLAYBOOK_DIR,
                'LOOM_CONNECTION_SETTINGS_FILE': LOOM_CONNECTION_SETTINGS_FILE,
                'LOOM_RESOURCE_DIR': LOOM_RESOURCE_DIR,
                'LOOM_SERVER_SETTINGS_FILE': LOOM_SERVER_SETTINGS_FILE,
            })
            mode = settings.get('LOOM_MODE').lower()
            if mode:
                settings.update({
                    'LOOM_START_SERVER_PLAYBOOK': '%s_start_server.yml' % mode,
                    'LOOM_STOP_SERVER_PLAYBOOK': '%s_stop_server.yml' % mode,
                    'LOOM_DELETE_SERVER_PLAYBOOK':
                    '%s_delete_server.yml' % mode,
                    'LOOM_RUN_TASK_ATTEMPT_PLAYBOOK':
                    '%s_run_task_attempt.yml' % mode,
                    'LOOM_CLEANUP_TASK_ATTEMPT_PLAYBOOK':
                    '%s_cleanup_task_attempt.yml' % mode,
                })

            if not settings.get('LOOM_SKIP_SETTINGS_VALIDATION'):
                validate(settings)

            self._make_dir_if_missing(LOOM_SETTINGS_HOME)
            self._copy_playbooks_to_settings_dir()
            self._save_server_settings_file(settings)
            self._copy_resources_to_settings_dir()

            self._print('Starting a Loom server named "%s".' %
                        self._get_required_setting(
                            'LOOM_SERVER_NAME', settings))
        playbook = self._get_required_setting(
            'LOOM_START_SERVER_PLAYBOOK', settings)
        retcode = self._run_playbook(
            playbook, settings, verbose=self.args.verbose)
        if retcode:
            raise SystemExit(
                'ERROR! Playbook to start server failed. There may be '
                'active resources such as running docker containers or '
                ' VMs that were created by the playbook and not '
                'cleaned up.')

    def _get_default_storage_type(self, settings):
        if settings.get('LOOM_MODE').lower() == 'gcloud':
            return 'google_storage'
        else:
            return 'local'

    def _get_default_storage_root(self, settings):
        if settings.get('LOOM_STORAGE_TYPE').lower() == 'local':
            return os.path.expanduser('~/loomdata')
        else:
            return '/loomdata'

    def _get_default_ansible_inventory(self, settings):
        if settings.get('LOOM_MODE').lower() == 'gcloud':
            return 'gce_inventory_wrapper.py'
        else:
            return 'localhost,'

    def _get_default_login_required(self, settings):
        if settings.get('LOOM_MODE').lower() == 'local':
            return 'false'
        else:
            return 'true'

    def _set_default_mysql_settings(self, settings):
        # If user provides a MySQL server name, assume they don't
        # want to create a new one
        if settings.get('LOOM_MYSQL_HOST'):
            settings.setdefault('LOOM_MYSQL_CREATE_DOCKER_CONTAINER', 'false')
        else:
            settings.setdefault('LOOM_MYSQL_CREATE_DOCKER_CONTAINER', 'true')

        if to_bool(settings.get('LOOM_MYSQL_CREATE_DOCKER_CONTAINER')):
            settings.setdefault('LOOM_MYSQL_HOST',
                                settings.get('LOOM_SERVER_NAME')+'-mysql')
        return

    def stop(self):
        if not self._has_server_settings():
            raise SystemExit(
                'ERROR! No server settings found. Nothing to stop.')

        settings = parse_settings_file(
            os.path.join(LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE))
        self._print('Stopping Loom server named "%s".'
                    % self._get_required_setting(
                        'LOOM_SERVER_NAME', settings))
        playbook = self._get_required_setting('LOOM_STOP_SERVER_PLAYBOOK',
                                              settings)
        retcode = self._run_playbook(
            playbook, settings, verbose=self.args.verbose)
        if retcode:
            raise SystemExit('ERROR! Playbook to stop server failed.')

    def connect(self):
        server_url = self.args.server_url
        if has_connection_settings():
            raise SystemExit(
                'ERROR! Already connected to "%s".' % get_server_url())

        parsed_url = urlparse.urlparse(server_url)
        if not parsed_url.scheme:
            if is_server_running(url='https://' + server_url):
                server_url = 'https://' + server_url
            elif is_server_running(url='http://' + server_url):
                server_url = 'http://' + server_url
            else:
                raise SystemExit(
                    'ERROR! Loom server not found at "%s".' % server_url)
        elif not is_server_running(url=server_url):
            raise SystemExit(
                'ERROR! Loom server not found at "%s".' % server_url)
        connection_settings = {"LOOM_SERVER_URL": server_url}
        self._save_connection_settings_file(connection_settings)
        self._print('Connected to Loom server at "%s".' % server_url)

    def disconnect(self):
        if not has_connection_settings():
            raise SystemExit(
                'ERROR! No server connection found. Nothing to disconnect.')
        if self._has_server_settings():
            raise SystemExit(
                'ERROR! Server settings found. Disconnecting is not allowed. '
                'If you really want to disconnect without deleting the '
                'server, back up the settings in %s and manually remove them.'
                % os.path.join(LOOM_SETTINGS_HOME))
        settings = parse_settings_file(
            os.path.join(LOOM_SETTINGS_HOME, LOOM_CONNECTION_SETTINGS_FILE))
        server_url = settings.get('LOOM_SERVER_URL')
        os.remove(os.path.join(
            LOOM_SETTINGS_HOME, LOOM_CONNECTION_SETTINGS_FILE))
        delete_token()
        try:
            # remove if empty
            os.rmdir(LOOM_SETTINGS_HOME)
        except OSError:
            pass
        self._print('Disconnected from the Loom server at %s \nTo reconnect, '
                    'use "loom server connect %s"' % (server_url, server_url))

    def delete(self):
        if not self._has_server_settings():
            raise SystemExit(
                'ERROR! No server settings found. Nothing to delete.')
        settings = parse_settings_file(
            os.path.join(LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE))

        server_name = self._get_required_setting('LOOM_SERVER_NAME', settings)
        user_provided_server_name = self.args.confirm_server_name
        if not user_provided_server_name:
            user_provided_server_name = raw_input(
                'WARNING! This will delete the Loom server and all its data. '
                'Data will be lost!\n'
                'If you are sure you want to continue, please '
                'type the name of the server:\n> ')

        if user_provided_server_name != server_name:
            self._print(
                'Input did not match current server name \"%s\".'
                % server_name)
            return
        playbook = self._get_required_setting(
            'LOOM_DELETE_SERVER_PLAYBOOK', settings)

        retcode = self._run_playbook(
            playbook, settings, verbose=self.args.verbose)

        if retcode:
            raise SystemExit(
                'ERROR! Playbook to delete server failed. '
                'Skipping deletion of configuration files in "%s".'
                % LOOM_SETTINGS_HOME)

        # Do not attempt remove if value is missing or root
        if not LOOM_SETTINGS_HOME \
           or os.path.abspath(LOOM_SETTINGS_HOME) == os.path.abspath('/'):
            print 'WARNING! LOOM_SETTINGS_HOME is "%s". Refusing to delete.' \
                % LOOM_SETTINGS_HOME
        else:
            try:
                if os.path.exists(LOOM_SETTINGS_HOME):
                    shutil.rmtree(LOOM_SETTINGS_HOME)
            except Exception as e:
                print 'WARNING! Failed to remove settings directory %s.\n%s' \
                    % (LOOM_SETTINGS_HOME, str(e))

    def _save_server_settings_file(self, settings):
        write_settings_file(
            os.path.join(LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE),
            settings)

    def _save_connection_settings_file(self, settings):
        if not os.path.exists(LOOM_SETTINGS_HOME):
            os.makedirs(LOOM_SETTINGS_HOME)
        write_settings_file(
            os.path.join(LOOM_SETTINGS_HOME, LOOM_CONNECTION_SETTINGS_FILE),
            settings)

    def _make_dir_if_missing(self, path):
        try:
            os.makedirs(path)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(path):
                pass  # Ok, dir exists
            else:
                raise SystemExit('ERROR! Unable to create directory "%s"\n%s'
                                 % (path, str(e)))

    def _copy_playbooks_to_settings_dir(self):
        if self.args.playbook_dir:
            playbook_dir = self.args.playbook_dir
        else:
            playbook_dir = STOCK_PLAYBOOK_DIR
        shutil.copytree(playbook_dir,
                        os.path.join(LOOM_SETTINGS_HOME, LOOM_PLAYBOOK_DIR))

    def _copy_resources_to_settings_dir(self):
        if self.args.resource_dir:
            resource_dir = self.args.resource_dir
        elif self.args.admin_files_dir:
            ADMIN_FILES_DIR_FLAG_DEPRECATED \
                = 'WARNING! The "--admin-files-dir" flag is deprecated '\
                'and will be removed. Use "--resource-dir" instead.'
            warnings.warn(ADMIN_FILES_DIR_FLAG_DEPRECATED)
            resource_dir = self.args.admin_files_dir
        if self.args.resource_dir:
            shutil.copytree(
                self.args.resource_dir,
                os.path.join(LOOM_SETTINGS_HOME, LOOM_RESOURCE_DIR))
        else:
            # If no files, leave an empty directory
            os.makedirs(
                os.path.join(LOOM_SETTINGS_HOME, LOOM_RESOURCE_DIR))

    def _run_playbook(self, playbook, settings, verbose=False):
        inventory = self._get_required_setting(
            'LOOM_ANSIBLE_INVENTORY', settings)
        if ',' not in inventory:
            inventory = os.path.join(
                LOOM_SETTINGS_HOME, LOOM_PLAYBOOK_DIR, inventory)
        cmd_list = ['ansible-playbook',
                    '-i', inventory,
                    os.path.join(
                        LOOM_SETTINGS_HOME, LOOM_PLAYBOOK_DIR, playbook),
                    # Without this, ansible uses /usr/bin/python,
                    # which may be missing needed modules
                    '-e', 'ansible_python_interpreter="/usr/bin/env python"']
        if 'LOOM_SSH_PRIVATE_KEY_NAME' in settings:
            private_key_file_path = os.path.join(
                os.path.expanduser('~/.ssh'),
                settings['LOOM_SSH_PRIVATE_KEY_NAME'])
            cmd_list.extend(['--private-key', private_key_file_path])
        if verbose:
            cmd_list.append('-vvvv')

        # Add one context-specific setting
        settings.update({'LOOM_SETTINGS_HOME': LOOM_SETTINGS_HOME})

        # Add settings to environment, with precedence to environment vars
        settings.update(copy.copy(os.environ))

        return subprocess.call(cmd_list, env=settings)

    def _get_required_setting(self, key, settings):
        try:
            return settings[key]
        except KeyError:
            raise SystemExit('ERROR! Missing required setting "%s".' % key)

    def _user_provided_settings(self):
        # True if user passed settings through commandline arguments
        return self.args.settings_file or self.args.extra_settings

    def _has_server_settings(self):
        server_settings_path = os.path.join(LOOM_SETTINGS_HOME,
                                            LOOM_SERVER_SETTINGS_FILE)
        resource_paths = [
            os.path.join(LOOM_SETTINGS_HOME, LOOM_RESOURCE_DIR),
            os.path.join(LOOM_SETTINGS_HOME, LOOM_PLAYBOOK_DIR),
        ]
        has_settings = os.path.exists(server_settings_path)
        has_files = any(os.path.exists(path) for path in resource_paths)
        if has_files and not has_settings:
            raise SystemExit(
                'ERROR! Server settings are corrupt. No settings file '
                'found at "%s", but settings files exist in these '
                'directories: [%s]'
                % (server_settings_path, ', '.join(resource_paths)))
        return has_settings

    def _get_server_settings(self):
        if self._has_server_settings():
            if self._user_provided_settings():
                raise SystemExit(
                    'ERROR! Server settings already exist in "%s". '
                    'The "--settings-file" and "--extra-settings" '
                    'flags are not allowed now because new settings '
                    'and existing settings may conflict.'
                    % os.path.join(
                        LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE))
            else:
                settings = parse_settings_file(
                    os.path.join(
                        LOOM_SETTINGS_HOME, LOOM_SERVER_SETTINGS_FILE))
        elif has_connection_settings():
            if self._user_provided_settings():
                raise SystemExit(
                    'ERROR! Connection settings already exist in "%s". '
                    'The "--settings-file" and "--extra-settings" '
                    'flags are not allowed now because new settings '
                    'and existing settings may conflict.'
                    % os.path.join(
                        LOOM_SETTINGS_HOME, LOOM_CONNECTION_SETTINGS_FILE))
            else:
                raise SystemExit(
                    'ERROR! You are already connected to a server. '
                    'That lets you view or manage workflows, but you '
                    'do not have the settings needed to manage the server. '
                    'If you want to start a new server, first disconnect '
                    'using "loom server disconnect".')
        else:
            settings = self._get_start_settings_from_args()
        return settings

    def _get_start_settings_from_args(self):
        settings = {}
        if self.args.settings_file:
            for settings_file in self.args.settings_file:
                settings.update(parse_settings_file(settings_file))
        if self.args.extra_settings:
            settings.update(
                self._parse_extra_settings(self.args.extra_settings))

        # Pick up any LOOM_* settings from the environment, and
        # give precedence to env over settings file. Exclude
        # LOOM_SETTINGS_HOME because it is context-specific.
        for key, value in os.environ.iteritems():
            if key.startswith('LOOM_') and key != 'LOOM_SETTINGS_HOME':
                settings.update({key: value})

        for key, value in settings.items():
            settings[key] = os.path.expanduser(value)

        return settings

    def _copy_setting_without_loom_prefix(self, settings, real_setting_name):
        loom_setting_name = 'LOOM_'+real_setting_name
        if settings.get(loom_setting_name) and not \
           settings.get(real_setting_name):
            settings[real_setting_name] = settings.get(loom_setting_name)
        elif settings.get(loom_setting_name) == settings.get(
                real_setting_name):
            pass
        else:
            raise Exception("Conflicting settings %s=%s, %s=%s" % (
                real_setting_name,
                settings.get(real_setting_name),
                loom_setting_name,
                settings.get(loom_setting_name)))
        return settings

    def _parse_extra_settings(self, extra_settings):
        settings_dict = {}
        for setting in extra_settings:
            if '=' not in setting:
                raise SystemExit(
                    'Invalid format for extra setting "%s". '
                    'Use "-e key=value" format.' % setting)
            (key, value) = setting.split('=', 1)
            settings_dict[key] = value
        return settings_dict


def get_parser(parser=None):

    if parser is None:
        parser = argparse.ArgumentParser(__file__)

    subparsers = parser.add_subparsers(dest='command')

    status_parser = subparsers.add_parser(
        'status',
        help='show the status of the Loom server')

    start_parser = subparsers.add_parser(
        'start',
        help='start a loom server')
    start_parser.add_argument('-s', '--settings-file', action='append',
                              metavar='SETTINGS_FILE')
    start_parser.add_argument('-e', '--extra-settings', action='append',
                              metavar='KEY=VALUE')
    start_parser.add_argument('-p', '--playbook-dir', metavar='PLAYBOOK_DIR')
    start_parser.add_argument('-r', '--resource-dir', metavar='RESOURCE_DIR')
    start_parser.add_argument(
        '-a', '--admin-files-dir',
        metavar='ADMIN_FILES_DIR',
        help=argparse.SUPPRESS)
    start_parser.add_argument('-v', '--verbose', action='store_true',
                              help='provide more feedback to console')

    stop_parser = subparsers.add_parser(
        'stop',
        help='stop execution of a Loom server. (It can be started again.)')
    stop_parser.add_argument('-v', '--verbose', action='store_true',
                             help='provide more feedback to console')

    connect_parser = subparsers.add_parser(
        'connect',
        help='connect to a running Loom server')
    connect_parser.add_argument(
        'server_url',
        metavar='LOOM_SERVER_URL',
        help='URL of the Loom server you wish to connect to')

    disconnect_parser = subparsers.add_parser(
        'disconnect',
        help='disconnect the client from a Loom server '
        'but leave the server running')

    delete_parser = subparsers.add_parser(
        'delete',
        help='delete the Loom server')
    delete_parser.add_argument(
        '-s', '--confirm-server-name', metavar='SERVER_NAME',
        help='provide server name to skip confirmation prompt '
        'when deleting the server')
    delete_parser.add_argument('-v', '--verbose', action='store_true',
                               help='provide more feedback to console')

    return parser


def _get_args():
    parser = get_parser()
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    ServerControls().run()
