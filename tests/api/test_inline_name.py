"""A name is shown with a pencil and edited on the spot (AC-160)."""

import re
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest

from app.api.admin_forms import QuizNameForm
from app.api.public import ASSETS
from app.api.rendering import SCRIPTS
from app.domain import attempts, authoring, bank_folders, participants, rewards
from app.domain.models import Attempt, Participant, QuestionBank, Quiz, QuizRun
from app.kernel.models import AuditEvent
from tests.api.test_admin_rewards import rule_data, with_template
from tests.domain.helpers import ADMIN_ID, add_bank_question, make_bank, make_quiz, published_quiz

pytestmark = pytest.mark.django_db
HTMX = {"HTTP_HX_REQUEST": "true"}
EVIL = "<img src=x onerror=alert(1)>"


def text(response):
    return response.content.decode()


def grab(pattern, html):
    found = re.search(pattern, html, re.S)
    assert found, pattern
    return found


def bank_url(bank):
    return f"/admin/banks/{bank.id}"


def name_url(bank):
    return f"/admin/banks/{bank.id}/name"


# --- the name of a bank --------------------------------------------------------------------


def test_the_bank_name_is_shown_with_a_pencil_and_the_old_form_is_gone(logged_in):
    bank = make_bank("Dějepis")
    html = text(logged_in.get(bank_url(bank)))
    assert 'class="inline-name"' in html
    pencil = grab(r'<a [^>]*class="inline-name-pencil"[^>]*>', html).group(0)
    assert f'href="{bank_url(bank)}?edit=name"' in pencil
    assert "hx-get=" in pencil
    assert "Dějepis" in grab(r'aria-label="([^"]*)"', pencil).group(1)
    assert 'maxlength="120"' not in html
    assert "Delete the bank" in html or "Smazat banku" in html


def test_edit_partial_and_full_page(logged_in):
    bank = make_bank("Dějepis")
    partial = text(logged_in.get(name_url(bank) + "?edit=1", **HTMX))
    assert "<html" not in partial
    assert "<form" in partial
    assert 'value="Dějepis"' in partial
    full = text(logged_in.get(bank_url(bank) + "?edit=name"))
    assert "<html" in full
    assert 'name="name"' in full
    assert "autofocus" in full


def test_saving_through_htmx_returns_the_display_and_changes_the_name(logged_in):
    bank = make_bank("Dějepis")
    response = logged_in.post(name_url(bank), {"name": "Nová"}, **HTMX)
    assert response.status_code == 200
    html = text(response)
    assert "<html" not in html
    assert "Nová" in html
    assert 'role="status"' in html
    bank.refresh_from_db()
    assert bank.name == "Nová"
    event = AuditEvent.objects.get(action="bank.renamed")
    assert event.details_json == {}


def test_saving_without_htmx_redirects(logged_in):
    bank = make_bank("Dějepis")
    response = logged_in.post(name_url(bank), {"name": "Nová"})
    assert response.status_code == 302
    assert response["Location"] == bank_url(bank)
    bank.refresh_from_db()
    assert bank.name == "Nová"


@pytest.mark.parametrize("bad", ["", "   ", "x" * 121])
def test_a_refusal_shows_the_message_and_keeps_the_text(logged_in, bad):
    """AC-160: a refused name shows its message beside the field and keeps what was typed."""
    bank = make_bank("Dějepis")
    for extra in (HTMX, {}):
        response = logged_in.post(name_url(bank), {"name": bad}, **extra)
        html = text(response)
        assert response.status_code == 400
        assert 'role="alert"' in html
        if bad.strip():
            assert f'value="{bad}"' in html
        assert ("<html" in html) is (not extra)
    bank.refresh_from_db()
    assert bank.name == "Dějepis"
    assert not AuditEvent.objects.filter(action="bank.renamed").exists()


def test_a_name_with_html_is_escaped_everywhere(logged_in):
    bank = make_bank(EVIL)
    pages = [
        text(logged_in.get(bank_url(bank))),
        text(logged_in.get(bank_url(bank) + "?edit=name")),
        text(logged_in.get(name_url(bank) + "?edit=1", **HTMX)),
    ]
    for html in pages:
        assert EVIL not in html
        assert "&lt;img" in html
    display = pages[0]
    label = grab(r'class="inline-name-pencil"[^>]*aria-label="([^"]*)"', display).group(1)
    assert "&lt;img" in label


