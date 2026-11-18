"""A module states which settings it needs; the kernel applies that (ADR-0034, AC-61)."""

import pytest

from app.domain import authoring, requirements, run_flow, run_schedule, settings
from app.domain.models import QuizRun
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest
from app.kernel.models import AuditEvent
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_question,
    add_row,
    make_bank,
    make_quiz,
    published_quiz,
)
from tests.support.requirements import REASON, needs_reveal_at_end, requiring

pytestmark = pytest.mark.django_db
KEY = settings.REVEAL_MOMENT


def manifest(**requirement):
    fields = {"refuse": ["after_each"], "use": "at_end", "reason": REASON} | requirement
    return Manifest.model_validate(
        {
            "id": "mod.needs",
            "kind": "plugin",
            "version": "1.0.0",
            "app": "x.y",
            "api_compatibility": ">=1.0",
            "settings": [],
            "settings_requirements": {KEY: fields},
        }
    )


def needing_quiz(value="after_each"):
    quiz = make_quiz()
    add_question(quiz)
    settings.set_override(KEY, quiz, value, admin_id=ADMIN_ID)
    return quiz


def test_manifest_requires_a_use_outside_refuse():
    with pytest.raises(ValueError):
        manifest(use="after_each")


def test_known_requirement_starts():
    settings.check_requirements([manifest()])


def test_unknown_key_is_a_startup_error():
    module = manifest().model_copy(
        update={
            "settings_requirements": {
                "no_such_setting": manifest().settings_requirements[KEY],
            }
        }
    )
    with pytest.raises(StartupError):
        settings.check_requirements([module])


@pytest.mark.parametrize("fields", [{"use": "sometime"}, {"refuse": ["sometime"]}])
def test_unknown_value_is_a_startup_error(fields):
    with pytest.raises(StartupError):
        settings.check_requirements([manifest(**fields)])


def test_unmet_blocks_publication_with_the_reason():
    """AC-17: a conflicting setting blocks publication and the problem carries the reason."""
    quiz = needing_quiz()
    with needs_reveal_at_end():
        problems = authoring.validate_for_publication(quiz)
        with pytest.raises(authoring.PublicationError):
            authoring.publish(quiz, admin_id=ADMIN_ID)
    found = [problem for problem in problems if problem.code == "requirement"]
    assert [problem.detail for problem in found] == [REASON]


def test_met_allows_publication():
    """AC-17: once the required setting is satisfied, the quiz publishes."""
    quiz = needing_quiz("at_end")
    with needs_reveal_at_end():
        assert authoring.validate_for_publication(quiz) == []
        assert authoring.publish(quiz, admin_id=ADMIN_ID).status == "PUBLISHED"


def test_unmet_blocks_opening_a_run():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "after_each", admin_id=ADMIN_ID)
    with needs_reveal_at_end():
        with pytest.raises(authoring.RequirementUnmet) as error:
            authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert error.value.reasons == [REASON]


def test_a_run_is_judged_by_what_it_will_play_not_by_the_draft():
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "after_each", admin_id=ADMIN_ID)
    with needs_reveal_at_end("question.matching"):
        authoring.save_question(
            quiz,
            None,
            "matching",
            {
                "prompt": {"cs": "Spojte"},
                "mode": "order",
                "items": [
                    {"id": "a", "text": {"cs": "A"}},
                    {"id": "b", "text": {"cs": "B"}},
                ],
            },
        )
        assert requirements.unmet(quiz)
        assert authoring.open_run(quiz, admin_id=ADMIN_ID)


def test_type_only_in_a_draw_pool_counts():
    quiz = make_quiz()
    bank = make_bank()
    add_bank_question(bank)
    add_row(quiz, bank)
    settings.set_override(KEY, quiz, "after_each", admin_id=ADMIN_ID)
    with needs_reveal_at_end():
        assert [found.key for found in requirements.of_quiz(quiz)] == [KEY]


def test_missing_bank_requires_nothing():
    quiz = make_quiz()
    bank = make_bank()
    add_bank_question(bank)
    add_row(quiz, bank)
    bank.questions.all().delete()
    bank.delete()
    with needs_reveal_at_end():
        assert requirements.of_quiz(quiz) == []


def test_type_not_used_requires_nothing():
    quiz = needing_quiz()
    with needs_reveal_at_end("question.matching"):
        assert requirements.unmet(quiz) == []


