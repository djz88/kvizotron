# Python je pinnutý podle ADR-0022, digest se mění jen vědomě.
FROM python:3.15-slim@sha256:e97b88e416c3c01eb427b21fd8cd3ebf006e6ee38afcfcc3cae1c54ee2ab0a75

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DJANGO_SETTINGS_MODULE=app.settings \
    KVZ_DB_PATH=/data/db/kvizotron.sqlite3

RUN pip install --quiet --disable-pip-version-check --root-user-action=ignore uv==0.13.7

WORKDIR /srv/kvizotron
COPY pyproject.toml uv.lock ./
# Závislosti zvlášť, aby změna kódu neinvalidovala jejich vrstvu.
RUN uv sync --frozen --no-dev --no-cache --no-install-project
COPY manage.py ./
COPY app ./app
RUN uv sync --frozen --no-dev --no-cache

# Pojmenované svazky přebírají vlastníka těchto adresářů, aplikace proto může běžet bez roota.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin kvizotron \
    && mkdir -p /data/db /data/media \
    && chown -R kvizotron:kvizotron /data
USER kvizotron

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"]

# Jeden proces: SQLite a limity v paměti procesu na tom závisí (ADR-0036).
CMD ["gunicorn", "app.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8"]