def test_the_script_is_loaded_and_used():
    assert "inline-edit.js" in SCRIPTS
    assert (ASSETS / "inline-edit.js").exists()


def test_an_unknown_bank_is_a_404(logged_in):
    assert (
        logged_in.get("/admin/banks/00000000-0000-7000-8000-0000000000ff/name").status_code == 404
    )
    assert QuestionBank.objects.count() == 0


# --- the name of a folder ------------------------------------------------------------------


def make_folders(bank_name="Dějepis"):
    bank = make_bank(bank_name)
    eu = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    trade = bank_folders.create(bank, eu, "Obchod", admin_id=ADMIN_ID)
    return bank, eu, trade


def folder_url(bank, folder):
    return f"/admin/banks/{bank.id}/folders/{folder.pk}/rename"


def test_a_folder_row_has_a_pencil_and_no_rename_field_in_the_menu(logged_in):
    bank, eu, _trade = make_folders()
    html = text(logged_in.get(bank_url(bank)))
    row = grab(rf'<span class="inline-name" id="name-name-{eu.pk}">.*?</span>', html).group(0)
    assert f'<a href="{bank_url(bank)}?folder={eu.pk}" class="inline-name-text">EU</a>' in row
    pencil = grab(r'<a [^>]*class="inline-name-pencil"[^>]*>', row).group(0)
    assert f"edit=folder:{eu.pk}" in pencil
    assert "EU" in grab(r'aria-label="([^"]*)"', pencil).group(1)
    assert 'value="EU"' not in html  # the old field of the menu


def test_the_folder_one_is_inside_can_be_renamed_from_its_heading(logged_in):
    bank, eu, _trade = make_folders()
    html = text(logged_in.get(f"{bank_url(bank)}?folder={eu.pk}"))
    heading = grab(rf'<div class="inline-name" id="name-name-{eu.pk}">.*?</div>', html).group(0)
    assert '<h2 class="inline-name-text">EU</h2>' in heading
    assert "inline-name-pencil" in heading
    opened = text(logged_in.get(f"{bank_url(bank)}?folder={eu.pk}&edit=folder:{eu.pk}"))
    assert f'<form method="post" action="{folder_url(bank, eu)}"' in opened
    assert 'value="EU"' in opened


def test_renaming_a_folder_through_htmx_and_without(logged_in):
    bank, eu, trade = make_folders()
    response = logged_in.post(
        folder_url(bank, trade),
        {"name": "Trh", "variant": "row", "next_folder": str(eu.pk)},
        **HTMX,
    )
    assert response.status_code == 200
    html = text(response)
    assert "<html" not in html
    assert ">Trh<" in html
    assert 'role="status"' in html
    trade.refresh_from_db()
    assert trade.name == "Trh"
    assert AuditEvent.objects.get(action="bank.folder_renamed").details_json == {}
    response = logged_in.post(
        folder_url(bank, trade), {"name": "Obchod", "next_folder": str(eu.pk)}
    )
    assert response.status_code == 302
    assert response["Location"] == f"{bank_url(bank)}?folder={eu.pk}"
    trade.refresh_from_db()
    assert trade.name == "Obchod"


def test_the_display_after_saving_keeps_the_kind_of_place_it_is_in(logged_in):
    bank, eu, _trade = make_folders()
    heading = text(
        logged_in.post(folder_url(bank, eu), {"name": "Evropa", "variant": "heading"}, **HTMX)
    )
    assert '<h2 class="inline-name-text">Evropa</h2>' in heading
    row = text(logged_in.get(folder_url(bank, eu) + "?variant=row", **HTMX))
    assert 'class="inline-name-text">Evropa</a>' in row


