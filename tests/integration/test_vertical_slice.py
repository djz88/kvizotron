"""The whole of A4: from an admin writing a quiz to participants in three languages."""

import re

import pytest

from app.domain.models import Attempt, Quiz, QuizRun
from app.kernel.models import AdminUser
from tests.support.client import FormClient

PASSWORD = "dlouhe-a-neobvykle-heslo"
LOCALES = ("cs", "en", "uk")
pytestmark = pytest.mark.django_db


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


def test_admin_to_participant_in_three_languages():
    AdminUser.objects.create_admin("alice", PASSWORD)
    admin = FormClient()
    assert admin.post("/admin/login", {"login": "alice", "password": PASSWORD}).status_code == 302
    admin.post(
        "/admin/quizzes/new",
        {
            "slug": "hlavni-mesta",
            "supported_locales": list(LOCALES),
            "default_locale": "cs",
            **{f"description_{code}": f"Popis {code}" for code in LOCALES},
            **{f"title_{code}": f"Hlavní města {code}" for code in LOCALES},
        },
    )
    quiz = Quiz.objects.get()
    question = {"correct_1": "on"}
    for code in LOCALES:
        question |= {
            f"prompt_{code}": f"Hlavní město {code}?",
            f"option_0_{code}": f"Brno {code}",
            f"option_1_{code}": f"Praha {code}",
        }
    url = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    assert admin.post(url, question).status_code == 302
    publish_url = f"/admin/quizzes/{quiz.id}/publish"
    publish_page = admin.get(publish_url).content.decode()
    published = admin.post(publish_url, {"snapshot_hash": hidden(publish_page, "snapshot_hash")})
    assert published.status_code == 302
    assert admin.post(f"/admin/quizzes/{quiz.id}/runs").status_code == 302
    assert admin.get(f"/admin/quizzes/{quiz.id}/qr.svg").status_code == 200
    run = QuizRun.objects.get()

    assert "/q/hlavni-mesta" in FormClient().get("/").content.decode()
    snapshot = run.current_revision.snapshot_json["questions"][0]
    correct = snapshot["definition"]["correct"]
    forms = []
    for code in LOCALES:
        participant = FormClient()
        page = participant.get(f"/q/hlavni-mesta?lang={code}").content.decode()
        assert f'<html lang="{code}"' in page and f"Hlavní města {code}" in page
        html = participant.post(f"/r/{run.id}/start", {"lang": code}).content.decode()
        assert f"Hlavní město {code}?" in html and f"Praha {code}" in html
        action = re.search(r'action="(/a/[^"?]+/submit)(?:\?[^"]*)?"', html).group(1)
        fields = {
            "attempt_token": hidden(html, "attempt_token"),
            "submission_key": hidden(html, "submission_key"),
            "lang": code,
            f"{snapshot['id']}:options[]": correct,
        }
        forms.append((participant, action, fields))
        response = participant.post(action, fields)
        assert response.status_code == 200 and "1 / 1" in response.content.decode()
    assert Attempt.objects.filter(status="SUBMITTED", score=1).count() == 3

    run_page = admin.get(f"/admin/runs/{run.id}").content.decode()
    assert "Odesláno pokusů: 3" in run_page
    assert admin.post(f"/admin/runs/{run.id}/close").status_code == 302
    assert FormClient().post(f"/r/{run.id}/start").status_code == 409
    participant, action, fields = forms[0]
    assert "1 / 1" in participant.post(action, fields).content.decode()
    assert Attempt.objects.filter(status="SUBMITTED").count() == 3
