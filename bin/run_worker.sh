#!/bin/bash

BIN_PATH="`dirname \"$0\"`"

DEFAULT_LOG_LEVEL=info
DEFAULT_CELERY_CONCURRENCY=30

LOOM_LOG_LEVEL=${LOOM_LOG_LEVEL:-$DEFAULT_LOG_LEVEL}
LOOM_WORKER_CELERY_CONCURRENCY=${LOOM_WORKER_CELERY_CONCURRENCY:-$DEFAULT_CELERY_CONCURRENCY}

# omitting --without-gossip causes missed heartbeat errors
celery -A loomengine.master.master -P eventlet worker --concurrency=${LOOM_WORKER_CELERY_CONCURRENCY} --loglevel=${LOOM_LOG_LEVEL} --workdir=${BIN_PATH}/../loomengine/master --without-gossip
