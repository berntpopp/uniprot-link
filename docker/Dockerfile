# syntax=docker/dockerfile:1
# Multi-stage Dockerfile for uniprot-link.

FROM python:3.12-slim AS builder

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

RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev --active --no-install-project


FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
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
