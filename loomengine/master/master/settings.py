# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.7/howto/deployment/checklist/

import datetime
import json
import logging
import os
import random
import socket
import sys
import tempfile
import warnings

def to_boolean(value):
    if value is None:
        return False
    if str(value).upper() == 'FALSE':
        return False
    if str(value).upper() == 'TRUE':
        return True
    raise Exception("Invalid value %s. Expected True or False")

def to_list(value):
    if value is None:
        return []
    value = value.strip(' "\'')
    list_str = value.lstrip('[').rstrip(']')
    if list_str == '':
        return []
    list = list_str.split(',')
    return [item.strip(' "\'') for item in list]

SETTINGS_DIR = os.path.dirname(__file__)
BASE_DIR = (os.path.join(SETTINGS_DIR, '..'))
sys.path.append(BASE_DIR)
PORTAL_ROOT = os.path.join(BASE_DIR, '..', 'portal')

# Security settings
DEBUG = to_boolean(os.getenv('LOOM_DEBUG'))
SECRET_KEY = os.getenv(
    'LOOM_MASTER_SECRET_KEY',
    ''.join([random.SystemRandom()\
             .choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)')
             for i in range(50)]))
CORS_ORIGIN_ALLOW_ALL = to_boolean(
    os.getenv('LOOM_MASTER_CORS_ORIGIN_ALLOW_ALL', 'False'))
CORS_ORIGIN_WHITELIST = to_list(os.getenv('LOOM_MASTER_CORS_ORIGIN_WHITELIST', '[]'))

ALLOWED_HOSTS = to_list(os.getenv('LOOM_MASTER_ALLOWED_HOSTS', '[*]'))

LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING').upper()

WORKER_TYPE = os.getenv('WORKER_TYPE', 'LOCAL').upper()
LOOM_STORAGE_TYPE = os.getenv('LOOM_STORAGE_TYPE', 'LOCAL').upper()

STATIC_ROOT = os.getenv('LOOM_MASTER_STATIC_ROOT', '/tmp/static')

MASTER_URL_FOR_WORKER = os.getenv('MASTER_URL_FOR_WORKER', 'http://127.0.0.1:8000')
MASTER_URL_FOR_SERVER = os.getenv('MASTER_URL_FOR_SERVER', 'http://127.0.0.1:8000')
LOOM_STORAGE_ROOT = os.path.expanduser(os.getenv('LOOM_STORAGE_ROOT', '~/loom-data'))
FILE_ROOT_FOR_WORKER = os.path.expanduser(
    os.getenv('FILE_ROOT_FOR_WORKER', LOOM_STORAGE_ROOT))

LOOM_SETTINGS_PATH = os.path.expanduser(os.getenv('LOOM_SETTINGS_PATH','~/.loom/'))
TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS = os.getenv('LOOM_TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS', '60')
TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS = os.getenv('LOOM_TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS', '300')
PRESERVE_ON_FAILURE = to_boolean(os.getenv('LOOM_PRESERVE_ON_FAILURE', 'False'))
PRESERVE_ALL = to_boolean(os.getenv('LOOM_PRESERVE_ALL', 'False'))
MAXIMUM_TASK_RETRIES = os.getenv('LOOM_MAXIMUM_TASK_RETRIES', '2')

# GCP settings
GCE_EMAIL = os.getenv('GCE_EMAIL')
GCE_PROJECT = os.getenv('GCE_PROJECT', '')
GCE_PEM_FILE_PATH = os.getenv('GCE_PEM_FILE_PATH')
GOOGLE_STORAGE_BUCKET = os.getenv('LOOM_GOOGLE_STORAGE_BUCKET', '')

WORKER_BOOT_DISK_TYPE = os.getenv('WORKER_BOOT_DISK_TYPE')
WORKER_BOOT_DISK_SIZE = os.getenv('WORKER_BOOT_DISK_SIZE')
WORKER_CUSTOM_SUBNET = os.getenv('WORKER_CUSTOM_SUBNET', '')
WORKER_LOCATION = os.getenv('WORKER_LOCATION')
WORKER_NETWORK = os.getenv('WORKER_NETWORK')
WORKER_SCRATCH_DISK_MOUNT_POINT = os.getenv('WORKER_SCRATCH_DISK_MOUNT_POINT')
WORKER_SCRATCH_DISK_TYPE = os.getenv('WORKER_SCRATCH_DISK_TYPE')
WORKER_SCRATCH_DISK_SIZE = os.getenv('WORKER_SCRATCH_DISK_SIZE')
WORKER_SKIP_INSTALLS = os.getenv('WORKER_SKIP_INSTALLS')
WORKER_TAGS = os.getenv('WORKER_TAGS')
WORKER_USES_SERVER_INTERNAL_IP = os.getenv('WORKER_USES_SERVER_INTERNAL_IP')
WORKER_VM_IMAGE = os.getenv('WORKER_VM_IMAGE')

