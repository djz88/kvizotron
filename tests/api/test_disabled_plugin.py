"""AC-126, AC-127: every page still answers with a plugin disabled or a module missing."""

from datetime import timedelta

import pytest
from django.utils import timezone

from app.contracts import REWARD_SOURCE
from app.domain import authoring, banks, draws, rewards, run_schedule, run_stats, settings
from app.domain.models import QuizRevision, QuizRun
from app.kernel import lifecycle, registry
from app.kernel.models import PluginInstallation
from tests.api.test_admin_rewards import rule_data
from tests.api.test_import import GOOD, QUIZ_ROW, csv_of, job_url, upload, uploader  # noqa: F401
from tests.api.test_run_stats_page import submitted
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    add_question,
    definition,
    make_bank,
    make_quiz,
    published_quiz,
)
from tests.domain.test_prize_draws import draw_rule
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
CHOICE = "question.choice"
QUESTION_TYPES = [
    CHOICE,
    "question.image_answer",
    "question.matching",
    "question.number",
    "question.text",
]


def switch(module, value):
    lifecycle.set_enabled(module, value, actor_type="cli", actor_id=None)


def text(response):
    return response.content.decode()


def past_run(slug="kviz"):
    run = authoring.open_run(published_quiz(slug), admin_id=ADMIN_ID, data={"profile": "answers"})
    submitted(run, "1", "1")
    authoring.close_run(run, admin_id=ADMIN_ID)
    return run


def add_row_question(bank):
    config = definition(["cs"], OPTION_A, "V bance")
    return banks.save_question(
        bank, None, "choice", config, locales=["cs"], tags=[], admin_id=ADMIN_ID
    )


def draft_quiz():
    quiz = published_quiz()
    add_question(quiz, prompt="Rozepsaná")
    return quiz


def edit_url(quiz):
    return f"/admin/quizzes/{quiz.id}/edit?lang=en"


def test_disabled_type_is_not_offered_for_a_new_question(logged_in):
    """AC-126"""
    quiz = published_quiz()
    switch(CHOICE, False)
    assert "type=choice" not in text(logged_in.get(edit_url(quiz)))
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/questions/new?type=choice").status_code == 404


def test_disabled_type_is_not_offered_or_saved_in_a_bank(logged_in):
    """AC-126"""
    bank = make_bank()
    switch(CHOICE, False)
    assert "type=choice" not in text(logged_in.get(f"/admin/banks/{bank.id}?lang=en"))
    response = logged_in.post(
        f"/admin/banks/{bank.id}/questions/new?type=choice", {"prompt_cs": "Ne"}
    )
    assert response.status_code < 500
    assert not bank.questions.exists()


def test_import_row_of_a_disabled_type_is_refused_with_its_row_message(uploader):  # noqa: F811
    """AC-126"""
    switch(CHOICE, False)
    response = upload(uploader, csv_of(QUIZ_ROW, GOOD))
    assert response.status_code < 500
    check = uploader.get(job_url("check") + "?lang=en")
    assert check.status_code == 200
    assert "This question type is not known." in text(check)


def test_draft_with_a_disabled_type_opens_and_publication_refuses(logged_in):
    """AC-126"""
    quiz = draft_quiz()
    switch(CHOICE, False)
    page = logged_in.get(edit_url(quiz))
    assert page.status_code == 200
    assert "Rozepsaná" in text(page)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/publish?lang=en", {})
    assert response.status_code < 500
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_preview_of_a_draft_with_a_disabled_type_is_refused_not_an_error(logged_in):
    """AC-126"""
    quiz = draft_quiz()
    switch(CHOICE, False)
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en").status_code < 500
    submit = logged_in.post(f"/admin/quizzes/{quiz.id}/preview/submit?lang=en", {})
    assert submit.status_code < 500


def test_reenabled_type_leaves_the_draft_as_it_was(logged_in):
    """AC-126"""
    quiz = draft_quiz()
    switch(CHOICE, False)
    switch(CHOICE, True)
    assert "Rozepsaná" in text(logged_in.get(edit_url(quiz)))
    assert authoring.publish(quiz, admin_id=ADMIN_ID)


def test_question_of_a_disabled_type_can_be_seen_and_removed(logged_in):
    """AC-126"""
    quiz = draft_quiz()
    draft = authoring.get_draft(quiz)
    question_id = draft.snapshot_json["questions"][-1]["id"]
    switch(CHOICE, False)
    address = f"/admin/quizzes/{quiz.id}/questions/{question_id}"
    assert logged_in.get(f"{address}/edit?lang=en").status_code < 500
    assert logged_in.post(f"{address}/edit?lang=en", {"prompt_cs": "Jinak"}).status_code < 500
    assert logged_in.post(f"{address}/delete").status_code == 302
    draft.refresh_from_db()
    assert question_id not in [q["id"] for q in draft.snapshot_json["questions"]]


def test_bank_question_of_a_disabled_type_answers_without_an_error(logged_in):
    """AC-126"""
    bank = make_bank()
    question_id = add_row_question(bank)
    switch(CHOICE, False)
    address = f"/admin/banks/{bank.id}/questions/{question_id}/edit?lang=en"
    assert logged_in.get(f"/admin/banks/{bank.id}?lang=en").status_code == 200
    assert logged_in.get(address).status_code < 500
    assert logged_in.post(address, {"prompt_cs": "Jinak"}).status_code < 500


def test_the_maximum_of_a_stored_question_is_read_with_its_strategy_off():
    """AC-126: the strategy's own module is locked, so the port is switched off directly."""
    run = past_run()
    question = run.current_revision.snapshot_json["questions"][0]
    owner = registry.owned_by("scoring.basic")
    assert ("scoring_strategy", question["scoring"]) in owner
    PluginInstallation.objects.update_or_create(
        pk="scoring.basic", defaults={"enabled": False, "version": "1", "manifest_json": {}}
    )
    assert run_stats.question_max(question) > 0


