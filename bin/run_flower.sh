#!/bin/bash

BIN_PATH="`dirname \"$0\"`"

DEFAULT_LOG_LEVEL=info
DEFAULT_FLOWER_INTERNAL_PORT=5555

LOOM_LOG_LEVEL=${LOOM_LOG_LEVEL:-$DEFAULT_LOG_LEVEL}
LOOM_FLOWER_INTERNAL_PORT=${LOOM_FLOWER_INTERNAL_PORT:-$DEFAULT_FLOWER_INTERNAL_PORT}

celery flower -A loomengine.master.master -l ${LOOM_LOG_LEVEL} --address=0.0.0.0 --port=${LOOM_FLOWER_INTERNAL_PORT} --workdir=${BIN_PATH}/../loomengine/master --url_prefix=flower
