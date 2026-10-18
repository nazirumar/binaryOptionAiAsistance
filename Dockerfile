# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Nazbeen Academy Binary Ai Asisstance — production image
#
# One image, many services (web / worker-*/beat / migrate). The command is
# chosen per service in compose.yaml. MT5 is NOT part of this image: the
# MetaTrader 5 package is Windows-only and runs on a separate host.
#
# Build:  docker build -t nazbeen-academy:latest .
# The image contains NO credentials: every secret is injected at runtime.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

# Never write .pyc files, never buffer output (so container logs are timely),
# and fail fast on any error in the entrypoint scripts.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Inline, minimal security banner:
#  - curl     -> container healthchecks
#  - libpq    -> psycopg
#  - libjpeg/zlib -> Pillow
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

# --- Dependencies ----------------------------------------------------------
WORKDIR /app
COPY requirements/base.txt requirements/prod.txt ./requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt

# --- Non-root user ---------------------------------------------------------
# Numeric UID/GID so Kubernetes/OpenShift-style arbitrary UIDs also work.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --shell /usr/sbin/nologin --create-home app

# --- Application -----------------------------------------------------------
COPY --chown=app:app . .

# Static/media directories the app writes to. `/app` itself must also belong to
# the runtime user: WORKDIR created it root-owned, while the app creates files
# in the working directory at runtime (SQLite under dev settings, log files) —
# without this, a bare `docker run` fails with "unable to open database file".
RUN mkdir -p /app/staticfiles /app/media /app/private_media/screenshots \
    && chown -R app:app /app/staticfiles /app/media /app/private_media \
    && chown app:app /app

# Static files are collected at build time ONLY when a secret key is supplied
# (WhiteNoise's manifest storage hashes filenames using SECRET_KEY). In the
# standard flow, `entrypoint.sh collectstatic` runs at container start with the
# runtime SECRET_KEY instead, so the build needs no secrets.
USER app:app

# Health endpoint served by Django itself (no shell-out needed at runtime).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

EXPOSE 8000

# Default: ASGI web server. `uvicorn` ships in requirements/prod.txt (the
# build installs prod.txt), so this command always exists in the image.
# compose.yaml overrides this for workers/migrate.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
