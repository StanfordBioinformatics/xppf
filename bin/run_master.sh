#!/bin/bash

DEFAULT_LOG_LEVEL=info
DEFAULT_IP=0.0.0.0
DEFAULT_PORT=8000
DEFAULT_GUNICORN_WORKERS_COUNT=10

LOOM_LOG_LEVEL=${LOOM_LOG_LEVEL:-$DEFAULT_LOG_LEVEL}
LOOM_MASTER_INTERNAL_IP=${LOOM_MASTER_INTERNAL_IP:-$DEFAULT_IP}
LOOM_MASTER_INTERNAL_PORT=${LOOM_MASTER_INTERNAL_PORT:-$DEFAULT_PORT}
LOOM_MASTER_GUNICORN_WORKERS_COUNT=${LOOM_MASTER_GUNICORN_WORKERS_COUNT:-$DEFAULT_GUNICORN_WORKERS_COUNT}


BIN_PATH="`dirname \"$0\"`"

# Wait for database to become available
RETRIES=30
n=0
while :
do
    # break if db connection is successful
    $BIN_PATH/../loomengine/master/manage.py inspectdb > /dev/null 2>%1 && break

    # exit if retries exceeded
    if [ $n -ge $RETRIES ]
    then
	>&2 echo "Timeout while waiting for database"
	exit 1;
    fi

    sleep 1
    n=$[$n+1]
done

$BIN_PATH/../loomengine/master/manage.py migrate
$BIN_PATH/../loomengine/master/manage.py collectstatic --noinput

gunicorn loomengine.master.master.wsgi --bind ${LOOM_MASTER_INTERNAL_IP}:${LOOM_MASTER_INTERNAL_PORT} --log-level ${LOOM_LOG_LEVEL} --capture-output -w ${LOOM_MASTER_GUNICORN_WORKERS_COUNT}
