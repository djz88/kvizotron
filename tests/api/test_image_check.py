"""Opening a quiz checks the images it loads from elsewhere, at most once an hour (AC-42)."""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.utils import timezone

from app.contracts import EXTERNAL_IMAGE_MODE
from app.domain import authoring, settings
from app.providers.media_local import remote
from app.providers.media_local.models import AddressCheck
from tests.api.test_external_images import png
from tests.domain.helpers import ADMIN_ID, definition, make_quiz

pytestmark = pytest.mark.django_db
URL = "https://a.example/1.png"


def quiz_with_image(mode="external"):
    quiz = make_quiz()
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, mode, admin_id=ADMIN_ID)
    image = {"asset": "abc", "source": URL, "alt": {"cs": "P"}}
    authoring.save_question(quiz, None, "choice", definition(("cs",)) | {"image": image})
    return quiz


def check_url(quiz):
    return f"/admin/quizzes/{quiz.id}/image-check"


def edit_url(quiz):
    return f"/admin/quizzes/{quiz.id}/edit?lang=en"


@pytest.fixture
def down(monkeypatch):
    fake = mock.Mock(side_effect=remote.RemoteRefused("down"))
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


@pytest.fixture
def up(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


def test_an_unreachable_image_shows_a_warning(logged_in, down):
    html = logged_in.post(check_url(quiz_with_image()) + "?lang=en").content.decode()
    assert "could not be reached: 1" in html
    assert "Last checked" in html


def test_no_failure_means_no_warning(logged_in, up):
    html = logged_in.post(check_url(quiz_with_image()) + "?lang=en").content.decode()
    assert "could not be reached" not in html


def test_a_second_opening_within_the_hour_runs_no_check(logged_in, down):
    quiz = quiz_with_image()
    logged_in.post(check_url(quiz))
    logged_in.post(check_url(quiz))
    assert down.call_count == 1


def test_a_copy_mode_quiz_has_no_check_on_its_page(logged_in, up):
    quiz = quiz_with_image("copy")
    assert check_url(quiz) not in logged_in.get(edit_url(quiz)).content.decode()
    logged_in.post(check_url(quiz))
    up.assert_not_called()


def test_the_page_loads_without_running_a_check(logged_in, up):
    quiz = quiz_with_image()
    html = logged_in.get(edit_url(quiz)).content.decode()
    up.assert_not_called()
    assert f'hx-post="{check_url(quiz)}"' in html
    assert 'hx-trigger="load"' in html
    assert "csrfmiddlewaretoken" in html


def test_a_stored_failure_shows_on_the_page_without_a_new_check(logged_in, up):
    quiz = quiz_with_image()
    AddressCheck.objects.create(address=URL, ok=False, checked_at=timezone.now())
    html = logged_in.get(edit_url(quiz)).content.decode()
    assert "could not be reached: 1" in html
    up.assert_not_called()


def test_an_old_failure_of_another_quiz_does_not_show(logged_in):
    old = timezone.now() - timedelta(days=1)
    AddressCheck.objects.create(address="https://other.example/x.png", ok=False, checked_at=old)
    html = logged_in.get(edit_url(quiz_with_image())).content.decode()
    assert "could not be reached" not in html


def test_the_check_needs_an_admin(client, logged_in):
    quiz = quiz_with_image()
    assert logged_in.get(check_url(quiz)).status_code == 405
    logged_in.logout()
    assert client.post(check_url(quiz)).status_code == 302
    assert not AddressCheck.objects.exists()


def test_the_publish_page_lists_failures_and_still_publishes(logged_in):
    quiz = quiz_with_image()
    AddressCheck.objects.create(address=URL, ok=False, checked_at=timezone.now())
    url = f"/admin/quizzes/{quiz.id}/publish?lang=en"
    html = logged_in.get(url).content.decode()
    assert URL in html
    assert "cannot be published" not in html
    assert authoring.validate_for_publication(quiz) == []


def test_the_check_time_is_written_like_other_admin_times(logged_in):
    quiz = quiz_with_image()
    moment = datetime(2026, 11, 7, 9, 6, tzinfo=UTC)
    AddressCheck.objects.create(address=URL, ok=False, checked_at=moment)
    assert "2026-11-07 10:06 CET" in logged_in.get(edit_url(quiz)).content.decode()