def _get_run_task_playbook_path():
    if not os.getenv('LOOM_RUN_TASK_PLAYBOOK'):
        return None
    return os.path.join(PLAYBOOKS_PATH,
                        os.getenv('LOOM_RUN_TASK_PLAYBOOK'))

LOOM_SETTINGS_HOME = os.getenv('LOOM_SETTINGS_HOME', os.path.expanduser('~/.loom'))
PLAYBOOK_PATH = os.path.join(LOOM_SETTINGS_HOME, os.getenv('LOOM_PLAYBOOK_DIR', 'playbooks'))
LOOM_RUN_TASK_PLAYBOOK = os.getenv('LOOM_RUN_TASK_PLAYBOOK')
LOOM_CLEANUP_TASK_PLAYBOOK = os.getenv('LOOM_CLEANUP_TASK_PLAYBOOK')

# Database settings
LOOM_MYSQL_PASSWORD = os.getenv('LOOM_MYSQL_PASSWORD')
LOOM_MYSQL_HOST = os.getenv('LOOM_MYSQL_HOST')
LOOM_MYSQL_USER = os.getenv('LOOM_MYSQL_USER')
LOOM_MYSQL_DATABASE = os.getenv('LOOM_MYSQL_DATABASE')
LOOM_MYSQL_PORT = os.getenv('LOOM_MYSQL_PORT', 3306)
LOOM_MYSQL_SSL_CA_CERT_PATH = os.getenv('LOOM_MYSQL_SSL_CA_CERT_PATH')
LOOM_MYSQL_SSL_CLIENT_CERT_PATH = os.getenv('LOOM_MYSQL_SSL_CLIENT_CERT_PATH')
LOOM_MYSQL_SSL_CLIENT_KEY_PATH = os.getenv('LOOM_MYSQL_SSL_CLIENT_KEY_PATH')

# Message broker settings
LOOM_RABBITMQ_PASSWORD = os.getenv('LOOM_RABBITMQ_PASSWORD', 'guest')
LOOM_RABBITMQ_USER = os.getenv('LOOM_RABBITMQ_USER', 'guest')
LOOM_RABBITMQ_VHOST = os.getenv('LOOM_RABBITMQ_VHOST', '/')
LOOM_RABBITMQ_HOST = os.getenv('LOOM_RABBITMQ_HOST', 'rabbitmq')
LOOM_RABBITMQ_PORT = os.getenv('LOOM_RABBITMQ_PORT', '5672')

def _get_ansible_inventory():
    ansible_inventory = os.getenv('LOOM_ANSIBLE_INVENTORY', 'localhost,')
    if ',' not in ansible_inventory:
	ansible_inventory = os.path.join(
            os.getenv('LOOM_SETTINGS_HOME'),
            os.getenv('LOOM_INVENTORY_DIR'),
            os.getenv('LOOM_ANSIBLE_INVENTORY'))
    return ansible_inventory

ANSIBLE_INVENTORY = _get_ansible_inventory()
LOOM_SSH_PRIVATE_KEY_PATH = os.getenv('LOOM_SSH_PRIVATE_KEY_PATH')

KEEP_DUPLICATE_FILES = True
FORCE_RERUN = True

# For testing only
TEST_DISABLE_ASYNC_DELAY = to_boolean(os.getenv('TEST_DISABLE_ASYNC_DELAY', False))
TEST_NO_TASK_CREATION = to_boolean(os.getenv('TEST_NO_TASK_CREATION', False))
TEST_NO_RUN_TASK_ATTEMPT = to_boolean(os.getenv('TEST_NO_RUN_TASK_ATTEMPT', False))
TEST_NO_POSTPROCESS = to_boolean(os.getenv('TEST_NO_POSTPROCESS', False))
TEST_NO_PUSH_INPUTS_ON_RUN_CREATION = to_boolean(os.getenv(
    'TEST_NO_PUSH_INPUTS_ON_RUN_CREATION', False))