@pytest.mark.parametrize("bad", ["obchod", "a/b", "x" * 81, ""])
def test_a_clashing_or_bad_folder_name_is_refused_inline(logged_in, bad):
    bank, eu, trade = make_folders()
    other = bank_folders.create(bank, eu, "Trh", admin_id=ADMIN_ID)
    for extra in (HTMX, {}):
        data = {"name": bad, "variant": "row", "next_folder": str(eu.pk)}
        response = logged_in.post(folder_url(bank, other), data, **extra)
        html = text(response)
        assert response.status_code == 400
        assert 'role="alert"' in html
        assert ("<html" in html) is (not extra)
        if bad:
            assert f'value="{bad}"' in html
    other.refresh_from_db()
    assert other.name == "Trh"


def test_folder_names_are_escaped(logged_in):
    bank = make_bank()
    folder = bank_folders.create(bank, None, EVIL, admin_id=ADMIN_ID)
    pages = [
        text(logged_in.get(bank_url(bank))),
        text(logged_in.get(f"{bank_url(bank)}?folder={folder.pk}")),
        text(logged_in.get(f"{bank_url(bank)}?edit=folder:{folder.pk}")),
        text(logged_in.get(folder_url(bank, folder) + "?edit=1", **HTMX)),
    ]
    for html in pages:
        assert EVIL not in html
        assert "&lt;img" in html


def test_a_folder_of_another_bank_is_a_404(logged_in):
    bank, _eu, _trade = make_folders()
    other = make_bank("Jiná")
    foreign = bank_folders.create(other, None, "X", admin_id=ADMIN_ID)
    assert logged_in.post(folder_url(bank, foreign), {"name": "Y"}).status_code == 404


# --- the name of a quiz --------------------------------------------------------------------


def quiz_name_url(quiz):
    return f"/admin/quizzes/{quiz.id}/name"


def test_the_quiz_header_has_a_pencil_and_the_note(logged_in):
    quiz = published_quiz(slug="kviz", locales=("cs", "en"))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    box = grab(rf'<div class="inline-name" id="name-name-{quiz.id}">.*?</div>', html).group(0)
    assert '<h1 class="inline-name-text">Název cs</h1>' in box
    assert "inline-name-pencil" in box
    assert "Název cs" in grab(r'aria-label="([^"]*)"', box).group(1)
    assert "inline-name-note" in box  # visitors see the change after publication


def test_renaming_keeps_a_quiz_type_changed_meanwhile(logged_in):
    quiz = published_quiz(slug="kviz")
    real = QuizNameForm.is_valid

    def valid_after_a_type_change(self):
        Quiz.objects.filter(pk=quiz.pk).update(quiz_type="practice")
        return real(self)

    with mock.patch.object(QuizNameForm, "is_valid", valid_after_a_type_change):
        assert logged_in.post(quiz_name_url(quiz), {"name": "Nový"}, **HTMX).status_code == 200
    quiz.refresh_from_db()
    assert quiz.quiz_type == "practice" and quiz.title["cs"] == "Nový"


def test_the_header_of_every_tab_has_the_pencil(logged_in):
    quiz = published_quiz()
    for tab in ("edit", "runs", "grading", "settings", "rewards", "tests", "revisions"):
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/{tab}"))
        assert f'id="name-name-{quiz.id}"' in html, tab


def test_renaming_changes_the_default_language_title_only_and_makes_a_draft(logged_in):
    quiz = published_quiz(slug="kviz", locales=("cs", "en"))
    assert not authoring.has_draft(quiz)
    response = logged_in.post(quiz_name_url(quiz), {"name": "Nový název"}, **HTMX)
    assert response.status_code == 200
    html = text(response)
    assert "<html" not in html
    assert "Nový název" in html
    assert 'role="status"' in html
    assert "inline-name-note" in html
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Nový název", "en": "Název en"}
    assert authoring.has_draft(quiz)


def test_an_unchanged_name_makes_no_draft_and_the_redirect_goes_to_the_questions(logged_in):
    quiz = published_quiz(slug="kviz")
    response = logged_in.post(quiz_name_url(quiz), {"name": "Název cs"})
    assert response.status_code == 302
    assert response["Location"] == f"/admin/quizzes/{quiz.id}/edit"
    assert not authoring.has_draft(quiz)


