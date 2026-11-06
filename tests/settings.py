import os

os.environ.setdefault("KVZ_SECRET_KEY", "test-only-not-a-secret")
os.environ.setdefault("KVZ_DOMAIN", "testserver")
os.environ.setdefault("KVZ_DB_PATH", ":memory:")

from app.settings import *  # noqa: E402, F403
