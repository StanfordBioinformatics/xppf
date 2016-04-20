# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.7/howto/deployment/checklist/

import datetime
import os
import socket
import sys
import warnings

include_models = os.getenv('GRAPH_MODELS_INCLUDE_MODELS')

BASE_DIR = os.path.dirname(__file__)
DOC_ROOT = os.path.join(BASE_DIR, '..', 'webclient')

def get_secret_key():
    SECRET_FILE = os.path.join(BASE_DIR, 'secret.txt')
    try:
        SECRET_KEY = open(SECRET_FILE).read().strip()
        return SECRET_KEY
    except IOError:
        try:
            import random
            SECRET_KEY = ''.join([random.SystemRandom().choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)])
            secret = file(SECRET_FILE, 'w')
            secret.write(SECRET_KEY)
            secret.close()
            return SECRET_KEY
        except IOError:
            Exception('Failed to create file for secret key. Please create file "%s"' \
            ' with a random secret key' % SECRET_FILE)

SECRET_KEY = get_secret_key()

# TODO
# if os.getenv('LOOM_DEBUG_TRUE'):
DEBUG = True
TEMPLATE_DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1']

INSTALLED_APPS = (
#    'django.contrib.auth',
    'django_extensions',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'universalmodels',
    'analysis',
    'editor',
)

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
#    'django.contrib.auth.middleware.AuthenticationMiddleware',
#    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

ROOT_URLCONF = 'loomserver.urls'

WSGI_APPLICATION = 'loomserver.wsgi.application'

MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')

def get_database_name():
    DATABASE_NAME_FILE = os.path.join(BASE_DIR, 'dbname.txt')
    try:
        DATABASE_NAME = open(DATABASE_NAME_FILE).read().strip()
        return DATABASE_NAME
    except IOError:
        try:
            DATABASE_NAME = datetime.datetime.utcnow().strftime("loom-%Y%m%d-%H%M%S")
            f = file(DATABASE_NAME_FILE, 'w')
            f.write(DATABASE_NAME)
            f.close()
            return DATABASE_NAME
        except IOError:
            Exception('Failed to create file for database name. Please create file "%s"' \
                      ' with a name for the Loom database' % DATABASE_NAME_FILE)

DATABASE_NAME = get_database_name()

if not os.getenv('LOOM_TEST_DATABASE'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, DATABASE_NAME+'.sqlite3'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'test_loom.sqlite3'),
        }
    }

def _get_django_handler():
    DJANGO_LOGFILE = os.getenv('DJANGO_LOGFILE', None)
    if DJANGO_LOGFILE is not None:
        handler = {
            'class': 'logging.FileHandler',
            'filename': DJANGO_LOGFILE,
            'formatter': 'default',
            }
    else:
        handler = {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            }
    return handler

def _get_loom_handler():
    WEBSERVER_LOGFILE = os.getenv('WEBSERVER_LOGFILE', None)
    if WEBSERVER_LOGFILE  is not None:
        if not os.path.exists(os.path.dirname(WEBSERVER_LOGFILE)):
            os.makedirs(os.path.dirname(WEBSERVER_LOGFILE))
        handler = {
            'class': 'logging.FileHandler',
            'filename': WEBSERVER_LOGFILE,
            'formatter': 'default',
            }
    else:
        handler = {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            }
    return handler

def _get_log_level():
    DEFAULT_LOG_LEVEL = 'INFO'
    LOG_LEVEL = os.getenv('LOG_LEVEL', DEFAULT_LOG_LEVEL)
    return LOG_LEVEL.upper()

LOG_LEVEL = _get_log_level()
WORKER_LOGFILE = os.getenv('WORKER_LOGFILE', None)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(levelname)s [%(asctime)s] %(message)s'
            },
        },
    'handlers': {
        'django_handler': _get_django_handler(),
        'django_request_handler': _get_django_handler(),
        'loom_handler': _get_loom_handler(),
        },
    'loggers': {
        'django': {
            'handlers': ['django_handler'],
            'level': LOG_LEVEL,
            },
        'django.request': {
            'handlers': ['django_request_handler'],
            'level': LOG_LEVEL,
            },
        'loom': {
            'handlers': ['loom_handler'],
            'level': LOG_LEVEL,
            },
        },
    }

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True

STATIC_URL = '/static/'

WORKER_TYPE = os.getenv('WORKER_TYPE', 'LOCAL')
MASTER_URL_FOR_WORKER = os.getenv('MASTER_URL_FOR_WORKER', 'http://127.0.0.1:8000')
FILE_SERVER_FOR_WORKER = os.getenv('FILE_SERVER_FOR_WORKER', socket.getfqdn())
FILE_ROOT = os.getenv('FILE_ROOT', os.path.join(os.getenv('HOME'),'working_dir'))
FILE_ROOT_FOR_WORKER = os.getenv('FILE_ROOT_FOR_WORKER')

FILE_SERVER_TYPE = os.getenv('FILE_SERVER_TYPE')
IMPORT_DIR = os.getenv('IMPORT_DIR')
STEP_RUNS_DIR = os.getenv('STEP_RUNS_DIR')
BUCKET_ID = os.getenv('BUCKET_ID')
PROJECT_ID = os.getenv('PROJECT_ID')
ANSIBLE_PEM_FILE = os.getenv('ANSIBLE_PEM_FILE')
GCE_KEY_FILE = os.getenv('GCE_KEY_FILE')
WORKER_VM_IMAGE = os.getenv('WORKER_VM_IMAGE')
WORKER_LOCATION = os.getenv('WORKER_LOCATION')
WORKER_DISK_TYPE = os.getenv('WORKER_DISK_TYPE')
WORKER_DISK_SIZE = os.getenv('WORKER_DISK_SIZE')
WORKER_DISK_MOUNT_POINT = os.getenv('WORKER_DISK_MOUNT_POINT')

# Graph Models settings to generate model schema plots
GRAPH_MODELS = {
    'include_models': include_models,
}
