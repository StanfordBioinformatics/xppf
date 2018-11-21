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
from django.core.exceptions import ValidationError

SESSION_BACKED = 'django.contrib.sessions.backends.db'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

def to_boolean(value):
    if value in [None, '', False]:
        return False
    if value == True:
        return True
    if str(value).lower() == 'false':
        return False
    if str(value).lower() == 'true':
        return True
    raise Exception("Invalid value %s. Expected True or False")

def to_float(value):
    if value is None:
        return None
    if value == '':
        return None
    return float(value)

def to_int(value):
    if value is None:
        return None
    if value == '':
        return None
    return int(value)

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
PORTAL_ROOT = os.path.join(BASE_DIR, '..', '..', 'portal')

# Security settings
DEBUG = to_boolean(os.getenv('LOOM_DEBUG'))

secret_file = os.path.join(os.path.dirname(__file__),'secret.txt')
if os.path.exists(secret_file):
    with open(secret_file) as f:
        SECRET_KEY = f.read()
else:
    SECRET_KEY = os.getenv(
        'LOOM_SERVER_SECRET_KEY',
        ''.join([random.SystemRandom()\
                 .choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)')
                 for i in range(50)]))
    with open(secret_file, 'w') as f:
        f.write(SECRET_KEY)

CORS_ORIGIN_ALLOW_ALL = to_boolean(
    os.getenv('LOOM_SERVER_CORS_ORIGIN_ALLOW_ALL', 'False'))
CORS_ORIGIN_WHITELIST = to_list(os.getenv('LOOM_SERVER_CORS_ORIGIN_WHITELIST', '[]'))

CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

ALLOWED_HOSTS = to_list(os.getenv('LOOM_SERVER_ALLOWED_HOSTS', '[*]'))

LOGIN_REQUIRED = to_boolean(os.getenv('LOOM_LOGIN_REQUIRED', 'True'))

LOG_LEVEL = os.getenv('LOG_LEVEL', 'WARNING').upper()

STORAGE_TYPE = os.getenv('LOOM_STORAGE_TYPE', 'local').lower()

STATIC_ROOT = os.getenv('LOOM_SERVER_STATIC_ROOT', '/var/www/loom/static')

SERVER_NAME = os.getenv('LOOM_SERVER_NAME', 'loom') # used in attempt container names
SERVER_URL_FOR_WORKER = os.getenv('SERVER_URL_FOR_WORKER', 'http://127.0.0.1:8000')
SERVER_URL_FOR_CLIENT = os.getenv('SERVER_URL_FOR_CLIENT', 'http://127.0.0.1:8000')

# GCP settings
GCE_EMAIL = os.getenv('GCE_EMAIL')
GCE_PROJECT = os.getenv('GCE_PROJECT', '')
GCE_PEM_FILE_PATH = os.getenv('GCE_PEM_FILE_PATH')
GOOGLE_STORAGE_BUCKET = os.getenv('LOOM_GOOGLE_STORAGE_BUCKET', '')

SETTINGS_HOME = os.getenv('LOOM_SETTINGS_HOME', os.path.expanduser('~/.loom'))
PLAYBOOK_PATH = os.path.join(SETTINGS_HOME, os.getenv('LOOM_PLAYBOOK_DIR', 'playbooks'))
RUN_TASK_ATTEMPT_PLAYBOOK = os.getenv('LOOM_RUN_TASK_ATTEMPT_PLAYBOOK')
CLEANUP_TASK_ATTEMPT_PLAYBOOK = os.getenv('LOOM_CLEANUP_TASK_ATTEMPT_PLAYBOOK')

def _add_url_prefix(path):
    if STORAGE_TYPE.lower() == 'local':
	return 'file://' + path
    elif STORAGE_TYPE.lower() == 'google_storage':
        return 'gs://' + GOOGLE_STORAGE_BUCKET + path
    else:
        raise ValidationError(
            'Couldn\'t recognize value for setting STORAGE_TYPE="%s"'\
	    % STORAGE_TYPE)
STORAGE_ROOT = os.path.expanduser(os.getenv('LOOM_STORAGE_ROOT', '~/loomdata'))
INTERNAL_STORAGE_ROOT = os.path.expanduser(
    os.getenv('LOOM_INTERNAL_STORAGE_ROOT', STORAGE_ROOT))
STORAGE_ROOT_WITH_PREFIX =_add_url_prefix(STORAGE_ROOT)
INTERNAL_STORAGE_ROOT_WITH_PREFIX =_add_url_prefix(INTERNAL_STORAGE_ROOT)
DISABLE_DELETE = to_boolean(os.getenv('LOOM_DISABLE_DELETE', 'False'))
FORCE_RERUN = to_boolean(os.getenv('LOOM_FORCE_RERUN', 'False'))

TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS = float(os.getenv('LOOM_TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS', '60'))
TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS = float(os.getenv('LOOM_TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS', TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS*2.5))
SYSTEM_CHECK_INTERVAL_MINUTES = float(os.getenv('LOOM_SYSTEM_CHECK_INTERVAL_MINUTES', '15'))
PRESERVE_ON_FAILURE = to_boolean(os.getenv('LOOM_PRESERVE_ON_FAILURE', 'False'))
PRESERVE_ALL = to_boolean(os.getenv('LOOM_PRESERVE_ALL', 'False'))
TASK_TIMEOUT_HOURS = float(os.getenv(
    'LOOM_TASK_TIMEOUT_HOURS', '24.0'))
MAXIMUM_RETRIES_FOR_ANALYSIS_FAILURE = int(os.getenv(
    'LOOM_MAXIMUM_TASK_RETRIES_FOR_ANALYSIS_FAILURE', '1'))
MAXIMUM_RETRIES_FOR_SYSTEM_FAILURE = int(os.getenv(
    'LOOM_MAXIMUM_TASK_RETRIES_FOR_SYSTEM_FAILURE', '10'))
MAXIMUM_RETRIES_FOR_TIMEOUT_FAILURE = int(os.getenv(
    'LOOM_MAXIMUM_TASK_RETRIES_FOR_TIMEOUT_FAILURE', '0'))
MAXIMUM_TREE_DEPTH = int(os.getenv('LOOM_MAXIMUM_TREE_DEPTH', '10'))

DEFAULT_DOCKER_REGISTRY = os.getenv('LOOM_DEFAULT_DOCKER_REGISTRY', '')

# Database settings
# Any defaults must match defaults in playbook
MYSQL_HOST = os.getenv('LOOM_MYSQL_HOST')
MYSQL_USER = os.getenv('LOOM_MYSQL_USER', 'loom')
MYSQL_PASSWORD = os.getenv('LOOM_MYSQL_PASSWORD', 'loompass')
MYSQL_DATABASE = os.getenv('LOOM_MYSQL_DATABASE', 'loomdb')
MYSQL_PORT = int(os.getenv('LOOM_MYSQL_PORT', 3306))
MYSQL_SSL_CA_CERT_PATH = os.getenv('LOOM_MYSQL_SSL_CA_CERT_PATH')
MYSQL_SSL_CLIENT_CERT_PATH = os.getenv('LOOM_MYSQL_SSL_CLIENT_CERT_PATH')
MYSQL_SSL_CLIENT_KEY_PATH = os.getenv('LOOM_MYSQL_SSL_CLIENT_KEY_PATH')

# Email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('LOOM_EMAIL_HOST', None)
EMAIL_PORT = to_int(os.getenv('LOOM_EMAIL_PORT', 587))
EMAIL_HOST_USER = os.getenv('LOOM_EMAIL_HOST_USER', None)
EMAIL_HOST_PASSWORD = os.getenv('LOOM_EMAIL_HOST_PASSWORD', None)
EMAIL_USE_TLS = to_boolean(os.getenv('LOOM_EMAIL_USE_TLS', True))
EMAIL_USE_SSL = to_boolean(os.getenv('LOOM_EMAIL_USE_SSL', True))
EMAIL_TIMEOUT = to_float(os.getenv('LOOM_EMAIL_TIMEOUT', 0.0))
EMAIL_SSL_KEYFILE = os.getenv('LOOM_EMAIL_SSL_KEYFILE', None)
EMAIL_SSL_CERTFILE = os.getenv('LOOM_EMAIL_SSL_CERTFILE', None)
DEFAULT_FROM_EMAIL = os.getenv('LOOM_DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
NOTIFICATION_ADDRESSES = to_list(os.getenv('LOOM_NOTIFICATION_ADDRESSES', '[]'))
NOTIFICATION_HTTPS_VERIFY_CERTIFICATE = to_boolean(os.getenv('LOOM_NOTIFICATION_HTTPS_VERIFY_CERTIFICATE', True))

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
            PLAYBOOK_PATH,
            os.getenv('LOOM_ANSIBLE_INVENTORY'))
    return ansible_inventory

ANSIBLE_INVENTORY = _get_ansible_inventory()
LOOM_SSH_PRIVATE_KEY_PATH = os.getenv('LOOM_SSH_PRIVATE_KEY_PATH')

