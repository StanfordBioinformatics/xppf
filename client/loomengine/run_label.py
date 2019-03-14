#!/usr/bin/env python
import argparse
import logging
import os
import sys

from loomengine import LoomClientError
from loomengine.server import verify_has_connection_settings, \
    get_server_url, verify_server_is_running, get_token
from loomengine_utils.connection import Connection
from loomengine_utils.exceptions import LoomengineUtilsError


class RunLabelAdd(object):
    """Add a new run labels
    """

    def __init__(self, args=None):

        # Args may be given as an input argument for testing purposes
        # or from the main parser.
        # Otherwise get them from the parser.
        if args is None:
            args = self._get_args()
        self.args = args
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
            help='identifier for run to be labeled')
        parser.add_argument(
            'label',
            metavar='LABEL', help='label name to be added')
        return parser

    def run(self):
        try:
            runs = self.connection.get_run_index(
                min=1, max=1,
                query_string=self.args.target)
        except LoomengineUtilsError as e:
            raise LoomClientError("ERROR! Failed to get run list: '%s'" % e)

        label_data = {'label': self.args.label}
        try:
            label = self.connection.post_run_label(runs[0]['uuid'], label_data)
        except LoomengineUtilsError as e:
            raise LoomClientError("ERROR! Failed to create label: '%s'" % e)
        logging.info('Target "%s@%s" has been labeled as "%s"' % \
                     (runs[0].get('name'),
                      runs[0].get('uuid'),
                      label.get('label')))


class RunLabelRemove(object):
    """Remove a run label
    """

    def __init__(self, args=None):
        if args is None:
            args = self._get_args()
        self.args = args
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
            help='identifier for run to be unlabeled')
        parser.add_argument(
            'label',
            metavar='LABEL', help='label name to be removed')
        return parser

    def run(self):
        try:
            runs = self.connection.get_run_index(
                min=1, max=1,
                query_string=self.args.target)
        except LoomengineUtilsError as e:
            raise LoomClientError("ERROR! Failed to get run list: '%s'" % e)
        label_data = {'label': self.args.label}
        try:
            label = self.connection.remove_run_label(
                runs[0]['uuid'], label_data)
        except LoomengineUtilsError as e:
            raise LoomClientError("ERROR! Failed to remove label: '%s'" % e)
        logging.info('Label %s has been removed from run "%s@%s"' % \
                     (label.get('label'),
                      runs[0].get('name'),
                      runs[0].get('uuid')))


class RunLabelList(object):

    def __init__(self, args=None):
        if args is None:
            args = self._get_args()
        self.args = args
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
            help='show labels only for the specified run')

        return parser

    def run(self):
        if self.args.target:
            try:
                runs = self.connection.get_run_index(
                    min=1, max=1,
                    query_string=self.args.target)
            except LoomengineUtilsError as e:
                raise LoomClientError("ERROR! Failed to get run list: '%s'" % e)
            try:
                label_data = self.connection.list_run_labels(runs[0]['uuid'])
            except LoomengineUtilsError as e:
                raise LoomClientError("ERROR! Failed to get label list: '%s'" % e)
            labels = label_data.get('labels', [])
            logging.info('[showing %s labels]' % len(labels))
            for label in labels:
                logging.info(label)
        else:
            try:
                label_list = self.connection.get_run_label_index()
            except LoomengineUtilsError as e:
                raise LoomClientError("ERROR! Failed to get label list: '%s'" % e)
            label_counts = {}
            for item in label_list:
                label_counts.setdefault(item.get('label'), 0)
                label_counts[item.get('label')] += 1
            logging.info('[showing %s labels]' % len(label_counts))
            for key in label_counts:
                logging.info("%s (%s)" % (key, label_counts[key]))


class RunLabel(object):
    """Configures and executes subcommands under "label" on the parent parser.
    """

    def __init__(self, args=None):
        if args is None:
            args = self._get_args()
        self.args = args

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
            'add', help='add a run label')
        RunLabelAdd.get_parser(add_subparser)
        add_subparser.set_defaults(SubSubSubcommandClass=RunLabelAdd)

        remove_subparser = subparsers.add_parser(
            'remove', help='remove a run label')
        RunLabelRemove.get_parser(remove_subparser)
        remove_subparser.set_defaults(SubSubSubcommandClass=RunLabelRemove)

        list_subparser = subparsers.add_parser(
            'list', help='list run labels')
        RunLabelList.get_parser(list_subparser)
        list_subparser.set_defaults(SubSubSubcommandClass=RunLabelList)

        return parser

    def run(self):
        return self.args.SubSubSubcommandClass(
            self.args).run()


if __name__ == '__main__':
    response = RunLabel().run()
