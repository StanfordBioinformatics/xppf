#!/usr/bin/env python
import argparse
import os
import sys

from loomengine import server
from loomengine.common import verify_has_connection_settings, \
    get_server_url, verify_server_is_running, get_token
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import LoomengineUtilsError


class RunTagAdd(object):
    """Add new run tags
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
            help='identifier for run to be tagged')
        parser.add_argument(
            'tag',
            metavar='TAG', help='tag name to be added')
        return parser

    def run(self):
        try:
            runs = self.connection.get_run_index(
                min=1, max=1,
                query_string=self.args.target)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run list: '%s'" % e)

        tag_data = {'tag': self.args.tag}
        try:
            tag = self.connection.post_run_tag(runs[0]['uuid'], tag_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed create tag: '%s'" % e)
        print 'Target "%s@%s" has been tagged as "%s"' % \
            (runs[0].get('name'),
             runs[0].get('uuid'),
             tag.get('tag'))


class RunTagRemove(object):
    """Remove a run tag
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
            help='identifier for run to be untagged')
        parser.add_argument(
            'tag',
            metavar='TAG', help='tag name to be removed')
        return parser

    def run(self):
        try:
            runs = self.connection.get_run_index(
                min=1, max=1,
                query_string=self.args.target)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get run list: '%s'" % e)

        tag_data = {'tag': self.args.tag}
        try:
            tag = self.connection.remove_run_tag(runs[0]['uuid'], tag_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to remove tag: '%s'" % e)
        print 'Tag %s has been removed from run "%s@%s"' % \
            (tag.get('tag'),
             runs[0].get('name'),
             runs[0].get('uuid'))


class RunTagList(object):

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
            help='show tags only for the specified run')

        return parser

    def run(self):
        if self.args.target:
            try:
                runs = self.connection.get_run_index(
                    min=1, max=1,
                    query_string=self.args.target)
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get run list: '%s'" % e)
            try:
                tag_data = self.connection.list_run_tags(runs[0]['uuid'])
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get tag list: '%s'" % e)
            tags = tag_data.get('tags', [])
        else:
            try:
                tag_list = self.connection.get_run_tag_index()
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get tag list: '%s'" % e)
            tags = [item.get('tag') for item in tag_list]

        print '[showing %s tags]' % len(tags)
        for tag in tags:
            print tag


class RunTag(object):
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
            'add', help='add a run tag')
        RunTagAdd.get_parser(add_subparser)
        add_subparser.set_defaults(SubSubSubcommandClass=RunTagAdd)

        remove_subparser = subparsers.add_parser(
            'remove', help='remove a run tag')
        RunTagRemove.get_parser(remove_subparser)
        remove_subparser.set_defaults(SubSubSubcommandClass=RunTagRemove)

        list_subparser = subparsers.add_parser(
            'list', help='list run tags')
        RunTagList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubSubcommandClass=RunTagList)

        return parser

    def run(self):
        return self.args.SubSubSubcommandClass(
            self.args, silent=self.silent).run()


if __name__ == '__main__':
    response = RunTag().run()
