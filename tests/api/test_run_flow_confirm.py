"""AC-185: the quiz settings page asks whether a planned or open run takes the change."""

import re
from decimal import Decimal

import pytest

from app.contracts import REWARD_SOURCE
from app.domain import authoring, rewards, run_flow, settings
from tests.domain.helpers import ADMIN_ID, add_question, keep, published_quiz
from tests.support.requirements import needs_reveal_at_end

pytestmark = pytest.mark.django_db
NAV = settings.NAVIGATION_MODE


def text(response):
    return response.content.decode()


def open_run(quiz=None):
    quiz = quiz or published_quiz()
    return quiz, authoring.open_run(quiz, admin_id=ADMIN_ID)


def url(quiz):
    return f"/admin/quizzes/{quiz.id}/settings?lang=en"


def post(client, quiz, **fields):
    data = {"slug": quiz.slug, NAV: "all_at_once"} | fields
    return client.post(url(quiz), data)


def with_rewards(quiz):
    texts = {"cs": {"name": "Cena", "description": "", "claim": ""}}
    rule = rewards.RuleData(
        kind="threshold", texts=texts, threshold_unit="percent", threshold_value=Decimal(50)
    )
    rewards.save_rule(quiz, rule, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)


def test_a_change_the_run_would_take_asks_first(logged_in):
    """AC-185: the question comes before anything is saved."""
    quiz, run = open_run()
    response = post(logged_in, quiz)
    html = text(response)
    assert response.status_code == 200
    assert f"Apply the change to run {run.run_no} too?" in html
    assert "<strong>Moving through the questions</strong>: One by one, with going back" in html
    assert 'name="flow_choice" value="run"' in html
    assert settings.quiz_override(NAV, quiz) is None


def test_answering_run_applies_it(logged_in):
    """AC-185: "run" saves the quiz change and the run keeps the new value."""
    quiz, run = open_run()
    response = post(logged_in, quiz, flow_choice="run")
    assert response.status_code == 302
    assert settings.quiz_override(NAV, quiz) == "all_at_once"
    run.refresh_from_db()
    assert run_flow.of(run)[NAV] == "all_at_once"


def test_answering_next_keeps_the_run(logged_in):
    """AC-185: "next" saves the quiz change only."""
    quiz, run = open_run()
    response = post(logged_in, quiz, flow_choice="next")
    assert response.status_code == 302
    assert settings.quiz_override(NAV, quiz) == "all_at_once"
    run.refresh_from_db()
    assert run_flow.of(run)[NAV] == "step_back"


def test_the_confirm_page_repeats_the_posted_fields(logged_in):
    """AC-185: every posted field comes back hidden and Cancel returns to the settings."""
    quiz, _run = open_run()
    html = text(post(logged_in, quiz, reveal_moment="never"))
    for name, value in (("slug", quiz.slug), (NAV, "all_at_once"), ("reveal_moment", "never")):
        assert re.search(rf'<input type="hidden" name="{name}" value="{value}"', html)
    form = html[html.index('name="slug"') :].split("</form>")[0]
    assert form.count("csrfmiddlewaretoken") == 0  # the form's own token comes before the fields
    assert html.count(f'action="/admin/quizzes/{quiz.id}/settings"') == 1
    assert f'href="/admin/quizzes/{quiz.id}/settings"' in html


def test_a_run_with_rewards_is_offered_only_next(logged_in):
    """AC-185: a run with rewards cannot take answers after each question; the reason is shown."""
    quiz = published_quiz()
    with_rewards(quiz)
    _quiz, run = open_run(quiz)
    response = post(logged_in, quiz, reveal_moment="after_each", navigation_mode="step_back")
    html = text(response)
    assert response.status_code == 200
    assert f"Run {run.run_no} cannot take this change:" in html
    assert "Answers after each question cannot go with rewards." in html
    assert 'value="run"' not in html
    assert re.search(r'value="next"[^>]*checked|checked[^>]*value="next"', html)
    done = post(
        logged_in, quiz, reveal_moment="after_each", navigation_mode="step_back", flow_choice="next"
    )
    assert done.status_code == 302
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) == "after_each"


def test_a_forged_run_answer_on_a_refused_run_is_409(logged_in):
    """AC-185: "run" for a run that cannot take the change saves nothing."""
    quiz = published_quiz()
    with_rewards(quiz)
    open_run(quiz)
    response = post(
        logged_in, quiz, reveal_moment="after_each", navigation_mode="step_back", flow_choice="run"
    )
    assert response.status_code == 409
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) is None


def test_an_unknown_answer_asks_again(logged_in):
    """AC-185: an answer that is neither run nor next counts as no answer."""
    quiz, _run = open_run()
    response = post(logged_in, quiz, flow_choice="maybe")
    assert response.status_code == 200
    assert "too?" in text(response)
    assert settings.quiz_override(NAV, quiz) is None


