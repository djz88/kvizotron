"""Test-only proof that auth is replaceable (ADR-0027). Never shipped."""

from django.contrib.auth import get_user_model

TOKEN = "test-only-token"


class TokenBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        if password != TOKEN:
            return None
        user = get_user_model().objects.filter(login=username).first()
        return user if user is not None and user.is_active else None

    def get_user(self, user_id):
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()
