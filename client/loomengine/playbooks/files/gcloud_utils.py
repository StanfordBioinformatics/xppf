import json
import math
import os
import re
import requests

# Utility functions related to Google Cloud Platform
# that can be used by all components.


def on_gcloud_vm():
    """ Determines if we're running on a GCE instance."""
    r = None
    try:
        r = requests.get('http://metadata.google.internal')
    except requests.ConnectionError:
        return False

    try:
        if r.headers['Metadata-Flavor'] == 'Google' and \
           r.headers['Server'] == 'Metadata Server for VM':
            return True
    except KeyError:
        return False


def get_cheapest_instance_type(cores, memory):
    """Determine the cheapest instance type given a minimum
    number of cores and minimum amount of RAM (in GB).
    """

    pricelist = get_gcloud_pricelist()

    # Filter out preemptible, shared-CPU, and non-US instance types
    us_instance_types = {k: v for k, v in pricelist.items()
                         if k.startswith('CP-COMPUTEENGINE-VMIMAGE-')
                         and not k.endswith('-PREEMPTIBLE')
                         and 'us' in v and v['cores'] != 'shared'}

    # Convert to array and add keys (instance type names) as type names
    price_array = []
    for key in us_instance_types:
        value = us_instance_types[key]
        value.update({'name': key.replace(
            'CP-COMPUTEENGINE-VMIMAGE-', '').lower()})
        price_array.append(value)

    # Sort by price in US
    price_array.sort(None, lambda x: x['us'])

    # Look for an instance type that satisfies requested
    # cores and memory; first will be cheapest
    for instance_type in price_array:
        if int(instance_type['cores']) >= int(cores) \
           and float(instance_type['memory']) >= float(memory):
            print instance_type['name']
            return instance_type['name']

    # No instance type found that can fulfill requested cores and memory
    raise Exception('No instance type found with at least %d cores '
                    'and %f GB of RAM.' % (cores, memory))


def get_gcloud_pricelist():
    """Retrieve latest pricelist from Google Cloud, or use
    cached copy if not reachable.
    """
    try:
        r = requests.get('http://cloudpricingcalculator.appspot.com'
                         '/static/data/pricelist.json')
        content = json.loads(r.content)
    except ConnectionError:
        logger.warning(
            "Couldn't get updated pricelist from "
            "http://cloudpricingcalculator.appspot.com"
            "/static/data/pricelist.json. Falling back to cached "
            "copy, but prices may be out of date.")
        with open('gcloudpricelist.json') as infile:
            content = json.load(infile)

    pricelist = content['gcp_price_list']
    return pricelist


MIN_TASK_ID_CHARS = 8


def _get_base_name(hostname, step_name, attempt_id, max_length):
    """Create a base name for the worker instance that will run the specified
    task run attempt, from this server. Since hostname and step name will be
    duplicated across workers (reruns, etc.), ensure that at least
    MIN_TASK_ID_CHARS are preserved in the instance name. Also, prevent names
    from ending with dashes.
    """
    max_length = int(max_length)
    if len(hostname)+len(step_name)+MIN_TASK_ID_CHARS+2 > max_length:
        # round with ceil/floor such that extra char goes to hostname if odd
        hostname_chars = int(math.ceil(
            (max_length-MIN_TASK_ID_CHARS-2)/float(2)))
        step_name_chars = int(math.floor(
            (max_length-MIN_TASK_ID_CHARS-2)/float(2)))
        hostname = hostname[:hostname_chars]
        step_name = step_name[:step_name_chars]
    name_base = '-'.join([hostname, step_name, attempt_id])
    return _sanitize_instance_name(name_base, max_length)


def get_worker_name(hostname, step_name, attempt_id, max_length, silent=False):
    worker_name = _get_base_name(hostname, step_name, attempt_id, max_length)
    if not silent:
        print worker_name
    return worker_name


def _sanitize_instance_name(name, max_length):
    """Instance names must start with a lowercase letter.
    All following characters must be a dash, lowercase letter,
    or digit.
    """
    name = str(name).lower()                # make all letters lowercase
    name = re.sub(r'[^-a-z0-9]', '', name)  # remove invalid characters
    # remove non-lowercase letters from the beginning
    name = re.sub(r'^[^a-z]+', '', name)
    name = name[:max_length]
    name = re.sub(r'-+$', '', name)         # remove hyphens from the end
    return name


def sanitize_server_name(name, max_length, silent=False):
    max_length = int(max_length)
    server_name = _sanitize_instance_name(name, max_length)
    if not server_name:
        raise Exception('Failed to sanitize server name "%s"' % name)
    if not silent:
        print server_name
    return server_name