def test_a_quiz_without_a_title_in_its_default_language_can_be_named(logged_in):
    quiz = make_quiz(slug="bez-nazvu")
    quiz.title = {}
    quiz.save()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert "bez-nazvu" in grab(r'<h1 class="inline-name-text">(.*?)</h1>', html).group(1)
    assert logged_in.post(quiz_name_url(quiz), {"name": "Pojmenovaný"}, **HTMX).status_code == 200
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Pojmenovaný"}


def test_an_archived_quiz_is_not_renamed(logged_in):
    quiz = published_quiz(slug="stary")
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    for extra in (HTMX, {}):
        response = logged_in.post(quiz_name_url(quiz), {"name": "Jiný"}, **extra)
        assert response.status_code == 409
        assert "archivovaný" in text(response)
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Název cs"}


@pytest.mark.parametrize("bad", ["", "   ", "x" * 201])
def test_a_bad_quiz_name_is_refused_inline(logged_in, bad):
    quiz = published_quiz(slug="kviz")
    for extra in (HTMX, {}):
        response = logged_in.post(quiz_name_url(quiz), {"name": bad}, **extra)
        html = text(response)
        assert response.status_code == 400
        assert 'role="alert"' in html
        assert ("<html" in html) is (not extra)
        if bad.strip():
            assert f'value="{bad}"' in html
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Název cs"}
    assert not authoring.has_draft(quiz)


def test_the_quiz_name_is_escaped(logged_in):
    quiz = published_quiz(slug="kviz")
    quiz.title = {"cs": EVIL}
    quiz.save()
    pages = [
        text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit")),
        text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit?edit=name")),
        text(logged_in.get(quiz_name_url(quiz) + "?edit=1", **HTMX)),
    ]
    for html in pages:
        assert EVIL not in html
        assert "&lt;img" in html


# --- the name of a reward ------------------------------------------------------------------


def reward_name_url(rule):
    return f"/admin/rewards/{rule.id}/name"


def a_rule(name="Odznak"):
    quiz = with_template(rule_data(name=name))
    (rule,) = rewards.template_of(quiz)
    return quiz, rule


def test_a_reward_has_a_pencil_beside_its_summary(logged_in):
    quiz, rule = a_rule()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards"))
    row = grab(r'<div class="reward-row"[^>]*>(.*?)</details>\s*(.*?)</div>', html)
    assert "<summary><strong" in row.group(1)  # the summary keeps the name as text
    pencil = grab(r'<a [^>]*class="inline-name-pencil"[^>]*>', row.group(2)).group(0)
    assert f"edit={rule.id}" in pencil
    assert "Odznak" in grab(r'aria-label="([^"]*)"', pencil).group(1)
    assert "<summary" not in row.group(2)


def test_renaming_a_reward_changes_only_the_default_language_name(logged_in):
    quiz = with_template(
        rewards.RuleData(
            kind="threshold",
            threshold_unit="percent",
            threshold_value=Decimal("80"),
            texts={
                "cs": {"name": "Odznak", "description": "Popis", "claim": "U pultu"},
                "en": {"name": "Badge", "description": "", "claim": ""},
            },
        )
    )
    (rule,) = rewards.template_of(quiz)
    response = logged_in.post(reward_name_url(rule), {"name": "Medaile"}, **HTMX)
    assert response.status_code == 200
    html = text(response)
    assert "<html" not in html
    assert 'role="status"' in html
    rule.refresh_from_db()
    assert rule.texts_json["cs"] == {"name": "Medaile", "description": "Popis", "claim": "U pultu"}
    assert rule.texts_json["en"]["name"] == "Badge"
    event = AuditEvent.objects.get(action="reward.texts_saved")
    assert event.details_json == {}


def test_a_reward_of_a_running_run_can_be_renamed_and_keeps_its_structure(logged_in):
    quiz = with_template(rule_data(name="Odznak"))
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    (rule,) = rewards.rules_of(run)
    before = (rule.kind, rule.threshold_unit, rule.threshold_value)
    assert logged_in.post(reward_name_url(rule), {"name": "Medaile"}, **HTMX).status_code == 200
    rule.refresh_from_db()
    assert rule.texts_json["cs"]["name"] == "Medaile"
    assert (rule.kind, rule.threshold_unit, rule.threshold_value) == before
    html = text(logged_in.get(f"/admin/runs/{run.id}/rewards"))
    assert "inline-name-pencil" in html