# Fixed settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
CELERY_ALWAYS_EAGER = True
APPEND_SLASH = True
ROOT_URLCONF = 'master.urls'

# Celery
CELERY_RESULT_BACKEND = 'django-cache'
CELERY_BROKER_URL = 'amqp://%s:%s@%s:%s/%s' \
                    % (LOOM_RABBITMQ_USER, LOOM_RABBITMQ_PASSWORD,
                       LOOM_RABBITMQ_HOST, LOOM_RABBITMQ_PORT,
                       LOOM_RABBITMQ_VHOST)
CELERY_BROKER_POOL_LIMIT = 50
CELERYD_TASK_SOFT_TIME_LIMIT = 60

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django_extensions',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_swagger',
    'django_celery_results',
    'api',
]

MIDDLEWARE_CLASSES = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
#    'django.contrib.auth.middleware.AuthenticationMiddleware',
#    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

REST_FRAMEWORK = {
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, "templates")],
	'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
		'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'master.wsgi.application'

def _get_sqlite_databases():
    return {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'loomdb.sqlite3'),
        }
    }

def _get_mysql_databases():
    if not LOOM_MYSQL_USER:
        raise Exception(
            "LOOM_MYSQL_USER is a required setting if LOOM_MYSQL_HOST is set")
    if not LOOM_MYSQL_DATABASE:
        raise Exception(
            "LOOM_MYSQL_DATABASE is a required setting if LOOM_MYSQL_HOST is set")

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'HOST': LOOM_MYSQL_HOST,
            'NAME': LOOM_MYSQL_DATABASE,
            'USER': LOOM_MYSQL_USER,
            'PORT': LOOM_MYSQL_PORT,
        }
    }

    if LOOM_MYSQL_PASSWORD:
        DATABASES['default'].update({
            'PASSWORD': LOOM_MYSQL_PASSWORD
        })
    if LOOM_MYSQL_SSL_CA_CERT_PATH \
       or LOOM_MYSQL_SSL_CLIENT_CERT_PATH \
       or LOOM_MYSQL_SSL_CLIENT_KEY_PATH:
        if not (LOOM_MYSQL_SSL_CA_CERT_PATH \
                and LOOM_MYSQL_SSL_CLIENT_CERT_PATH \
                and LOOM_MYSQL_SSL_CLIENT_KEY_PATH):
            raise Exception(
                'One or more required values missing: '\
                'LOOM_MYSQL_SSL_CA_CERT_PATH="%s", '\
                'LOOM_MYSQL_SSL_CLIENT_CERT_PATH="%s", '\
                'LOOM_MYSQL_SSL_CLIENT_KEY_PATH="%s"' % (
                    LOOM_MYSQL_SSL_CA_CERT_PATH,
                    LOOM_MYSQL_SSL_CLIENT_CERT_PATH,
                    LOOM_MYSQL_SSL_CLIENT_KEY_PATH))
        else:
            DATABASES['default'].update({
                'OPTIONS': {
                    'ssl': {
                        'ca': LOOM_MYSQL_SSL_CA_CERT_PATH,
                        'cert': LOOM_MYSQL_SSL_CLIENT_CERT_PATH,
                        'key': LOOM_MYSQL_SSL_CLIENT_KEY_PATH
                    }
                }
            })
    return DATABASES

# Database
if LOOM_MYSQL_HOST:
    DATABASES = _get_mysql_databases()
else:
    DATABASES = _get_sqlite_databases()

# Logging
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    DISABLE_LOGGING = True
else:
    DISABLE_LOGGING = False

if DISABLE_LOGGING:
    LOGGING = {}
else:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(levelname)s [%(asctime)s] %(message)s'
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
            }
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': LOG_LEVEL,
            },
            'loomengine': {
                'handlers': ['console'],
                'level': LOG_LEVEL,
            },
            'api': {
                'handlers': ['console'],
                'level': LOG_LEVEL,
            },
        },
    }

STATIC_URL = '/%s/' % os.path.basename(STATIC_ROOT)
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

INTERNAL_IPS = [
    "127.0.0.1",
]

if DEBUG:
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE_CLASSES.append('debug_toolbar.middleware.DebugToolbarMiddleware')

    def custom_show_toolbar(request):
        return True

    DEBUG_TOOLBAR_CONFIG = {
        "INTERCEPT_REDIRECTS": False,
        'MEDIA_URL': '/__debug__/m/',
        'SHOW_TOOLBAR_CALLBACK': custom_show_toolbar,
    }
