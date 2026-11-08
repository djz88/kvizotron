import re
from dataclasses import replace
from datetime import timedelta
from unittest import mock
from uuid import uuid7

import pytest
from django.test import override_settings

from app.domain import authoring, settings, tokens
from app.domain.models import Attempt, QuizRevision
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    OPTION_B,
    add_question,
    definition,
    make_quiz,
    open_quiz_run,
)
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


class Play:
    """A participant's form, as the browser would send it."""

    def __init__(self, client, run, lang="cs"):
        self.client = client
        self.run = run
        self.start_response = client.post(f"/r/{run.id}/start", {"lang": lang}, headers=HTMX)
        assert self.start_response.status_code == 200
        html = self.start_response.content.decode()
        self.action = re.search(r'action="(/a/[^"]+/submit)"', html).group(1)
        self.fields = {
            "attempt_token": hidden(html, "attempt_token"),
            "submission_key": hidden(html, "submission_key"),
            "lang": hidden(html, "lang"),
        }
        self.question_ids = [q["id"] for q in run.current_revision.snapshot_json["questions"]]

    def submit(self, option=OPTION_A, headers=HTMX, **extra):
        answers = {f"{qid}:options[]": option for qid in self.question_ids} if option else {}
        return self.client.post(self.action, self.fields | answers | extra, headers=headers)


@pytest.fixture
def run():
    return open_quiz_run(locales=("cs", "uk"))


def text(response):
    return response.content.decode()


def test_start_returns_questions_in_language_with_token_and_key(client, run):
    html = text(Play(client, run, "uk").start_response)
    assert "Otázka uk" in html and "Ano uk" in html
    assert "Otázka cs" not in html
    assert tokens.verify(hidden(html, "attempt_token")).run_id == run.id
    assert hidden(html, "submission_key")
    assert hidden(html, "lang") == "uk"
    assert re.search(r'name="[^"]+:options\[\]"', html)


def test_start_needs_no_csrf_token(run):
    response = FormClient(enforce_csrf_checks=True).post(f"/r/{run.id}/start", {"lang": "cs"})
    assert response.status_code == 200


def test_start_html_has_no_answer_key(client, run):
    def normalised(current):
        html = text(Play(client, current).start_response)
        html = re.sub(r'name="(attempt_token|submission_key)" value="[^"]*"', "", html)
        html = re.sub(r' data-(run|attempt|copy-expires)="[^"]*"', "", html)
        return re.sub(r"/a/[^/]+/(submit|revision-status)", "", html)

    first = normalised(run)
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    authoring.close_run(run, admin_id=ADMIN_ID)
    add_question(run.quiz, OPTION_B, question_id=question_id)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    second = authoring.open_run(run.quiz, admin_id=ADMIN_ID)
    assert first == normalised(second)
    assert "correct" not in first


def test_start_html_escapes_admin_markup(client):
    run = open_quiz_run()
    revision = run.current_revision
    snapshot = revision.snapshot_json
    snapshot["questions"][0]["definition"]["prompt"]["cs"] = "<script>x"
    QuizRevision.objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))
    assert "<script>x" not in html and "&lt;script&gt;x" in html


