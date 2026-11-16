"""The admin who created a quiz, as far as it is known."""

import uuid

from django.contrib.auth import get_user_model

from app.domain.models import Quiz


def creator_email(quiz: Quiz) -> str:
    """The creator's account e-mail; empty when unknown, deleted or not set."""
    try:
        admin_id = uuid.UUID(quiz.created_by)
    except ValueError:
        return ""
    email = get_user_model().objects.filter(pk=admin_id).values_list("email", flat=True).first()
    return email or ""
