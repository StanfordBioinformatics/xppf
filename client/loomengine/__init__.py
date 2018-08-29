import dateutil.parser
import dateutil.tz
import logging
import sys
import loomengine_utils

utils_logger = logging.getLogger(loomengine_utils.__name__)
utils_logger.addHandler(logging.StreamHandler(sys.stdout))
utils_logger.setLevel('INFO')

_DATETIME_FORMAT = '%b %d, %Y %-I:%M:%S %p'


def _render_time(timestr):
    time_gmt = dateutil.parser.parse(timestr)
    time_local = time_gmt.astimezone(dateutil.tz.tzlocal())
    return format(time_local, _DATETIME_FORMAT)


def to_bool(value):
    if value and value.lower() in ['true', 't', 'yes', 'y']:
        return True
    else:
        return False
