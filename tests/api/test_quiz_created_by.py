"""D1 addendum: a quiz created on the admin screen records its creator."""

import pytest

from app.domain.models import Quiz

pytestmark = pytest.mark.django_db


def test_new_quiz_in_admin_records_the_creator(logged_in, admin_user):
    response = logged_in.post(
        "/admin/quizzes/new",
        {
            "slug": "novy",
            "supported_locales": ["cs"],
            "default_locale": "cs",
            "title_cs": "Nový",
        },
    )
    assert response.status_code == 302, response.content.decode()
    assert Quiz.objects.get(slug="novy").created_by == str(admin_user.pk)