def test_a_reward_of_an_archived_quiz_template_is_not_renamed(logged_in):
    quiz, rule = a_rule()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    for extra in (HTMX, {}):
        response = logged_in.post(reward_name_url(rule), {"name": "Jiné"}, **extra)
        assert response.status_code == 409
    rule.refresh_from_db()
    assert rule.texts_json["cs"]["name"] == "Odznak"


@pytest.mark.parametrize("bad", ["", "  ", "x" * 81])
def test_a_bad_reward_name_is_refused_inline(logged_in, bad):
    quiz, rule = a_rule()
    for extra in (HTMX, {}):
        response = logged_in.post(reward_name_url(rule), {"name": bad}, **extra)
        html = text(response)
        assert response.status_code == 400
        assert 'role="alert"' in html
        assert ("<html" in html) is (not extra)
        if bad.strip():
            assert f'value="{bad}"' in html
    rule.refresh_from_db()
    assert rule.texts_json["cs"]["name"] == "Odznak"
    assert not AuditEvent.objects.filter(action="reward.texts_saved").exists()


def test_the_reward_field_opens_in_the_page_without_javascript(logged_in):
    quiz, rule = a_rule()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards?edit={rule.id}"))
    assert f'<form method="post" action="{reward_name_url(rule)}"' in html
    assert 'value="Odznak"' in html


def test_a_reward_name_is_escaped_and_a_test_run_reward_is_a_404(logged_in):
    quiz, rule = a_rule(EVIL)
    pages = [
        text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards")),
        text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards?edit={rule.id}")),
        text(logged_in.get(reward_name_url(rule) + "?edit=1", **HTMX)),
    ]
    for html in pages:
        assert EVIL not in html
        assert "&lt;img" in html
    assert (
        logged_in.post(
            "/admin/rewards/00000000-0000-7000-8000-0000000000ff/name", {"name": "x"}
        ).status_code
        == 404
    )


def test_a_mirror_of_the_name_is_swapped_with_the_display(logged_in):
    """The name in the summary changes with the pencil's display (it is swapped out of band)."""
    quiz, rule = a_rule()
    page = text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards"))
    assert f'id="reward-name-{rule.id}"' in page
    html = text(logged_in.post(reward_name_url(rule), {"name": "Medaile"}, **HTMX))
    assert f'hx-swap-oob="innerHTML:#reward-name-{rule.id}"' in html


def test_the_summary_title_and_the_trail_follow_a_save(logged_in):
    quiz = published_quiz(slug="kviz")
    page = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f'<strong id="quiz-title-{quiz.id}">' in page
    html = text(logged_in.post(quiz_name_url(quiz), {"name": "Nový"}, **HTMX))
    assert f'hx-swap-oob="innerHTML:#quiz-title-{quiz.id}"' in html
    bank, eu, _trade = make_folders()
    inside = text(logged_in.get(f"{bank_url(bank)}?folder={eu.pk}"))
    assert f'id="crumb-{eu.pk}"' in inside
    saved = text(
        logged_in.post(folder_url(bank, eu), {"name": "Evropa", "variant": "heading"}, **HTMX)
    )
    assert f'hx-swap-oob="innerHTML:#crumb-{eu.pk}"' in saved
    row = text(logged_in.post(folder_url(bank, eu), {"name": "EU", "variant": "row"}, **HTMX))
    assert "hx-swap-oob" not in row


# --- the nickname of a participant ---------------------------------------------------------


def nick_url(run, who):
    return f"/admin/runs/{run.id}/participants/{who.pk}/name"


def a_named_run(**rules):
    run = authoring.open_run(
        published_quiz(slug="soutez"),
        admin_id=ADMIN_ID,
        rules={"ask_name": "optional", "duplicate_names": "forbid"} | rules,
    )
    one = send_attempt(run, "Ema", "k1")
    two = send_attempt(run, "Jan", "k2")
    return run, one, two


