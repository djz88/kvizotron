"""AC-120 to AC-125: the Modules page and the detail of a module."""

import re

import pytest
from django.conf import settings as django_settings
from django.urls import reverse

from app.domain import authoring, settings
from app.kernel import registry
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, open_quiz_run, published_quiz
from tests.domain.test_plugin_overview import set_question_value
from tests.domain.test_run_kinds import make_test_run
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
NUMBER = "question.number"
LOCKED = ["flow.basic", "participants.basic", "results.local", "scoring.basic"]


def text(response):
    return response.content.decode()


def state_url(module):
    return reverse("admin_plugin_state", args=[module])


def detail(client, module, lang="en"):
    return client.get(reverse("admin_plugin", args=[module]) + f"?lang={lang}")


def post_state(client, module, value):
    return client.post(state_url(module) + "?lang=en", {"enabled": value})


def test_list_shows_all_modules_and_a_provider_has_no_switch(logged_in):
    """AC-120"""
    body = text(logged_in.get(reverse("admin_plugins") + "?lang=en"))
    for manifest in django_settings.KVZ_MODULES:
        assert reverse("admin_plugin", args=[manifest.id]) in body
    assert "1.0.0" in body and "Photo" in body
    assert state_url("auth.local") not in body
    assert state_url(NUMBER) in body


def test_the_navigation_links_to_the_page(logged_in):
    """AC-120"""
    assert reverse("admin_plugins") in text(logged_in.get(reverse("admin_settings")))


def test_a_module_without_a_name_is_shown_by_its_id(logged_in, monkeypatch):
    """AC-120"""
    manifest = next(m for m in django_settings.KVZ_MODULES if m.id == NUMBER)
    nameless = manifest.model_copy(update={"name": None})
    others = [m for m in django_settings.KVZ_MODULES if m.id != NUMBER]
    monkeypatch.setattr(django_settings, "KVZ_MODULES", [*others, nameless])
    assert f">{NUMBER}<" in text(logged_in.get(reverse("admin_plugins")))


def test_pages_require_login(client):
    """AC-121"""
    for name, args in (("admin_plugins", []), ("admin_plugin", [NUMBER])):
        assert client.get(reverse(name, args=args)).status_code == 302
    assert client.post(state_url(NUMBER), {"enabled": "off"}).status_code == 302
    assert registry.is_enabled(NUMBER)


def test_disable_and_enable_apply_at_once_and_are_audited(logged_in, admin_user):
    """AC-121"""
    assert post_state(logged_in, NUMBER, "off").status_code == 302
    assert not registry.is_enabled(NUMBER)
    event = AuditEvent.objects.get(action="plugin.disabled", entity_id=NUMBER)
    assert event.actor_type == "admin"
    assert event.actor_id == str(admin_user.pk)
    assert post_state(logged_in, NUMBER, "on").status_code == 302
    assert registry.is_enabled(NUMBER)
    assert AuditEvent.objects.filter(action="plugin.enabled", entity_id=NUMBER).count() == 1


def test_state_needs_csrf(admin_user):
    """AC-121"""
    browser = FormClient(enforce_csrf_checks=True)
    browser.force_login(admin_user)
    assert browser.post(state_url(NUMBER), {"enabled": "off"}).status_code == 403
    assert registry.is_enabled(NUMBER)
    page = reverse("admin_plugins")
    form = text(browser.get(page, secure=True))
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form).group(1)
    answer = browser.post(
        state_url(NUMBER),
        {"csrfmiddlewaretoken": token, "enabled": "off"},
        secure=True,
        HTTP_REFERER=f"https://testserver{page}",
    )
    assert answer.status_code == 302
    assert not registry.is_enabled(NUMBER)


def test_second_disable_changes_nothing(logged_in):
    """AC-121"""
    assert post_state(logged_in, NUMBER, "off").status_code == 302
    assert post_state(logged_in, NUMBER, "off").status_code == 302
    assert AuditEvent.objects.filter(action="plugin.disabled", entity_id=NUMBER).count() == 1


