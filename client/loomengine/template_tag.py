#!/usr/bin/env python
import argparse
import os
import sys

from loomengine import server
from loomengine.common import verify_has_connection_settings, \
    get_server_url, verify_server_is_running, get_token
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import LoomengineUtilsError


class TemplateTagAdd(object):
    """Add a new template tags
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
            help='identifier for template to be tagged')
        parser.add_argument(
            'tag',
            metavar='TAG', help='tag name to be added')
        return parser

    def run(self):
        try:
            templates = self.connection.get_template_index(
                min=1, max=1,
                query_string=self.args.target)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get template list: '%s'" % e)
        tag_data = {'tag': self.args.tag}
        try:
            tag = self.connection.post_template_tag(
                templates[0]['uuid'], tag_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to create tag: '%s'" % e)
        print 'Target "%s@%s" has been tagged as "%s"' % \
            (templates[0].get('name'),
             templates[0].get('uuid'),
             tag.get('tag'))


class TemplateTagRemove(object):
    """Remove a template tag
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
            help='identifier for template to be untagged')
        parser.add_argument(
            'tag',
            metavar='TAG', help='tag name to be removed')
        return parser

    def run(self):
        try:
            templates = self.connection.get_template_index(
                min=1, max=1,
                query_string=self.args.target)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to get template list: '%s'" % e)
        tag_data = {'tag': self.args.tag}
        try:
            tag = self.connection.remove_template_tag(
                templates[0]['uuid'], tag_data)
        except LoomengineUtilsError as e:
            raise SystemExit("ERROR! Failed to remove tag: '%s'" % e)
        print 'Tag %s has been removed from template "%s@%s"' % \
            (tag.get('tag'),
             templates[0].get('name'),
             templates[0].get('uuid'))


class TemplateTagList(object):

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
            help='show tags only for the specified template')

        return parser

    def run(self):
        if self.args.target:
            try:
                templates = self.connection.get_template_index(
                    min=1, max=1,
                    query_string=self.args.target)
            except LoomengineUtilsError as e:
                raise SystemExit(
                    "ERROR! Failed to get template list: '%s'" % e)
            try:
                tag_data = self.connection.list_template_tags(
                    templates[0]['uuid'])
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get tag list: '%s'" % e)
            tags = tag_data.get('tags', [])
        else:
            try:
                tag_list = self.connection.get_template_tag_index()
            except LoomengineUtilsError as e:
                raise SystemExit("ERROR! Failed to get tag list: '%s'" % e)
            tags = [item.get('tag') for item in tag_list]
        print '[showing %s tags]' % len(tags)
        for tag in tags:
            print tag


class TemplateTag(object):
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
            'add', help='add a template tag')
        TemplateTagAdd.get_parser(add_subparser)
        add_subparser.set_defaults(SubSubSubcommandClass=TemplateTagAdd)

        remove_subparser = subparsers.add_parser(
            'remove', help='remove a template tag')
        TemplateTagRemove.get_parser(remove_subparser)
        remove_subparser.set_defaults(SubSubSubcommandClass=TemplateTagRemove)

        list_subparser = subparsers.add_parser(
            'list', help='list template tags')
        TemplateTagList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubSubcommandClass=TemplateTagList)

        return parser

    def run(self):
        return self.args.SubSubSubcommandClass(
            self.args, silent=self.silent).run()


if __name__ == '__main__':
    response = TemplateTag().run()