def send_attempt(run, name, key):
    who = participants.find_or_create(run, key)
    started = attempts.start(run, participant=who)
    identity = participants.read_identity(participants.rules_of(run), name, "", automatic=False)
    attempts.submit(
        started.attempt.id, started.token, {}, "s" * 12 + key + str(who.pk)[:6], identity=identity
    )
    return Participant.objects.get(pk=who.pk)


def test_the_table_of_attempts_has_a_pencil_for_each_name(logged_in):
    run, one, two = a_named_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    for who, name in ((one, "Ema"), (two, "Jan")):
        cell = grab(rf'<span class="inline-name" id="name-name-{who.pk}">.*?</td>', html).group(0)
        assert f">{name}<" in cell
        assert f"edit={who.pk}" in cell
        assert name in grab(r'aria-label="([^"]*)"', cell).group(1)


def test_renaming_a_participant_through_htmx_and_without(logged_in):
    run, one, _two = a_named_run()
    response = logged_in.post(nick_url(run, one), {"name": "Žába"}, **HTMX)
    assert response.status_code == 200
    html = text(response)
    assert "<html" not in html
    assert ">Žába<" in html
    assert 'role="status"' in html
    assert Participant.objects.get(pk=one.pk).display_name == "Žába"
    response = logged_in.post(nick_url(run, one), {"name": "Ema"})
    assert response.status_code == 302
    assert response["Location"] == f"/admin/runs/{run.id}#attempts"
    assert Participant.objects.get(pk=one.pk).display_name == "Ema"


@pytest.mark.parametrize("bad", ["Jan", " jan ", "", "   ", "x" * 41])
def test_a_refused_nickname_is_shown_inline(logged_in, bad):
    run, one, _two = a_named_run()
    for extra in (HTMX, {}):
        response = logged_in.post(nick_url(run, one), {"name": bad}, **extra)
        html = text(response)
        assert response.status_code == 400
        assert 'role="alert"' in html
        assert ("<html" in html) is (not extra)
        if bad.strip():
            assert f'value="{bad}"' in html
    assert Participant.objects.get(pk=one.pk).display_name == "Ema"
    assert not AuditEvent.objects.filter(action="participant.renamed").exists()


def test_a_participant_of_another_run_is_a_404(logged_in):
    run, one, _two = a_named_run()
    other = authoring.open_run(published_quiz(slug="jina"), admin_id=ADMIN_ID, rules={})
    assert logged_in.post(nick_url(other, one), {"name": "X"}).status_code == 404
    assert logged_in.get(nick_url(other, one) + "?edit=1", **HTMX).status_code == 404


def test_a_test_run_has_no_nickname_to_rename(logged_in):
    run, one, _two = a_named_run()
    QuizRun.all_kinds.filter(pk=run.pk).update(kind=QuizRun.Kind.TEST)
    assert logged_in.post(nick_url(run, one), {"name": "X"}).status_code == 404


def test_a_stateless_run_has_no_pencils(logged_in):
    run = authoring.open_run(
        published_quiz(slug="bez-stopy"), admin_id=ADMIN_ID, data={"profile": "none"}
    )
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert "/participants/" not in html  # the pencil of the quiz title is not one of them


def test_the_nickname_field_opens_in_the_page_without_javascript(logged_in):
    run, one, _two = a_named_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}?edit={one.pk}"))
    assert f'<form method="post" action="{nick_url(run, one)}"' in html
    assert 'value="Ema"' in html
    assert 'maxlength="40"' in html


def test_a_nickname_with_html_is_escaped(logged_in):
    run = authoring.open_run(
        published_quiz(slug="html"), admin_id=ADMIN_ID, rules={"ask_name": "optional"}
    )
    who = send_attempt(run, "Ema", "k1")
    Participant.objects.filter(pk=who.pk).update(display_name=EVIL)
    pages = [
        text(logged_in.get(f"/admin/runs/{run.id}")),
        text(logged_in.get(f"/admin/runs/{run.id}?edit={who.pk}")),
        text(logged_in.get(nick_url(run, who) + "?edit=1", **HTMX)),
    ]
    for html in pages:
        assert EVIL not in html
        assert "&lt;img" in html


