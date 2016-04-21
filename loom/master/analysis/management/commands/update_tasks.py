from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import requests

from loomdaemon import loom_daemon_logger


class Command(BaseCommand):
    help = 'Updates status of WorkflowRuns, StpeRuns, and TaskRuns'

    def add_arguments(self, parser):
        # Named (optional) arguments
        parser.add_argument('--logfile',
            dest='logfile',
            default=None,
            help='Log file path')

    def handle(self, *args, **options):
        logfile = options.get('logfile')
        logger = loom_daemon_logger.get_logger(logfile)
        try:
            response = requests.get(settings.MASTER_URL_FOR_WORKER+'/api/controls/update/')
            logger.debug(response.text)
        except Exception as e:
            logger.exception(e)
            raise
