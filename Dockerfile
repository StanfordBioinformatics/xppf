FROM ubuntu:18.04
MAINTAINER Nathan Hammond <info@loomengine.org>

# Install gcloud SDK.
RUN apt-get update && apt-get install -y \
    curl \
    lsb-release \
    gnupg \
    openssh-client \
    && CLOUD_SDK_REPO="cloud-sdk-$(lsb_release -c -s)" \
    && echo "deb http://packages.cloud.google.com/apt $CLOUD_SDK_REPO main" | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add - \
    && apt-get update && apt-get install -y \
    google-cloud-sdk \
    && apt-get autoremove \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Docker.
RUN apt-get update && apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg-agent \
    software-properties-common \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add - \
    && add-apt-repository \
     "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
     $(lsb_release -cs) stable"

RUN apt-get update && apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    && apt-get autoremove \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Loom's OS dependencies.
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libmariadbclient-dev \
    libssl-dev \
    python-dev \
    python-pip \
    && apt-get autoremove \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -U pip

# Install Loom
ADD ./portal /var/www/loom/portal
ADD ./client /loom/src/client
ADD ./server /loom/src/server
ADD ./utils /loom/src/utils
ADD ./worker /loom/src/worker
ADD ./bin /loom/src/bin
ADD ./NOTICES /loom/src/NOTICES
ADD ./LICENSE /loom/src/LICENSE
ADD ./README.rst /loom/src/README.rst
ADD ./build-tools /loom/src/build-tools
ARG LOOM_VERSION
RUN cd /loom/src/build-tools \
    && ./set-version.sh \
    && ./build-loom-packages.sh \
    && ./install-loom-packages.sh \
    && ./clean.sh
RUN loom-manage collectstatic --noinput
