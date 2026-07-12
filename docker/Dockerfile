# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for uniprot-link.

FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /home/app/web
COPY uv.lock pyproject.toml README.md ./

# Reproducible build: pin uv to a digest-addressed image (fleet-shared anchor)
# instead of a floating pip-bootstrapped installer upgrade (F-19).
COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab /uv /usr/local/bin/uv

RUN uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS production

# Runtime identity. The deploy builds from a source checkout rather than pulling a
# registry image, so there is no immutable OCI digest to pin; stamping the exact commit
# into the image is what lets an operator prove the running container was built from the
# revision the router's release inventory pins, instead of trusting a moving `main`.
# VCS_REF is deliberately unprefixed: a <SERVICE>_-prefixed name would be picked up by the
# pydantic settings class and rejected as an unknown field.
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/berntpopp/uniprot-link" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    VCS_REF="${VCS_REF}" \
    UNIPROT_LINK_HOST=0.0.0.0 \
    UNIPROT_LINK_PORT=8000 \
    UNIPROT_LINK_TRANSPORT=unified

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /home/app/web

COPY --chown=app:app ./uniprot_link ./uniprot_link
COPY --chown=app:app ./pyproject.toml ./README.md ./

# Install the project itself (no deps -- already provided by the builder venv)
# so the `uniprot-link` console script is on PATH.
RUN pip install --no-deps .

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Unified transport: FastAPI on / and MCP on /mcp via a single port.
CMD ["uniprot-link", "serve", "--transport", "unified", "--host", "0.0.0.0", "--port", "8000"]
