#!/usr/bin/env python
import argparse
import os
import sys

from loomengine import server
from loomengine.common import verify_has_connection_settings, \
    get_server_url, verify_server_is_running, get_token
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import LoomengineUtilsError


class FileTagAdd(object):
    """Add a new file tags
    """

    def __init__(self, args=None, silent=False):
        # Args may be given as an input argument for testing purposes
        # or from the main parser.
        # Otherwise get them from the parser.
        if args is None:
            args = self._get_args()
        self.args = args
        self.silent = silent
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        self.connection = Connection(server_url, token=get_token())

    def _get_args(self):
        self.parser = self.get_parser()
        return self.parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):
        # If called from main, use the subparser provided.
        # Otherwise create a top-level parser here.
        if parser is None:
            parser = argparse.ArgumentParser(__file__)

        parser.add_argument(
            'target',
            metavar='TARGET',
            help='identifier for file to be tagged')
        parser.add_argument(
            'tag',
            metavar='TAG', help='tag name to be added')
        return parser

    def run(self):
        try:
            files = self.connection.get_data_object_index(
                min=1, max=1,
                query_string=self.args.target, type='file')
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get data object list: '%s'" % e)
        tag_data = {'tag': self.args.tag}
        try:
            tag = self.connection.post_data_tag(files[0]['uuid'], tag_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to create tag: '%s'" % e)

        if not self.silent:
            print 'Target "%s@%s" has been tagged as "%s"' % \
                (files[0]['value'].get('filename'),
                 files[0].get('uuid'),
                 tag.get('tag'))


class FileTagRemove(object):
    """Remove a file tag
    """

    def __init__(self, args=None, silent=False):
        if args is None:
            args = self._get_args()
        self.args = args
        self.silent = silent
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        self.connection = Connection(server_url, token=get_token())

    def _get_args(self):
        self.parser = self.get_parser()
        return self.parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):
        # If called from main, use the subparser provided.
        # Otherwise create a top-level parser here.
        if parser is None:
            parser = argparse.ArgumentParser(__file__)
        parser.add_argument(
            'target',
            metavar='TARGET',
            help='identifier for file to be untagged')
        parser.add_argument(
            'tag',
            metavar='TAG', help='tag name to be removed')
        return parser

    def run(self):
        try:
            files = self.connection.get_data_object_index(
                min=1, max=1,
                query_string=self.args.target, type='file')
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get data object list: '%s'" % e)
        tag_data = {'tag': self.args.tag}
        try:
            tag = self.connection.remove_data_tag(files[0]['uuid'], tag_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to remove tag: '%s'" % e)
        if not self.silent:
            print 'Tag %s has been removed from file "%s@%s"' % \
                (tag.get('tag'),
                 files[0]['value'].get('filename'),
                 files[0].get('uuid'))


class FileTagList(object):

    def __init__(self, args=None, silent=False):
        if args is None:
            args = self._get_args()
        self.args = args
        self.silent = silent
        verify_has_connection_settings()
        server_url = get_server_url()
        verify_server_is_running(url=server_url)
        self.connection = Connection(server_url, token=get_token())

    def _get_args(self):
        self.parser = self.get_parser()
        return self.parser.parse_args()

    @classmethod
    def get_parser(cls, parser=None):
        # If called from main, use the subparser provided.
        # Otherwise create a top-level parser here.
        if parser is None:
            parser = argparse.ArgumentParser(__file__)

        parser.add_argument(
            'target',
            metavar='TARGET',
            nargs='?',
            help='show tags only for the specified file')

        return parser

    def run(self):
        if self.args.target:
            try:
                files = self.connection.get_data_object_index(
                    min=1, max=1,
                    query_string=self.args.target, type='file')
            except LoomengineUtilsError as e:
                raise SystemExit(
                    "ERROR! Failed to get data object list: '%s'" % e)

            try:
                tag_data = self.connection.list_data_tags(files[0]['uuid'])
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get tag list: '%s'" % e)
            tags = tag_data.get('tags', [])
        else:
            try:
                tag_list = self.connection.get_data_tag_index()
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get tag list: '%s'" % e)
            tags = [item.get('tag') for item in tag_list]
        if not self.silent:
            print '[showing %s tags]' % len(tags)
            for tag in tags:
                print tag


class FileTag(object):
    """Configures and executes subcommands under "tag" on the parent parser.
    """

    def __init__(self, args=None, silent=False):
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
            'add', help='add a file tag')
        FileTagAdd.get_parser(add_subparser)
        add_subparser.set_defaults(SubSubSubcommandClass=FileTagAdd)

        remove_subparser = subparsers.add_parser(
            'remove', help='remove a file tag')
        FileTagRemove.get_parser(remove_subparser)
        remove_subparser.set_defaults(SubSubSubcommandClass=FileTagRemove)

        list_subparser = subparsers.add_parser(
            'list', help='list file tags')
        FileTagList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubSubcommandClass=FileTagList)

        return parser

    def run(self):
        return self.args.SubSubSubcommandClass(
            self.args, silent=self.silent).run()


if __name__ == '__main__':
    response = FileTag().run()
