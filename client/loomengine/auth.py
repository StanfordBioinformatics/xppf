#!/usr/bin/env python

import argparse
import os
from getpass import getpass
from loomengine.common import verify_has_connection_settings, \
    verify_server_is_running, get_server_url, \
    save_token, delete_token, get_token
from loomengine_utils.connection import Connection
from requests.exceptions import HTTPError


class AuthClient(object):

    def __init__(self, args=None, silent=False):
        # Parse arguments
        if args is None:
            args = _get_args()
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        self.args = args
        self.silent = silent
        self._set_run_function()
        self.connection = Connection(server_url, token=None)

    def _print(self, text):
        if not self.silent:
            print text

    def _set_run_function(self):
        # Map user input command to method
        commands = {
            'login': self.login,
            'logout': self.logout,
            'print-token': self.print_token,
        }
        self.run = commands[self.args.command]

    def login(self):
        username = self.args.username
        password = self.args.password
        if password is None:
            password = getpass("Password: ")
        try:
            token = self.connection.create_token(
                username=username, password=password)
        except HTTPError:
            raise SystemExit("ERROR! Login failed")
        save_token(token)
        self._print("Login was successful. Token saved.")

    def logout(self):
        token = get_token()
        if token is None:
            self._print("No token found. You are logged out.")
        else:
            delete_token()
            self._print("Token deleted.")

    def print_token(self):
        print get_token()


def get_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser(__file__)

    subparsers = parser.add_subparsers(dest='command')

    login_parser = subparsers.add_parser('login')
    login_parser.add_argument('username', metavar='USERNAME')
    login_parser.add_argument(
        '--password', '-p', metavar='PASSWORD',
        default=None,
        help='Optional. Wait for the prompt to avoid displaying '
        'password and writing it in your terminal history'
    )

    subparsers.add_parser('logout')
    subparsers.add_parser('print-token')

    return parser


def _get_args():
    parser = get_parser()
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    AuthClient().run()