def test_start_on_closed_run_is_409_with_translated_message(client, run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    response = client.post(f"/r/{run.id}/start", {"lang": "uk"}, headers=HTMX)
    assert response.status_code == 409
    assert "Цей запуск завершився." in text(response)
    assert not Attempt.objects.exists()


def test_start_on_unknown_run_is_404(client):
    assert client.post(f"/r/{uuid7()}/start").status_code == 404


def test_htmx_start_returns_partial_and_plain_start_returns_whole_page(client, run):
    assert "<html" not in text(client.post(f"/r/{run.id}/start", headers=HTMX))
    assert "<html" in text(client.post(f"/r/{run.id}/start"))


def test_submit_shows_score_in_language(client, run):
    response = Play(client, run, "uk").submit()
    assert response.status_code == 200
    assert "1 / 1" in text(response) and "100" in text(response)
    assert "Ваш результат" in text(response)
    assert Attempt.objects.get().score == 1


def test_plain_submit_returns_whole_page(client, run):
    response = Play(client, run).submit(headers={})
    assert response.status_code == 200
    assert "<html" in text(response) and "1 / 1" in text(response)


def test_wrong_answer_shows_zero(client, run):
    assert "0 / 1" in text(Play(client, run).submit(OPTION_B))


def test_blank_answers_show_zero(client, run):
    assert "0 / 1" in text(Play(client, run).submit(None))


def test_submit_needs_no_csrf_token(run):
    play = Play(FormClient(enforce_csrf_checks=True), run)
    assert play.submit().status_code == 200


def test_tampered_score_started_at_revision_and_manifest_fields_do_not_change_result(client, run):
    response = Play(client, run).submit(
        OPTION_B,
        score="999",
        earned_points="999",
        started_at="2000-01-01T00:00:00Z",
        revision_id=str(uuid7()),
        manifest="tampered",
        manifest_hash="tampered",
    )
    assert response.status_code == 200
    assert "0 / 1" in text(response)
    attempt = Attempt.objects.get()
    assert attempt.score == 0
    assert attempt.revision_id == run.current_revision_id


def test_changed_token_is_403_and_attempt_stays_open(client, run):
    play = Play(client, run)
    good = play.fields["attempt_token"]
    response = play.submit(attempt_token=good[:-2] + "xx")
    assert response.status_code == 403
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS
    assert play.submit().status_code == 200


def test_signed_token_with_other_revision_is_403(client, run):
    play = Play(client, run)
    claims = tokens.verify(play.fields["attempt_token"])
    forged = tokens.issue(replace(claims, revision_id=uuid7()))
    assert play.submit(attempt_token=forged).status_code == 403


def test_double_submit_shows_same_score_once_stored(client, run):
    play = Play(client, run)
    first = play.submit()
    second = play.submit(OPTION_B)
    assert first.status_code == second.status_code == 200
    assert "1 / 1" in text(second)
    assert Attempt.objects.get().score == 1


def test_submit_with_other_key_is_409(client, run):
    play = Play(client, run)
    play.submit()
    response = play.submit(submission_key="another-key-1")
    assert response.status_code == 409
    assert "Tento pokus už byl odeslán." in text(response)


@pytest.mark.parametrize("key", ["", "short", "x" * 65, "bad key!"])
def test_invalid_key_is_400(client, run, key):
    assert Play(client, run).submit(submission_key=key).status_code == 400
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS


def test_missing_key_or_token_is_refused(client, run):
    play = Play(client, run)
    fields = {k: v for k, v in play.fields.items() if k != "submission_key"}
    assert client.post(play.action, fields).status_code == 400
    fields = {k: v for k, v in play.fields.items() if k != "attempt_token"}
    assert client.post(play.action, fields).status_code == 403


def test_malformed_answer_is_400_and_attempt_can_still_submit(client, run):
    play = Play(client, run)
    response = play.submit("no-such-option")
    assert response.status_code == 400
    assert "Odpověď se nepodařilo přečíst." in text(response)
    assert play.submit().status_code == 200


def test_field_names_without_colon_are_ignored(client, run):
    play = Play(client, run)
    assert "1 / 1" in text(play.submit(**{"nonsense": "x", ":options[]": "y", "x:": "z"}))


def test_oversized_body_is_400(client, run):
    play = Play(client, run)
    with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=10):
        response = play.submit()
    assert response.status_code == 400
    assert play.submit().status_code == 200


def test_too_many_fields_is_400(client, run):
    play = Play(client, run)
    with override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=2):
        assert play.submit().status_code == 400


def test_error_for_htmx_retargets_message_area(client, run):
    response = Play(client, run).submit("no-such-option")
    assert response["HX-Retarget"] == "#play-message"
    assert "<form" not in text(response)


def test_success_for_htmx_does_not_retarget(client, run):
    assert "HX-Retarget" not in Play(client, run).submit()


def test_plain_error_returns_whole_page(client, run):
    response = Play(client, run).submit("no-such-option", headers={})
    assert response.status_code == 400
    assert "<html" in text(response)
    assert "Odpověď se nepodařilo přečíst." in text(response)


def test_submit_after_close_is_409_with_translated_message(client, run):
    play = Play(client, run, "uk")
    authoring.close_run(run, admin_id=ADMIN_ID)
    response = play.submit()
    assert response.status_code == 409
    assert "Цей запуск завершився." in text(response)


def test_expired_attempt_is_410_with_translated_message(client, run):
    play = Play(client, run)
    expires = tokens.verify(play.fields["attempt_token"]).expires_at
    late = expires + timedelta(seconds=1)
    with mock.patch("app.domain.attempts.timezone.now", return_value=late):
        response = play.submit()
    assert response.status_code == 410
    assert "Čas na tento pokus vypršel." in text(response)


def test_unknown_attempt_is_404(client):
    assert client.post(f"/a/{uuid7()}/submit", {"attempt_token": "x"}).status_code == 404


def test_uninstalled_type_is_503_at_start(client, run):
    revision = run.current_revision
    snapshot = revision.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    response = client.post(f"/r/{run.id}/start")
    assert response.status_code == 503
    assert not Attempt.objects.exists()


