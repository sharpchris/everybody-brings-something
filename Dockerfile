# syntax=docker/dockerfile:1

# ---- Build stage: install dependencies into /app/.venv with uv ----
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer stays cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# ---- Runtime stage ----
FROM python:3.13-slim

LABEL org.opencontainers.image.title="Everybody Brings Something" \
      org.opencontainers.image.description="A self-hosted signup sheet for potlucks and outings. No accounts needed." \
      org.opencontainers.image.source="https://github.com/sharpchris/everybody-brings-something" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/data/db.sqlite3

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app \
 && mkdir -p /data \
 && chown app:app /data

WORKDIR /app
COPY --from=builder /app /app

# Collect static files at build time. The dummy key is only used for this step.
# ADMIN_KEY=off keeps a real key from being generated into the image.
RUN DEBUG=0 SECRET_KEY=build-only-dummy ADMIN_KEY=off DATABASE_PATH=/tmp/build.sqlite3 \
    python manage.py collectstatic --noinput

# No USER here: the entrypoint starts as root only to make /data writable (Railway and
# bind mounts often mount it root-owned), then drops to the unprivileged app user.
# No VOLUME either (Railway rejects it): mount a volume at /data yourself, as
# compose.yaml does, or the database lives only inside the container.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/health/\", timeout=3)"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
