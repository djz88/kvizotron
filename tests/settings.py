import os
import tempfile

os.environ.setdefault("KVZ_SECRET_KEY", "test-only-not-a-real-secret-key-0123456789")
os.environ.setdefault("KVZ_DOMAIN", "testserver")
os.environ.setdefault("KVZ_DB_PATH", ":memory:")
os.environ.setdefault("KVZ_MEDIA_PATH", tempfile.mkdtemp(prefix="kvz-media-"))

from app.settings import *  # noqa: E402, F403