def test_a_participant_without_a_name_can_be_named(logged_in):
    run = authoring.open_run(
        published_quiz(slug="anon"), admin_id=ADMIN_ID, rules={"ask_name": "optional"}
    )
    who = send_attempt(run, "", "k1")
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert "inline-name-pencil" in html
    assert logged_in.post(nick_url(run, who), {"name": "Nový"}, **HTMX).status_code == 200


# --- the languages of a bank ---------------------------------------------------------------


def two_language_bank():
    bank = make_bank("Dějepis")
    add_bank_question(bank, locales=("cs", "uk"), prompt="Obě")
    add_bank_question(bank, locales=("cs",), prompt="Jen česky")
    return bank


def chips(html):
    return re.findall(r'<a class="chip"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S)


def test_the_bank_page_shows_language_chips_with_counts(logged_in):
    """AC-162: under its name the page says which languages the questions are complete in."""
    bank = two_language_bank()
    html = text(logged_in.get(bank_url(bank)))
    found = [(code.strip(), "".join(body.split())) for code, body in chips(html)]
    assert [body for _href, body in found] == ["cs2", "uk1"]
    assert grab(r'<a class="chip"[^>]*aria-current="true"[^>]*>', html)
    assert "en" not in [body[:2] for _href, body in found]


def test_a_bank_without_questions_has_no_chips(logged_in):
    assert chips(text(logged_in.get(bank_url(make_bank("Prázdná"))))) == []


def test_the_chosen_language_sets_the_question_texts(logged_in):
    bank = two_language_bank()
    default = text(logged_in.get(bank_url(bank)))
    assert ">Obě cs<" in default
    chosen = text(logged_in.get(bank_url(bank) + "?view_lang=uk"))
    assert ">Obě uk<" in chosen
    assert ">Obě cs<" not in chosen


def test_the_first_language_the_bank_has_is_the_default(logged_in):
    bank = make_bank("Anglická")
    add_bank_question(bank, locales=("en", "uk"), prompt="Otázka")
    html = text(logged_in.get(bank_url(bank)))
    assert ">Otázka en<" in html
    assert (
        grab(r'<a class="chip"[^>]*aria-current="true"[^>]*>(.*?)</a>', html).group(1).split()[0]
        == "en"
    )


def test_a_question_without_the_chosen_language_is_marked(logged_in):
    bank = two_language_bank()
    html = text(logged_in.get(bank_url(bank) + "?view_lang=uk"))
    row = grab(
        r"<li>\s*<input[^>]*>\s*<div class=\"row-main\">[^<]*<a[^>]*>Jen česky cs</a>.*?</li>", html
    ).group(0)
    assert "chip-draft" in row
    assert "cs" in grab(
        r'aria-label="([^"]*)"', grab(r'<span class="chip chip-draft"[^>]*>', row).group(0)
    ).group(1)
    assert "chip-draft" not in grab(r"<li>\s*<input[^>]*>.*?Obě uk.*?</li>", html).group(0)


def test_chips_keep_the_folder_and_the_search(logged_in):
    bank = make_bank("Dějepis")
    eu = bank_folders.create(bank, None, "EU", admin_id=ADMIN_ID)
    add_bank_question(bank, locales=("cs", "uk"), prompt="Rok", folder=eu)
    inside = chips(text(logged_in.get(f"{bank_url(bank)}?folder={eu.pk}")))
    assert all(f"folder={eu.pk}" in href for href, _body in inside)
    assert all("view_lang=" in href for href, _body in inside)
    found = chips(text(logged_in.get(f"{bank_url(bank)}?q=Rok")))
    assert all("q=Rok" in href for href, _body in found)


def test_an_unknown_language_is_ignored(logged_in):
    bank = two_language_bank()
    html = text(logged_in.get(bank_url(bank) + "?view_lang=zz"))
    assert ">Obě cs<" in html


def test_the_mirror_is_only_for_a_summary_that_shows_the_default_name(logged_in):
    quiz, rule = a_rule()
    english = text(logged_in.post(reward_name_url(rule) + "?lang=en", {"name": "Medaile"}, **HTMX))
    assert "hx-swap-oob" in english  # the summary falls back to the default name
    RewardRule = type(rule)
    RewardRule.objects.filter(pk=rule.pk).update(
        texts_json={"cs": {"name": "Odznak"}, "en": {"name": "Badge"}}
    )
    own = text(logged_in.post(reward_name_url(rule) + "?lang=en", {"name": "Medaile"}, **HTMX))
    assert "hx-swap-oob" not in own  # it shows the English name, which this does not change


# --- found by the review ---------------------------------------------------------------------


def a_second_attempt(run, who):
    first = Attempt.objects.filter(participant=who).first()
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=first.revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=first.submitted_at + timedelta(minutes=5),
        score=first.score,
        max_score=first.max_score,
    )