@pytest.mark.parametrize("path", ["/r/{}/start", "/a/{}/submit"])
def test_get_is_405(client, path):
    assert client.get(path.format(uuid7())).status_code == 405


def test_two_ticks_reach_the_plugin_as_a_list(client):
    quiz = make_quiz(slug="dvakrat")
    config = definition(quiz.supported_locales)
    config["correct"] = [OPTION_A, OPTION_B]
    config["allow_multiple"] = True
    question = authoring.save_question(quiz, None, "choice", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    play = Play(client, authoring.open_run(quiz, admin_id=ADMIN_ID))
    fields = play.fields | {f"{question}:options[]": [OPTION_A, OPTION_B]}
    assert "1 / 1" in text(client.post(play.action, fields, headers=HTMX))


def order_quiz(client):
    quiz = make_quiz(slug="poradi")
    config = {
        "prompt": {"cs": "Seřaďte"},
        "mode": "order",
        "direction": "top_down",
        "items": [
            {"id": "aaaa1111", "text": {"cs": "První"}},
            {"id": "bbbb2222", "text": {"cs": "Druhá"}},
        ],
    }
    question = authoring.save_question(quiz, None, "matching", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return Play(client, authoring.open_run(quiz, admin_id=ADMIN_ID)), question


def test_order_list_reaches_the_plugin_and_scores(client):
    play, question = order_quiz(client)
    fields = play.fields | {f"{question}:order[]": ["aaaa1111", "bbbb2222"]}
    assert "1 / 1" in text(client.post(play.action, fields, headers=HTMX))


def test_repeated_position_without_a_script_keeps_the_answers(client):
    play, question = order_quiz(client)
    positions = {f"{question}:pos_aaaa1111": "2", f"{question}:pos_bbbb2222": "2"}
    response = client.post(play.action, play.fields | positions)
    assert response.status_code == 400
    html = text(response)
    assert html.count('value="2" selected') == 2
    assert hidden(html, "attempt_token") == play.fields["attempt_token"]
    assert hidden(html, "submission_key") == play.fields["submission_key"]
    assert 'id="play-message"' in html
    fixed = {f"{question}:pos_aaaa1111": "1", f"{question}:pos_bbbb2222": "2"}
    assert "1 / 1" in text(client.post(play.action, play.fields | fixed))


def test_two_answers_on_a_one_answer_question_are_refused(client, run):
    play = Play(client, run)
    question = play.question_ids[0]
    fields = play.fields | {f"{question}:options[]": [OPTION_A, OPTION_B]}
    assert client.post(play.action, fields, headers=HTMX).status_code == 400


def pairs_quiz(client):
    quiz = make_quiz(slug="dvojice")
    config = {
        "prompt": {"cs": "Spojte"},
        "mode": "pairs",
        "items": [
            {"id": "aaaa1111", "match_id": "cccc3333", "text": {"cs": "A"}, "match": {"cs": "1"}},
            {"id": "bbbb2222", "match_id": "dddd4444", "text": {"cs": "B"}, "match": {"cs": "2"}},
        ],
    }
    question = authoring.save_question(quiz, None, "matching", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return Play(client, authoring.open_run(quiz, admin_id=ADMIN_ID)), question


def test_one_year_for_two_events_without_a_script_keeps_the_answers(client):
    play, question = pairs_quiz(client)
    same = {f"{question}:pair_aaaa1111": "cccc3333", f"{question}:pair_bbbb2222": "cccc3333"}
    response = client.post(play.action, play.fields | same)
    assert response.status_code == 400
    assert text(response).count('value="cccc3333" selected') == 2
    fixed = same | {f"{question}:pair_bbbb2222": "dddd4444"}
    assert "1 / 1" in text(client.post(play.action, play.fields | fixed))


def _options_in(html):
    return re.findall(r'value="(opt\d)"', html)


def test_rerender_after_a_refused_form_keeps_the_option_order(client):
    quiz = make_quiz()
    config = definition(["cs"])
    config["options"] = [{"id": f"opt{n}", "text": {"cs": f"T{n}"}} for n in range(6)]
    config["correct"] = ["opt0"]
    question = authoring.save_question(quiz, None, "choice", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    settings.set_override(settings.SHUFFLE_OPTIONS, quiz, "on", admin_id=None)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    play = Play(client, run)
    first = _options_in(play.start_response.content.decode())
    assert sorted(first) == [f"opt{n}" for n in range(6)]
    refused = client.post(play.action, play.fields | {f"{question}:options[]": "forged"})
    assert refused.status_code == 400
    assert _options_in(refused.content.decode()) == first