@pytest.mark.parametrize("module", LOCKED)
def test_locked_plugin_has_no_switch_and_a_post_is_refused(logged_in, module):
    """AC-122"""
    assert state_url(module) not in text(logged_in.get(reverse("admin_plugins") + "?lang=en"))
    answer = post_state(logged_in, module, "off")
    assert answer.status_code == 409
    assert "cannot work without" in text(answer)
    assert registry.is_enabled(module)


def test_the_last_theme_shows_why_it_cannot_be_disabled(logged_in):
    """AC-122"""
    body = text(detail(logged_in, "theme.default"))
    assert "last enabled theme" in body
    assert state_url("theme.default") not in body


def test_post_for_a_provider_is_refused_not_an_error(logged_in):
    """AC-120"""
    assert post_state(logged_in, "auth.local", "off").status_code == 409
    assert registry.is_enabled("auth.local")


def test_unknown_module_is_404(logged_in):
    """AC-121"""
    assert detail(logged_in, "nope").status_code == 404
    assert post_state(logged_in, "nope", "off").status_code == 404


def test_invalid_state_value_is_400(logged_in):
    """AC-121"""
    assert post_state(logged_in, NUMBER, "maybe").status_code == 400
    assert registry.is_enabled(NUMBER)


def test_get_of_the_state_address_is_refused(logged_in):
    """AC-121"""
    assert logged_in.get(state_url(NUMBER)).status_code == 405


def test_in_use_detail_lists_the_run_with_a_link_in_the_admin_language(logged_in):
    """AC-123"""
    run = open_quiz_run()
    body = text(detail(logged_in, "question.choice", lang="cs"))
    assert "otevřený běh" in body
    assert reverse("admin_run", args=[run.pk]) in body
    assert state_url("question.choice") not in body


def test_refused_post_shows_the_reason_on_the_detail_page(logged_in):
    """AC-123"""
    open_quiz_run()
    answer = post_state(logged_in, "question.choice", "off")
    assert answer.status_code == 409
    assert "open run" in text(answer)
    assert registry.is_enabled("question.choice")


def test_a_test_link_is_named_as_such_and_has_no_broken_link(logged_in):
    """AC-123: the run page of a test link does not exist, so the reason leads to the quiz."""
    quiz = published_quiz()
    run = make_test_run(quiz)
    body = text(detail(logged_in, "question.choice"))
    assert "test link of quiz" in body
    assert reverse("admin_run", args=[run.pk]) not in body
    assert reverse("admin_quiz_edit", args=[quiz.id]) in body


def test_detail_lists_settings_with_global_value_and_links(logged_in):
    """AC-124"""
    body = text(detail(logged_in, "question.image_answer"))
    assert "Who sees a photo" in body
    assert "Admins and its author" in body
    assert reverse("admin_settings") in body


def test_different_elsewhere_links_to_quiz_settings_and_question(logged_in):
    """AC-125"""
    quiz = published_quiz()
    settings.set_override("photo_visibility", quiz, "admins", admin_id=ADMIN_ID)
    set_question_value(quiz, "public")
    question = authoring.get_draft(quiz).snapshot_json["questions"][0]["id"]
    body = text(detail(logged_in, "question.image_answer"))
    assert reverse("admin_quiz_settings", args=[quiz.id]) in body
    assert reverse("admin_question_edit", args=[quiz.id, question]) in body
    assert "question 1" in body


def test_global_only_setting_has_no_section_for_differences(logged_in):
    """AC-124"""
    body = text(detail(logged_in, "media.local"))
    assert "Images from an address" in body
    assert body.count("Different elsewhere") == 1  # of its two settings, one is global only


def test_module_without_settings_says_so(logged_in):
    """AC-124"""
    assert "This module adds no settings." in text(detail(logged_in, "question.choice"))


def test_detail_shows_what_it_requires_and_who_depends_on_it(logged_in):
    """AC-120"""
    assert "Media storage" in text(detail(logged_in, "question.image_answer"))
    assert "Photo" in text(detail(logged_in, "media.local"))


def test_long_list_shows_the_total(logged_in, monkeypatch):
    """AC-125"""
    monkeypatch.setattr("app.domain.plugin_overview.LIMIT", 1)
    for number in range(2):
        settings.set_override(
            "photo_visibility", published_quiz(f"k{number}"), "admins", admin_id=ADMIN_ID
        )
    assert "first 1 of 2" in text(detail(logged_in, "question.image_answer"))
