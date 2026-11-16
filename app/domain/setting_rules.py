"""Which quiz settings cannot go together: the cross-field rules of the settings forms.

The forms map each `Clash` to a message; a quiz type is checked by the same rules (ADR-0062).
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from app.contracts import (
    PARTICIPANT_KEYS,
    RESULT_KEYS,
    SCOREBOARD_SECOND_SORT,
    SCOREBOARD_SHOW_DURATION,
    SCOREBOARD_VISIBILITY,
)
from app.domain import data_policy, results, rewards, settings
from app.domain.models import Quiz, QuizRun

__all__ = [
    "ADJUSTABLE",
    "AFTER_CLOSE_PROFILE",
    "AFTER_CLOSE_VISIBILITY",
    "FLOW",
    "NEEDS_TIMES",
    "RESULT_AFTER_EACH",
    "RESULT_STATELESS",
    "RUN_BOARD",
    "RUN_PROFILE",
    "RUN_REWARDS",
    "STATELESS",
    "VISIBILITY",
    "Clash",
    "clashes",
]

FLOW = "flow"  # answers after each question in a mode without a next question
VISIBILITY = "visibility"  # answers shown to more than admins, but not kept
STATELESS = "stateless_rules"  # "nothing" with a rule that needs to remember someone
RESULT_STATELESS = results.STATELESS  # "nothing" with a visible scoreboard
RESULT_AFTER_EACH = results.AFTER_EACH  # answers after each question beside a visible board
NEEDS_TIMES = results.NEEDS_TIMES  # the duration on the board without the profile with times
RUN_BOARD = "run_board"  # answers after each question while a planned or open run shows a board
RUN_REWARDS = "run_rewards"  # the same while a planned or open run has reward rules
AFTER_CLOSE_PROFILE = "after_close_profile"  # answers after the run closes, but not kept
AFTER_CLOSE_VISIBILITY = "after_close_visibility"  # the same, but a participant may not see them
RUN_PROFILE = "run_profile"  # the same while a planned or open run keeps no answers

# The value of each key that ends the clash without asking the admin.
ADJUSTABLE: dict[str, dict[str, str]] = {
    VISIBILITY: {settings.ANSWERS_VISIBILITY: settings.AnswersVisibility.ADMINS.value},
    AFTER_CLOSE_PROFILE: {settings.DATA_PROFILE: settings.DataProfile.ANSWERS.value},
    AFTER_CLOSE_VISIBILITY: {
        settings.ANSWERS_VISIBILITY: settings.AnswersVisibility.PARTICIPANT.value
    },
    NEEDS_TIMES: {SCOREBOARD_SHOW_DURATION: "off", SCOREBOARD_SECOND_SORT: "submitted"},
}


@dataclass(frozen=True)
class Clash:
    reason: str
    key: str  # the setting the message attaches to
    detail: str | None = None  # the participant key for STATELESS, or data_policy.PHOTO_QUESTION


def _live_runs(quiz: Quiz | None) -> Iterator[QuizRun]:
    """For the global values, the runs of every quiz that takes the global answers setting."""
    live = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN)
    if quiz is not None:
        yield from quiz.runs.filter(status__in=live)
        return
    for run in QuizRun.objects.filter(status__in=live).select_related("quiz"):
        if settings.quiz_override(settings.REVEAL_MOMENT, run.quiz) is None:
            yield run


def clashes(values: Mapping[str, str], quiz: Quiz | None) -> list[Clash]:
    """`values` are resolved values; a missing or empty key takes the global value.

    `quiz` None judges global values. Runs already planned or open count too (AC-18).
    """

    def value(key: str) -> str:
        return values.get(key) or settings.resolve(key)

    found: list[Clash] = []
    moment = value(settings.REVEAL_MOMENT)
    profile = value(settings.DATA_PROFILE)
    if settings.is_flow_conflict(value(settings.NAVIGATION_MODE), moment):
        found.append(Clash(FLOW, settings.REVEAL_MOMENT))
    after_close = moment == settings.RevealMoment.AFTER_CLOSE
    keeps = data_policy.keeps_all_answers(profile)
    visibility = value(settings.ANSWERS_VISIBILITY)
    # After the run closes, the profile is the one cause: fixing it fixes this clash too.
    if settings.is_visibility_conflict(profile, visibility) and not after_close:
        found.append(Clash(VISIBILITY, settings.ANSWERS_VISIBILITY))
    # Under "nothing" no one is remembered; the visibility clash is reported above.
    rules = {key: value(key) for key in PARTICIPANT_KEYS}
    admins = settings.AnswersVisibility.ADMINS.value
    for key in data_policy.conflicts(profile, rules, admins, None):
        found.append(Clash(STATELESS, key, key))
    chosen = {key: value(key) for key in RESULT_KEYS}
    why = results.reasons(chosen, profile=profile, reveal_moment=moment)
    attached = {
        RESULT_STATELESS: SCOREBOARD_VISIBILITY,
        RESULT_AFTER_EACH: settings.REVEAL_MOMENT,
        NEEDS_TIMES: SCOREBOARD_VISIBILITY,
    }
    found += [Clash(reason, attached[reason]) for reason in why]
    if after_close:
        if not keeps:
            found.append(Clash(AFTER_CLOSE_PROFILE, settings.DATA_PROFILE))
        elif visibility == settings.AnswersVisibility.ADMINS:
            found.append(Clash(AFTER_CLOSE_VISIBILITY, settings.ANSWERS_VISIBILITY))
        if any(
            not data_policy.keeps_all_answers(data_policy.of(run)[data_policy.PROFILE])
            for run in _live_runs(quiz)
        ):
            found.append(Clash(RUN_PROFILE, settings.REVEAL_MOMENT))
    if moment != settings.RevealMoment.AFTER_EACH:
        return found
    runs = list(_live_runs(quiz))
    if RESULT_AFTER_EACH not in why and any(results.needs_participant(run) for run in runs):
        found.append(Clash(RUN_BOARD, settings.REVEAL_MOMENT))
    # Answers after each question would tell a player what the next attempt needs.
    if any(rewards.has_rules(run) for run in runs):
        found.append(Clash(RUN_REWARDS, settings.REVEAL_MOMENT))
    return found