def test_contradicting_requirements_block():
    quiz = make_quiz()
    add_question(quiz)
    with requiring(reveal_moment=(["at_end"], "never")):
        one = requirements.of_quiz(quiz)[0]
    with requiring(reveal_moment=(["never"], "at_end")):
        other = requirements.of_quiz(quiz)[0]
    assert requirements.contradiction([one, other]) == (one, other)
    assert requirements.contradiction([one]) is None


def test_contradiction_is_a_publication_problem(monkeypatch):
    quiz = make_quiz()
    add_question(quiz)
    with requiring(reveal_moment=(["at_end"], "never")):
        one = requirements.of_quiz(quiz)[0]
    with requiring(reveal_moment=(["never"], "at_end")):
        other = requirements.of_quiz(quiz)[0]
    monkeypatch.setattr(requirements, "of_quiz", lambda _quiz: [one, other])
    codes = [problem.code for problem in authoring.validate_for_publication(quiz)]
    assert "requirement_conflict" in codes


def test_requirement_is_read_through_resolve():
    quiz = make_quiz()
    add_question(quiz)
    with needs_reveal_at_end():
        assert requirements.unmet(quiz) == []
        settings.set_global(KEY, "after_each", admin_id=ADMIN_ID)
        assert [found.key for found in requirements.unmet(quiz)] == [KEY]
        settings.set_override(KEY, quiz, "at_end", admin_id=ADMIN_ID)
        assert requirements.unmet(quiz) == []


def test_of_type_names_the_module_and_values():
    with needs_reveal_at_end():
        found = requirements.of_type("choice")
    assert [(item.module, item.key, item.refuse, item.use, item.reason) for item in found] == [
        ("question.choice", KEY, ("after_each",), "at_end", REASON)
    ]
    assert requirements.of_type("no-such-type") == []


def test_test_link_draft_copy_is_blocked():
    quiz = needing_quiz()
    with needs_reveal_at_end(), pytest.raises(authoring.PublicationError):
        authoring.freeze_copy(quiz)


def test_applying_is_an_ordinary_audited_override():
    quiz = needing_quiz()
    with needs_reveal_at_end():
        requirement = requirements.unmet(quiz)[0]
        requirements.apply(requirement, quiz, admin_id=ADMIN_ID)
        assert requirements.unmet(quiz) == []
    assert settings.quiz_override(KEY, quiz) == "at_end"
    assert AuditEvent.objects.filter(action="setting.changed").exists()


def test_unmet_judges_a_given_value_instead_of_the_quiz():
    """AC-17: a run's kept value is judged, not the quiz's (TD-101)."""
    quiz = needing_quiz("at_end")
    with needs_reveal_at_end():
        assert requirements.unmet(quiz) == []
        assert [i.key for i in requirements.unmet(quiz, values={KEY: "after_each"})] == [KEY]
        assert requirements.unmet(quiz, values={"other": "after_each"}) == []


def keeping_after_each():
    """A run opened with `after_each`; the quiz was later changed to `at_end` for the next run."""
    quiz = published_quiz()
    settings.set_override(KEY, quiz, "after_each", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    settings.set_override(KEY, quiz, "at_end", admin_id=ADMIN_ID)
    assert run_flow.of(run)[KEY] == "after_each"
    return quiz, run


def test_an_open_run_keeping_the_refused_value_stays_on_its_revision():
    """AC-17: publishing a revision the run's values do not meet does not move the run."""
    quiz, run = keeping_after_each()
    before = run.current_revision_id
    with needs_reveal_at_end():
        add_question(quiz, prompt="Další")
        authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    run.refresh_from_db()
    assert run.current_revision_id == before


def test_an_open_run_whose_values_meet_them_is_moved():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    with needs_reveal_at_end():
        add_question(quiz, prompt="Další")
        draft = authoring.publish(
            quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH
        )
    run.refresh_from_db()
    assert run.current_revision_id == draft.id


def test_a_planned_run_keeping_the_refused_value_keeps_its_revision():
    """AC-17: the same hold for a planned run."""
    from datetime import UTC, datetime, timedelta

    quiz = published_quiz()
    settings.set_override(KEY, quiz, "after_each", admin_id=ADMIN_ID)
    starts = datetime.now(UTC) + timedelta(days=1)
    planned = run_schedule.plan(
        quiz, starts_at=starts, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
    )
    settings.set_override(KEY, quiz, "at_end", admin_id=ADMIN_ID)
    before = planned.current_revision_id
    with needs_reveal_at_end():
        add_question(quiz, prompt="Další")
        authoring.publish(quiz, admin_id=ADMIN_ID)
    assert QuizRun.objects.get(pk=planned.pk).current_revision_id == before