def test_an_unrelated_save_asks_nothing(logged_in):
    """AC-185: the run differs from the quiz after an earlier "next", but only a change asks."""
    quiz, run = open_run()
    keep(run, NAV, "pages")
    response = logged_in.post(url(quiz), {"slug": quiz.slug, NAV: "step_back"})
    assert response.status_code == 302
    run.refresh_from_db()
    assert run_flow.of(run)[NAV] == "pages"


def test_a_run_closed_meanwhile_saves_without_asking(logged_in):
    """AC-185: the page was shown while the run was open; closed runs are not offered."""
    quiz, run = open_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    response = post(logged_in, quiz, flow_choice="run")
    assert response.status_code == 302
    assert settings.quiz_override(NAV, quiz) == "all_at_once"
    run.refresh_from_db()
    assert run_flow.of(run)[NAV] == "step_back"


def test_a_global_change_does_not_reach_a_live_run(logged_in):
    """AC-185: a global change is not offered and never changes a planned or open run."""
    quiz = published_quiz()
    with_rewards(quiz)
    _quiz, run = open_run(quiz)
    before = run_flow.of(run)
    response = logged_in.post("/admin/settings", {settings.REVEAL_MOMENT: "after_each"})
    assert response.status_code == 302
    assert settings.resolve(settings.REVEAL_MOMENT) == "after_each"
    run.refresh_from_db()
    assert run_flow.of(run) == before


def test_the_confirm_page_is_built_from_the_saved_quiz(logged_in, monkeypatch):
    """AC-185: nothing is saved, so the page gets the stored quiz, not the posted values."""
    from app.api import admin_quizzes

    seen = []
    real = admin_quizzes.workspace

    def spy(quiz, *args, **kwargs):
        seen.append(quiz.featured)
        return real(quiz, *args, **kwargs)

    monkeypatch.setattr(admin_quizzes, "workspace", spy)
    quiz, _run = open_run()
    html = text(post(logged_in, quiz, featured="on"))
    assert "too?" in html
    assert seen == [False]


REVEAL = settings.REVEAL_MOMENT


def use_url(quiz):
    return f"/admin/quizzes/{quiz.id}/requirements/use?lang=en"


def keeping_after_each():
    quiz = published_quiz()
    settings.set_override(REVEAL, quiz, "after_each", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    return quiz, run


def test_use_asks_a_live_run_that_keeps_the_refused_value(logged_in):
    """AC-185: the editor's Use button is a quiz change, so the run is asked first."""
    quiz, _run = keeping_after_each()
    with needs_reveal_at_end():
        response = logged_in.post(use_url(quiz), {"key": REVEAL, "next": "/admin/"})
    html = text(response)
    assert response.status_code == 200
    assert 'name="flow_choice" value="run"' in html
    assert 'name="key" value="reveal_moment"' in html
    assert 'name="next" value="/admin/"' in html
    assert settings.quiz_override(REVEAL, quiz) == "after_each"


def test_use_answering_run_updates_the_run(logged_in):
    """AC-185"""
    quiz, run = keeping_after_each()
    with needs_reveal_at_end():
        response = logged_in.post(
            use_url(quiz), {"key": REVEAL, "next": "/admin/", "flow_choice": "run"}
        )
    assert response.status_code == 302
    assert response["Location"] == "/admin/"
    assert settings.quiz_override(REVEAL, quiz) == "at_end"
    run.refresh_from_db()
    assert run_flow.of(run)[REVEAL] == "at_end"


def test_use_answering_next_saves_only_the_quiz(logged_in):
    """AC-185"""
    quiz, run = keeping_after_each()
    with needs_reveal_at_end():
        response = logged_in.post(use_url(quiz), {"key": REVEAL, "flow_choice": "next"})
    assert response.status_code == 302
    assert settings.quiz_override(REVEAL, quiz) == "at_end"
    run.refresh_from_db()
    assert run_flow.of(run)[REVEAL] == "after_each"


def test_use_without_a_live_run_saves_at_once(logged_in):
    quiz = published_quiz()
    settings.set_override(REVEAL, quiz, "after_each", admin_id=ADMIN_ID)
    with needs_reveal_at_end():
        response = logged_in.post(use_url(quiz), {"key": REVEAL})
    assert response.status_code == 302
    assert settings.quiz_override(REVEAL, quiz) == "at_end"


def test_publishing_says_when_the_run_keeps_its_revision_for_requirements(logged_in):
    """AC-17: the admin is told, as for a stateless run, that the run stays on its revision."""
    quiz, run = keeping_after_each()
    settings.set_override(REVEAL, quiz, "at_end", admin_id=ADMIN_ID)
    before = run.current_revision_id
    with needs_reveal_at_end():
        add_question(quiz, prompt="Další")
        response = logged_in.post(
            f"/admin/quizzes/{quiz.id}/publish?lang=en",
            {"decision": "notify_switch", "snapshot_hash": authoring.snapshot_hash(quiz)},
        )
        assert authoring.held_back(quiz) == authoring.HELD_REQUIREMENTS
    assert response.status_code == 200
    assert "keeps settings that the new questions do not allow" in text(response)
    run.refresh_from_db()
    assert run.current_revision_id == before
