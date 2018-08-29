#!/usr/bin/env python

import argparse
from getpass import getpass
from requests.exceptions import HTTPError
from loomengine.common import verify_server_is_running, get_server_url, \
    verify_has_connection_settings, get_token
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import LoomengineUtilsError


class AbstractUserSubcommand(object):
    def __init__(self, args, silent=False):
        self.args = args
        self.silent = silent
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        token = get_token()
        self.connection = Connection(server_url, token=token)

    def _print(self, text):
        if not self.silent:
            print text


class UserAdd(AbstractUserSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'username',
            metavar='USERNAME', help='add a new user')
        parser.add_argument(
            '-p', '--password',
            metavar='PASSWORD',
            help='Optional. Wait for the prompt to avoid displaying '
            'password and writing it in your terminal history')
        parser.add_argument('-a', '--admin', action='store_true',
                            default=False,
                            help='Grant admin permission to new user')
        return parser

    def run(self):
        password = self.args.password
        if password is None:
            password = getpass("Password: ")
        try:
            user = self.connection.post_user({
                'username': self.args.username,
                'password': password,
                'is_staff': self.args.admin
            })
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to create user: '%s'" % e)
        text = 'Added user "%s"' % user.get('username')
        if user.get('is_staff'):
            text += ' as admin'
        self._print(text)


class UserDelete(AbstractUserSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'username',
            metavar='USERNAME', help='delete a user')
        return parser

    def run(self):
        try:
            users = self.connection.get_user_index(
                query_string=self.args.username)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get user list: '%s'" % e)
        if len(users) == 0:
            raise SystemExit('ERROR! User "%s" not found' % self.args.username)
        assert len(users) == 1, 'ERROR! username %s is not unique' \
            % self.args.username
        user_id = users[0].get('id')
        try:
            user = self.connection.delete_user(user_id)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to delete user: '%s'" % e)
        self._print("deleted user %s" % self.args.username)


class UserList(AbstractUserSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'username',
            nargs='?',
            default=None,
            metavar='USERNAME', help='query by username')
        return parser

    def run(self):
        try:
            users = self.connection.get_user_index(
                query_string=self.args.username)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get user list: '%s'" % e)
        for user in users:
            text = user.get('username')
            if user.get('is_staff'):
                text += ' (admin)'
            self._print(text)


class UserGrantAdmin(AbstractUserSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'username',
            default=None,
            metavar='USERNAME')
        return parser

    def run(self):
        try:
            users = self.connection.get_user_index(
                query_string=self.args.username)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get user list: '%s'" % e)
        if len(users) == 0:
            raise SystemExit('ERROR! User "%s" not found' % self.args.username)
        assert len(users) == 1, 'ERROR! username %s is not unique' \
            % self.args.username
        user_id = users[0].get('id')
        try:
            user = self.connection.update_user(user_id, {'is_staff': True})
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to update user: '%s'" % e)
        self._print(user)


class UserRevokeAdmin(AbstractUserSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'username',
            default=None,
            metavar='USERNAME')
        return parser

    def run(self):
        try:
            users = self.connection.get_user_index(
                query_string=self.args.username)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get user list: '%s'" % e)
        if len(users) == 0:
            raise SystemExit('ERROR! User "%s" not found' % self.args.username)
        assert len(users) == 1, 'ERROR! username %s is not unique' \
            % self.args.username
        user_id = users[0].get('id')
        try:
            user = self.connection.update_user(user_id, {'is_staff': False})
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to update user: '%s'" % e)
        self._print(user)


class UserSetPassword(AbstractUserSubcommand):

    @classmethod
    def get_parser(cls, parser):
        parser.add_argument(
            'username',
            default=None,
            metavar='USERNAME')
        parser.add_argument(
            '-p', '--password',
            metavar='PASSWORD',
            help='Optional. Wait for the prompt to avoid displaying '
            'password and writing it in your terminal history')

        return parser

    def run(self):
        password = self.args.password
        if password is None:
            password = getpass("Password: ")
        try:
            users = self.connection.get_user_index(
                query_string=self.args.username)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get user list: '%s'" % e)
        if len(users) == 0:
            raise SystemExit('ERROR! User "%s" not found' % self.args.username)
        assert len(users) == 1, 'ERROR! username %s is not unique' \
            % self.args.username
        user_id = users[0].get('id')
        try:
            user = self.connection.update_user(user_id, {'password': password})
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to update user: '%s'" % e)

        self._print(user)


class UserClient(object):
    """Configures and executes subcommands under "user" on the main parser.
    """

    def __init__(self, args=None, silent=False):

        # Args may be given as an input argument for testing purposes.
        # Otherwise get them from the parser.
        if args is None:
            args = self._get_args()
        self.args = args
        self.silent = silent

    def _get_args(self):
        parser = self.get_parser()
        return parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):

        # If called from main, a subparser should be provided.
        # Otherwise we create a top-level parser here.
        if parser is None:
            parser = argparse.ArgumentParser(__file__)

        subparsers = parser.add_subparsers()

        add_subparser = subparsers.add_parser(
            'add', help='add a new user')
        UserAdd.get_parser(add_subparser)
        add_subparser.set_defaults(SubSubcommandClass=UserAdd)

        list_subparser = subparsers.add_parser(
            'list', help='show users')
        UserList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubcommandClass=UserList)

        grant_admin_subparser = subparsers.add_parser(
            'grant-admin', help='give admin privileges to user')
        UserGrantAdmin.get_parser(grant_admin_subparser)
        grant_admin_subparser.set_defaults(SubSubcommandClass=UserGrantAdmin)

        revoke_admin_subparser = subparsers.add_parser(
            'revoke-admin', help='revoke admin privileges from user')
        UserRevokeAdmin.get_parser(revoke_admin_subparser)
        revoke_admin_subparser.set_defaults(SubSubcommandClass=UserRevokeAdmin)

        set_password_subparser = subparsers.add_parser(
            'set-password', help="Reset a user's password")
        UserSetPassword.get_parser(set_password_subparser)
        set_password_subparser.set_defaults(SubSubcommandClass=UserSetPassword)

        delete_subparser = subparsers.add_parser(
            'delete', help='delete a user')
        UserDelete.get_parser(delete_subparser)
        delete_subparser.set_defaults(SubSubcommandClass=UserDelete)
        return parser

    def run(self):
        return self.args.SubSubcommandClass(
            self.args, silent=self.silent).run()


if __name__ == '__main__':
    response = UserClient().run()