# For testing only
TEST_DISABLE_ASYNC_DELAY = to_boolean(os.getenv('TEST_DISABLE_ASYNC_DELAY', False))
TEST_NO_CREATE_TASK = to_boolean(os.getenv('TEST_NO_CREATE_TASK', False))
TEST_NO_RUN_TASK_ATTEMPT = to_boolean(os.getenv('TEST_NO_RUN_TASK_ATTEMPT', False))
TEST_NO_TASK_ATTEMPT_CLEANUP = to_boolean(os.getenv(
    'TEST_NO_TASK_ATTEMPT_CLEANUP', False))
TEST_NO_PUSH_INPUTS= to_boolean(os.getenv('TEST_NO_PUSH_INPUTS', False))

# Fixed settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
CELERY_ALWAYS_EAGER = True
APPEND_SLASH = True
ROOT_URLCONF = 'loomengine_server.core.urls'

# Celery
CELERY_RESULT_BACKEND = 'django-cache'
CELERY_BROKER_URL = 'amqp://%s:%s@%s:%s/%s' \
                    % (LOOM_RABBITMQ_USER, LOOM_RABBITMQ_PASSWORD,
                       LOOM_RABBITMQ_HOST, LOOM_RABBITMQ_PORT,
                       LOOM_RABBITMQ_VHOST)
CELERY_BROKER_POOL_LIMIT = 50
CELERYD_TASK_SOFT_TIME_LIMIT = 60

LOGIN_REDIRECT_URL = '/'

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django_extensions',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_swagger',
    'django_celery_results',
    'api',
]

MIDDLEWARE_CLASSES = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if LOGIN_REQUIRED:
    drf_permission_classes = ('rest_framework.permissions.IsAuthenticated',)
else:
    drf_permission_classes = ('rest_framework.permissions.AllowAny',)

REST_FRAMEWORK = {
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': drf_permission_classes,
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.TokenAuthentication',
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

WSGI_APPLICATION = 'loomengine_server.core.wsgi.application'

def _get_sqlite_databases():
    return {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'loomdb.sqlite3'),
        }
    }

def _get_mysql_databases():
    if not MYSQL_USER:
        raise Exception(
            "LOOM_MYSQL_USER is a required setting if LOOM_MYSQL_HOST is set")
    if not MYSQL_DATABASE:
        raise Exception(
            "LOOM_MYSQL_DATABASE is a required setting if LOOM_MYSQL_HOST is set")

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'HOST': MYSQL_HOST,
            'NAME': MYSQL_DATABASE,
            'USER': MYSQL_USER,
            'PORT': MYSQL_PORT,
        }
    }

    if MYSQL_PASSWORD:
        DATABASES['default'].update({
            'PASSWORD': MYSQL_PASSWORD
        })
    if MYSQL_SSL_CA_CERT_PATH \
       or MYSQL_SSL_CLIENT_CERT_PATH \
       or MYSQL_SSL_CLIENT_KEY_PATH:
        if not (MYSQL_SSL_CA_CERT_PATH \
                and MYSQL_SSL_CLIENT_CERT_PATH \
                and MYSQL_SSL_CLIENT_KEY_PATH):
            raise Exception(
                'One or more required values missing: '\
                'LOOM_MYSQL_SSL_CA_CERT_PATH="%s", '\
                'LOOM_MYSQL_SSL_CLIENT_CERT_PATH="%s", '\
                'LOOM_MYSQL_SSL_CLIENT_KEY_PATH="%s"' % (
                    MYSQL_SSL_CA_CERT_PATH,
                    MYSQL_SSL_CLIENT_CERT_PATH,
                    MYSQL_SSL_CLIENT_KEY_PATH))
        else:
            DATABASES['default'].update({
                'OPTIONS': {
                    'ssl': {
                        'ca': MYSQL_SSL_CA_CERT_PATH,
                        'cert': MYSQL_SSL_CLIENT_CERT_PATH,
                        'key': MYSQL_SSL_CLIENT_KEY_PATH
                    }
                }
            })
    return DATABASES

# Database
if MYSQL_HOST:
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

# This is needed for nginx reverse proxy to work
INTERNAL_IPS = ["127.0.0.1",]

if DEBUG or (len(sys.argv) > 1 and sys.argv[1] == 'collectstatic'):
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE_CLASSES.append('debug_toolbar.middleware.DebugToolbarMiddleware')

    def custom_show_toolbar(request):
        return True

    DEBUG_TOOLBAR_CONFIG = {
        "INTERCEPT_REDIRECTS": False,
        'MEDIA_URL': '/__debug__/m/',
        'SHOW_TOOLBAR_CALLBACK': custom_show_toolbar,
    }

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': '232871b2',
        'TIMEOUT': 0,
    }
}
