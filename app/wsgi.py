import os

from django.core.wsgi import get_wsgi_application

from app.kernel.bootstrap import setup

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
setup()
application = get_wsgi_application()

# Only after Django is set up: the models need the app registry.
from app.kernel.lifecycle import verify_startup  # noqa: E402

verify_startup()
