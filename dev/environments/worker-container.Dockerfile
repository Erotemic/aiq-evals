# Bind-mounted editable engines need git inside the container to prove HEAD
# and tracked cleanliness. An editable PEP 610 URL proves neither.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
