# Builds a Loom container using the latest version from PyPI. 

FROM debian:jessie
MAINTAINER Isaac Liao <iliao@stanford.edu>
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get update && apt-get install -y build-essential libffi-dev libssl-dev python-dev python-pip && \
    pip install virtualenv && \
    virtualenv /opt/loom && \
    . /opt/loom/bin/activate && \
    pip install loomengine && \
    loom config gcloud_master && \
    apt-get -y remove build-essential libssl-dev libffi-dev && \
    apt-get -y autoremove && \
    apt-get -y clean

