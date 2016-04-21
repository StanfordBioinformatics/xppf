#Common functions related to cloud platforms that can be used by all components.

def on_gcloud_vm():
    """ Determines if we're running on a GCE instance."""
    import requests
    r = None
    try:
        r = requests.get('http://metadata.google.internal')
    except requests.ConnectionError:
        return False

    try:
        if r.headers['Metadata-Flavor'] == 'Google' and r.headers['Server'] == 'Metadata Server for VM':
            return True
    except KeyError:
        return False