def test_editor_opens_with_every_question_type_disabled(logged_in):
    """AC-126"""
    quiz = make_quiz()
    for module in QUESTION_TYPES:
        switch(module, False)
    assert logged_in.get(edit_url(quiz)).status_code == 200


@pytest.mark.parametrize(
    "address",
    [
        "/admin/runs/{run}?lang=en",
        "/admin/quizzes/{quiz}/runs?lang=en",
        "/admin/quizzes/{quiz}/grading?lang=en",
        "/admin/exports/new?quiz={quiz}&lang=en",
    ],
)
def test_page_of_a_past_run_answers_with_its_type_disabled(logged_in, address):
    """AC-126"""
    run = past_run()
    switch(CHOICE, False)
    assert logged_in.get(address.format(run=run.id, quiz=run.quiz_id)).status_code == 200


def public_past_run():
    run = past_run()
    settings.set_override(settings.ANSWERS_VISIBILITY, run.quiz, "public", admin_id=ADMIN_ID)
    return run


def test_public_pages_of_a_past_run_answer_with_its_type_disabled():
    """AC-126"""
    run = public_past_run()
    switch(CHOICE, False)
    client = FormClient()
    assert client.get(f"/q/{run.quiz.slug}").status_code < 500
    assert client.get(f"/q/{run.quiz.slug}/r/{run.id}/answers").status_code == 200


def test_walkthrough_of_an_uninstalled_type_leaves_the_question_out(monkeypatch):
    """AC-127, TD-017"""
    run = public_past_run()
    monkeypatch.delitem(registry._ports, ("question_type", "choice"))
    client = FormClient()
    assert client.get(f"/q/{run.quiz.slug}").status_code < 500
    assert client.get(f"/q/{run.quiz.slug}/r/{run.id}/answers").status_code == 200


def test_reward_kinds_needing_a_disabled_plugin_are_not_offered(logged_in):
    """AC-126"""
    quiz = published_quiz()
    switch("rewards.threshold", False)
    assert 'value="threshold"' not in text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards"))
    with pytest.raises(rewards.RuleInvalid, match="plugin_disabled"):
        rewards.save_rule(quiz, rule_data("threshold"), rule=None, admin_id=ADMIN_ID)
    with pytest.raises(rewards.RuleInvalid, match="plugin_disabled"):
        rewards.save_rule(
            quiz, draw_rule(min_unit="percent", min_value="50"), rule=None, admin_id=ADMIN_ID
        )


def test_a_draw_rule_is_not_offered_with_the_draw_plugin_off(logged_in):
    """AC-126"""
    quiz = published_quiz()
    switch("drawings.manual", False)
    assert 'value="draw"' not in text(logged_in.get(f"/admin/quizzes/{quiz.id}/rewards"))
    with pytest.raises(rewards.RuleInvalid, match="plugin_disabled"):
        rewards.save_rule(quiz, draw_rule(), rule=None, admin_id=ADMIN_ID)


def archived_draw_rule():
    quiz = published_quiz()
    rewards.save_rule(quiz, draw_rule(), rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    rule = rewards.rules_of(run)[0]
    authoring.close_run(run, admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(status=QuizRun.Status.ARCHIVED)
    return run, rule


def test_draw_is_refused_with_a_message_when_the_plugin_is_off(logged_in):
    """AC-126"""
    run, rule = archived_draw_rule()
    switch("drawings.manual", False)
    assert draws.refusal(rule) == "plugin_disabled"
    with pytest.raises(draws.DrawRefused, match="plugin_disabled"):
        draws.draw(rule, admin_id=ADMIN_ID)
    assert logged_in.get(f"/admin/runs/{run.id}/draw?lang=en").status_code == 200
    assert logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en").status_code == 200


def test_a_run_cannot_be_opened_on_a_revision_with_a_disabled_type(logged_in):
    """AC-126"""
    quiz = published_quiz()
    switch(CHOICE, False)
    with pytest.raises(authoring.RequirementUnmet):
        authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert not quiz.runs.exists()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/runs?lang=en", {})
    assert response.status_code < 500


def test_a_run_cannot_be_planned_on_a_revision_with_a_disabled_type():
    """AC-126"""
    quiz = published_quiz()
    switch(CHOICE, False)
    start = timezone.now() + timedelta(days=1)
    with pytest.raises(authoring.RequirementUnmet):
        run_schedule.plan(
            quiz, starts_at=start, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
        )
    assert not quiz.runs.exists()


def test_a_template_rule_of_a_disabled_plugin_is_not_copied_onto_a_new_run():
    """AC-126"""
    quiz = published_quiz()
    rewards.save_rule(quiz, rule_data("threshold"), rule=None, admin_id=ADMIN_ID)
    rewards.save_rule(quiz, rule_data("participation", name="Účast"), rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    switch("rewards.threshold", False)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert [rule.kind for rule in rewards.rules_of(run)] == ["participation"]


def test_the_texts_of_an_existing_rule_can_change_with_its_plugin_off():
    """AC-126"""
    quiz = published_quiz()
    rule = rewards.save_rule(quiz, rule_data("threshold"), rule=None, admin_id=ADMIN_ID)
    switch("rewards.threshold", False)
    saved = rewards.save_rule(
        quiz, rule_data("threshold", name="Nový"), rule=rule, admin_id=ADMIN_ID
    )
    assert saved.texts_json["cs"]["name"] == "Nový"
