"""A test client that sends forms as a browser does. Multipart is refused by the application."""

from urllib.parse import urlencode

from django.test import Client

FORM = "application/x-www-form-urlencoded"


class FormClient(Client):
    def post(self, path, data=None, content_type=FORM, **extra):
        if content_type == FORM and not isinstance(data, str | bytes):
            data = urlencode(data or {}, doseq=True)
        return super().post(path, data, content_type=content_type, **extra)
