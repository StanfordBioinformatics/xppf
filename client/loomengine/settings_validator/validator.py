import os
import re
import warnings

from loomengine import to_bool


class SettingsValidationError(Exception):
    pass


class SettingsValidator(object):
    """Base class for settings validators
    """

    errors = []

    KNOWN_SETTINGS = (
        'LOOM_PLAYBOOK_DIR',
        'LOOM_RESOURCE_DIR',
        'LOOM_CONNECTION_SETTINGS_FILE',
        'LOOM_SERVER_SETTINGS_FILE',
        'LOOM_DOCKER_IMAGE',
        'LOOM_START_SERVER_PLAYBOOK',
        'LOOM_STOP_SERVER_PLAYBOOK',
        'LOOM_DELETE_SERVER_PLAYBOOK',
        'LOOM_RUN_TASK_ATTEMPT_PLAYBOOK',
        'LOOM_CLEANUP_TASK_ATTEMPT_PLAYBOOK',
        'LOOM_STORAGE_TYPE',
        'LOOM_ANSIBLE_INVENTORY',
        'LOOM_SERVER_NAME',
        'LOOM_DEBUG',
        'LOOM_LOG_LEVEL',
        'LOOM_MODE',
        'LOOM_LOGIN_REQUIRED',
        'LOOM_ADMIN_USERNAME',
        'LOOM_ADMIN_PASSWORD',
        'LOOM_ANSIBLE_HOST_KEY_CHECKING',
        'ANSIBLE_HOST_KEY_CHECKING',  # copy of LOOM_ANSIBLE_HOST_KEY_CHECKING
        'LOOM_DEFAULT_DOCKER_REGISTRY',
        'LOOM_STORAGE_ROOT',
        'LOOM_INTERNAL_STORAGE_ROOT',
        'LOOM_SYSTEM_CHECK_INTERVAL_MINUTES',
        'LOOM_MAXIMUM_RETRIES_FOR_TIMEOUT_FAILURE',
        'LOOM_MAXIMUM_RETRIES_FOR_ANALYSIS_FAILURE',
        'LOOM_MAXIMUM_RETRIES_FOR_SYSTEM_FAILURE',
        'LOOM_MAXIMUM_TREE_DEPTH',
        'LOOM_TASKRUNNER_HEARTBEAT_INTERVAL_SECONDS',
        'LOOM_TASKRUNNER_HEARTBEAT_TIMEOUT_SECONDS',
        'LOOM_TASK_TIMEOUT_HOURS',
        'LOOM_PRESERVE_ON_FAILURE',
        'LOOM_PRESERVE_ALL',
        'LOOM_DISABLE_DELETE',
        'LOOM_FORCE_DB_MIGRATIONS_ON_START',
        'LOOM_HTTP_PORT',
        'LOOM_HTTPS_PORT',
        'LOOM_HTTP_PORT_ENABLED',
        'LOOM_HTTPS_PORT_ENABLED',
        'LOOM_SSL_CERT_CREATE_NEW',
        'LOOM_SSL_CERT_C',
        'LOOM_SSL_CERT_ST',
        'LOOM_SSL_CERT_L',
        'LOOM_SSL_CERT_O',
        'LOOM_SSL_CERT_CN',
        'LOOM_SSL_CERT_KEY_FILE',
        'LOOM_SSL_CERT_FILE',
        'LOOM_SERVER_INTERNAL_IP',
        'LOOM_SERVER_INTERNAL_PORT',
        'LOOM_SERVER_ALLOWED_HOSTS',
        'LOOM_SERVER_GUNICORN_WORKERS_COUNT',
        'LOOM_SERVER_STATIC_ROOT',
        'LOOM_SERVER_CORS_ORIGIN_ALLOW_ALL',
        'LOOM_SERVER_CORS_ORIGIN_WHITELIST',
        'LOOM_WORKER_CELERY_CONCURRENCY',
        'LOOM_MYSQL_CREATE_DOCKER_CONTAINER',
        'LOOM_MYSQL_HOST',
        'LOOM_MYSQL_PORT',
        'LOOM_MYSQL_USER',
        'LOOM_MYSQL_DATA_VOLUME',
        'LOOM_MYSQL_DATABASE',
        'LOOM_RABBITMQ_IMAGE',
        'LOOM_RABBITMQ_USER',
        'LOOM_RABBITMQ_PASSWORD',
        'LOOM_RABBITMQ_PORT',
        'LOOM_RABBITMQ_VHOST',
        'LOOM_RABBITMQ_DATA_VOLUME',
        'LOOM_NGINX_IMAGE',
        'LOOM_NGINX_SERVER_NAME',
        'LOOM_NGINX_WEBPORTAL_ROOT',
        'LOOM_FLUENTD_IMAGE',
        'LOOM_FLUENTD_PORT',
        'LOOM_FLUENTD_OUTPUTS',
        'LOOM_ELASTICSEARCH_IMAGE',
        'LOOM_ELASTICSEARCH_PORT',
        'LOOM_ELASTICSEARCH_DATA_VOLUME',
        'LOOM_ELASTICSEARCH_JAVA_OPTS',
        'LOOM_KIBANA_CONTAINER_NAME_SUFFIX',
        'LOOM_KIBANA_IMAGE',
        'LOOM_KIBANA_PORT',
        'LOOM_KIBANA_VERSION',
        'LOOM_WEBPORTAL_DATA_VOLUME',
        'LOOM_STATIC_DATA_VOLUME',
        'LOOM_FLOWER_INTERNAL_PORT',
        'LOOM_MYSQL_IMAGE',
        'LOOM_MYSQL_RANDOM_ROOT_PASSWORD',
        'LOOM_MYSQL_PASSWORD',
        'LOOM_MYSQL_SSL_CA_CERT_FILE',
        'LOOM_MYSQL_SSL_CLIENT_CERT_FILE',
        'LOOM_MYSQL_SSL_CLIENT_KEY_FILE',
        'LOOM_RABBITMQ_MANAGEMENT_IMAGE',
        'LOOM_EMAIL_HOST',
        'LOOM_EMAIL_PORT',
        'LOOM_EMAIL_HOST_USER',
        'LOOM_EMAIL_HOST_PASSWORD',
        'LOOM_EMAIL_USE_TLS',
        'LOOM_EMAIL_USE_SSL',
        'LOOM_EMAIL_TIMEOUT',
        'LOOM_EMAIL_SSL_KEYFILE',
        'LOOM_EMAIL_SSL_CERTFILE',
        'LOOM_DEFAULT_FROM_EMAIL',
        'LOOM_NOTIFICATION_ADDRESSES',
        'LOOM_NOTIFICATION_HTTPS_VERIFY_CERTIFICATE',
        'LOOM_GOOGLE_STORAGE_BUCKET',
        # gcloud settings
        'LOOM_GCE_PEM_FILE',
        'LOOM_GCE_PROJECT',
        'LOOM_GCE_EMAIL',
        'LOOM_SSH_PRIVATE_KEY_NAME',
        'LOOM_GCLOUD_SERVER_DISK_SIZE_GB',
        'LOOM_GCLOUD_SERVER_INSTANCE_IMAGE',
        'LOOM_GCLOUD_SERVER_INSTANCE_TYPE',
        'LOOM_GCLOUD_SERVER_NETWORK',
        'LOOM_GCLOUD_SERVER_SUBNETWORK',
        'LOOM_GCLOUD_SERVER_ZONE',
        'LOOM_GCLOUD_SERVER_SKIP_INSTALLS',
        'LOOM_GCLOUD_SERVER_EXTERNAL_IP',
        'LOOM_GCLOUD_WORKER_DISK_SIZE_GB',
        'LOOM_GCLOUD_WORKER_INSTANCE_IMAGE',
        'LOOM_GCLOUD_WORKER_INSTANCE_TYPE',
        'LOOM_GCLOUD_WORKER_NETWORK',
        'LOOM_GCLOUD_WORKER_SUBNETWORK',
        'LOOM_GCLOUD_WORKER_ZONE',
        'LOOM_GCLOUD_WORKER_SKIP_INSTALLS',
        'LOOM_GCLOUD_WORKER_EXTERNAL_IP',
        'LOOM_GCLOUD_WORKER_CONNECTION_SETTINGS_FILE',
        'LOOM_GCLOUD_WORKER_USES_SERVER_INTERNAL_IP',
        'LOOM_GCLOUD_CLIENT_USES_SERVER_INTERNAL_IP',
        'LOOM_GCLOUD_SERVER_USES_WORKER_INTERNAL_IP',
        'LOOM_GCLOUD_SERVER_TAGS',
        'LOOM_GCLOUD_WORKER_TAGS',
        'LOOM_GCLOUD_INSTANCE_NAME_MAX_LENGTH',
    )

    def __init__(self, settings):
        self.settings = settings

    def validate(self):
        for setting in self.settings:
            if setting not in self.KNOWN_SETTINGS:
                warnings.warn(
                    'Unrecognized setting "%s" will be ignored' % setting)

        self._validate_ssl_cert_settings()
        self._validate_server_name()
        self._validate_storage_root()
        self._validate_gcloud_settings()
        self._validate_auth_settings()
        self.raise_if_errors()

    def raise_if_errors(self):
        if self.errors:
            raise SettingsValidationError(self.errors)

    def _validate_ssl_cert_settings(self):
        if not to_bool(self.settings.get('LOOM_SSL_CERT_CREATE_NEW')) \
           and to_bool(self.settings.get('LOOM_HTTPS_PORT_ENABLED')):
            for setting in ['LOOM_SSL_CERT_KEY_FILE',
                            'LOOM_SSL_CERT_FILE']:
                if setting not in self.settings.keys():
                    self.errors.append(
                        'Missing setting "%s" required when '
                        'LOOM_SSL_CERT_CREATE_NEW=false and '
                        'LOOM_HTTPS_PORT_ENABLED=true' % setting)

    def _validate_server_name(self):
        max_len = int(self.settings.get(
            'LOOM_GCLOUD_INSTANCE_NAME_MAX_LENGTH', 63))
        server_name = self.settings.get('LOOM_SERVER_NAME')
        pattern = '^[a-z]([-a-z0-9]*[a-z0-9])?$'
        if not re.match(pattern, server_name):
            self.errors.append(
                'Invalid LOOM_SERVER_NAME "%s". Must start with a letter, '
                'contain only alphanumerics and hyphens, and cannot end '
                'with a hyphen' % server_name)
        if len(server_name) > max_len:
            self.errors.append(
                'Invalid LOOM_SERVER_NAME "%s". Cannot exceed %s letters.'
                % server_name, max_len)

    def _validate_storage_root(self):
        LOOM_STORAGE_ROOT = self.settings.get('LOOM_STORAGE_ROOT')
        if LOOM_STORAGE_ROOT and not os.path.isabs(LOOM_STORAGE_ROOT):
            self.errors.append(
                'Invalid value "%s" for setting LOOM_STORAGE_ROOT. '
                'Value must be an absolute path.' % LOOM_STORAGE_ROOT)

    def _validate_gcloud_settings(self):
        if not self.settings.get('LOOM_MODE') == 'gcloud':
            return
        for required_setting in [
                'LOOM_GCE_PEM_FILE',
                'LOOM_GCE_EMAIL',
                'LOOM_GCE_PROJECT',
                'LOOM_GOOGLE_STORAGE_BUCKET']:
            if required_setting not in self.settings.keys():
                self.errors.append(
                    'Missing setting "%s" is required when '
                    'LOOM_MODE="gcloud"' % required_setting)
            if self.settings.get('LOOM_STORAGE_TYPE').lower() == 'local':
                self.errors.append(
                    'Setting LOOM_STORAGE_TYPE=local not allowed '
                    'when LOOM_MODE==gcloud.')
        if self.settings.get('LOOM_GCLOUD_WORKER_EXTERNAL_IP'):
            ip = self.settings.get('LOOM_GCLOUD_WORKER_EXTERNAL_IP')
            if ip not in ['none', 'ephemeral']:
                self.errors.append(
                    'Invalid value "%s" for LOOM_GCLOUD_WORKER_EXTERNAL_IP. '
                    'Allowed values are "ephemeral" and "none". If you need '
                    'to restrict the IP address range, use a subnetwork.' % ip)

    def _validate_auth_settings(self):
        if to_bool(self.settings.get('LOOM_LOGIN_REQUIRED')):
            for required_setting in [
                    'LOOM_ADMIN_USERNAME',
                    'LOOM_ADMIN_PASSWORD']:
                if required_setting not in self.settings.keys():
                    self.errors.append(
                        'Missing setting "%s" is required when '
                        'LOOM_LOGIN_REQUIRED=true' % required_setting)

            username_regex = r'^[a-zA-Z0-8@\+\.\-]{1,150}$'
            username = self.settings.get('LOOM_ADMIN_USERNAME')
            if username and not re.match(username_regex, username):
                self.errors.append(
                    'Invalid LOOM_ADMIN_USERNAME "%s". '
                    'Must match regex %s.' % (
                        username, username_regex))
            if not to_bool(self.settings.get('LOOM_HTTPS_PORT_ENABLED')):
                self.errors.append(
                    'If LOOM_LOGIN_REQUIRED is true, you must set '
                    'LOOM_HTTPS_PORT_ENABLED=true')
