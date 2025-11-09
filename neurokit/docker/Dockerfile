# Base: Matches Ubuntu 24.04 nodes, minimal footprint
FROM python:3.12-slim-bookworm

# Install git for remote pull; clean up after
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Clone latest from GitHub (main branch; override with BUILD_ARG for tags/branches)
ARG GIT_REPO=https://github.com/billyFelton/NeuroKit.git
ARG GIT_BRANCH=main
RUN git clone --depth 1 --branch ${GIT_BRANCH} ${GIT_REPO} /app && \
    cd /app && \
    pip install --no-cache-dir -e . && \
    # Install runtime deps explicitly (in case pyproject doesn't declare all)
    pip install --no-cache-dir pika==1.3.2 psutil==6.0.0 fastapi==0.115.0 uvicorn==0.30.0 && \
    # Purge git to slim image
    apt-get purge -y git && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /root/.cache

# Workdir: Repo root for editable install
WORKDIR /app
COPY entrypoint.py /app/entrypoint.py

# Entrypoint: From repo (pulled with clone)
ENTRYPOINT ["python", "entrypoint.py"]

# Default cmd: Allow overrides if needed
CMD []