def test_a_participant_with_two_attempts_has_one_pencil_and_unique_ids(logged_in):
    run, one, _two = a_named_run()
    a_second_attempt(run, one)
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert html.count(f'id="name-name-{one.pk}"') == 1
    assert html.count(f"edit={one.pk}") == 1
    opened = text(logged_in.get(f"/admin/runs/{run.id}?edit={one.pk}"))
    assert opened.count(f'action="{nick_url(run, one)}"') == 1
    rows = re.findall(r"<tr data-attempt-row>.*?</tr>", html, re.S)
    assert sum(">Ema<" in row for row in rows) == 2  # the name is in both rows


def test_renaming_a_participant_with_two_attempts_refreshes_the_page(logged_in):
    run, one, _two = a_named_run()
    a_second_attempt(run, one)
    response = logged_in.post(nick_url(run, one), {"name": "Eva"}, **HTMX)
    assert response.status_code == 200
    assert response["HX-Refresh"] == "true"  # the other row shows the name too
    single = logged_in.post(nick_url(run, _two), {"name": "Karel"}, **HTMX)
    assert "HX-Refresh" not in single


def test_saving_the_slug_shown_for_an_untitled_quiz_changes_nothing(logged_in):
    quiz = make_quiz(slug="bez-nazvu")
    quiz.title = {}
    quiz.save()
    assert not authoring.has_draft(quiz)
    assert logged_in.post(quiz_name_url(quiz), {"name": "bez-nazvu"}, **HTMX).status_code == 200
    quiz.refresh_from_db()
    assert quiz.title == {}
    assert not authoring.has_draft(quiz)


# --- a fixed part after the value and an own pencil label ----------------------------------


def a_field(**changes):
    from app.api.inline_name import NameField

    values = {
        "label": "Address",
        "field": "address",
        "key": "k1",
        "value": "https://a",
        "save_url": "/s",
        "edit_url": "/e",
        "view_url": "/v",
        "edit_page": "/p?edit=address-k1",
        "back_page": "/p",
        "max_length": 200,
        "link": "https://a/t/x",
        "suffix": "/t/x",
        "pencil_label": "Edit the address",
    }
    return NameField(**(values | changes))


def drawn(rf, field):
    from app.api.inline_name import render_field

    request = rf.get("/")
    request.locale = "en"
    return render_field(request, field).content.decode()


def test_a_suffix_and_a_pencil_label_are_drawn(rf):
    html = drawn(rf, a_field())
    assert '<a href="https://a/t/x" class="inline-name-text">https://a/t/x</a>' in html
    pencil = grab(r'<a [^>]*class="inline-name-pencil"[^>]*>', html).group(0)
    assert 'title="Edit the address"' in pencil
    assert 'aria-label="Edit the address"' in pencil
    editing = drawn(rf, a_field(editing=True))
    assert re.search(
        r'name="address"[^>]*>\s*<span class="inline-name-suffix">/t/x</span>', editing
    )


def test_a_name_without_the_new_fields_keeps_its_pencil_label(rf):
    html = drawn(rf, a_field(suffix="", pencil_label="", link="", value="Dějepis"))
    pencil = grab(r'<a [^>]*class="inline-name-pencil"[^>]*>', html).group(0)
    assert 'title="Edit name"' in pencil
    assert "Edit name: Dějepis" in pencil
    assert "required" in drawn(rf, a_field(editing=True, suffix="", pencil_label="", link=""))
