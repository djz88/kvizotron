# Python is pinned per ADR-0022; the digest changes only deliberately.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=app.settings \
    KVZ_DB_PATH=/data/db/kvizotron.sqlite3 \
    TZ=Europe/Prague

RUN pip install --quiet --disable-pip-version-check --no-cache-dir --root-user-action=ignore uv==0.13.7

WORKDIR /srv/kvizotron
COPY pyproject.toml uv.lock ./
# Dependencies come separately so that a code change does not invalidate their layer.
RUN uv sync --frozen --no-dev --no-cache --no-install-project
COPY manage.py ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-cache

# Named volumes inherit the owner of these directories, so the application can run without root.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin kvizotron \
    && mkdir -p /data/db /data/media /data/backups \
    && chown -R kvizotron:kvizotron /data
USER kvizotron

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"]

# One process: SQLite and the in-process limits depend on it (ADR-0036).
CMD ["gunicorn", "app.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--no-control-socket"]

# One container (ADR-0066): migrations, the application and `jobs` side by side, for example as a pod in Kubernetes
# behind an ingress. Build: `docker build --target single`.
FROM app AS single
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD ["sh", "-c", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)\" && python -m app.domain.heartbeat check"]
CMD ["python", "manage.py", "serve"]

# The default build (without --target) is the image Compose runs.
FROM app
