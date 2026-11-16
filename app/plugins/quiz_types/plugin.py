"""Seven quiz types: named bundles of quiz settings (ADR-0062).

Only definitions. Which keys a quiz then overrides, the deviations and the clashes are the domain's.
The core setting keys live in the domain, which a plugin may not import, so they are spelled here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy

from app.contracts import (
    AFTER_PASS,
    ASK_EMAIL,
    ASK_NAME,
    ASK_WHEN,
    DUPLICATE_NAMES,
    MAX_ATTEMPTS,
    OFFICIAL_ATTEMPT,
    PASS_MARK,
    REPEAT_ATTEMPTS,
    REWARD_SOURCE,
    SCOREBOARD_VISIBILITY,
    WINNER_CONTACT,
)

NAVIGATION_MODE = "navigation_mode"
PAGE_SIZE = "page_size"
REVEAL_MOMENT = "reveal_moment"
REVEAL_LEVEL = "reveal_level"
SHUFFLE_QUESTIONS = "shuffle_questions"
SHUFFLE_OPTIONS = "shuffle_options"
ATTEMPT_LIMIT = "attempt_limit"  # minutes, "0" is no limit
DATA_PROFILE = "data_profile"
SHOW_SOURCES = "show_sources"
ANSWERS_VISIBILITY = "answers_visibility"


@dataclass(frozen=True)
class QuizType:
    id: str
    order: int
    title: Promise
    summary: Promise
    settings: Mapping[str, str] = field(default_factory=dict)
    resets_all: bool = False
    version: str = "1.0.0"

    def label(self) -> str:
        return str(self.title)

    def description(self) -> str:
        return str(self.summary)

    def values(self) -> Mapping[str, str]:
        """A copy, so no caller can change the definition."""
        return dict(self.settings)


TYPES = (
    QuizType(
        "practice",
        10,
        gettext_lazy("Practice"),
        gettext_lazy("Learning: answers and explanations after each question, no time limit."),
        {
            NAVIGATION_MODE: "step_no_back",
            REVEAL_MOMENT: "after_each",
            REVEAL_LEVEL: "explanations",
            SHUFFLE_QUESTIONS: "on",
            SHUFFLE_OPTIONS: "on",
            ATTEMPT_LIMIT: "0",
            REPEAT_ATTEMPTS: "allow",
            ASK_NAME: "off",
            ASK_EMAIL: "off",
            SCOREBOARD_VISIBILITY: "hidden",
            DATA_PROFILE: "score",
            SHOW_SOURCES: "on",
        },
    ),
    QuizType(
        "final_test",
        20,
        gettext_lazy("Final test"),
        gettext_lazy("One named attempt in 30 minutes; answers are kept and never shown."),
        {
            NAVIGATION_MODE: "step_no_back",
            REVEAL_MOMENT: "never",
            SHUFFLE_QUESTIONS: "on",
            SHUFFLE_OPTIONS: "on",
            ATTEMPT_LIMIT: "30",
            REPEAT_ATTEMPTS: "forbid",
            ASK_NAME: "required",
            ASK_WHEN: "start",
            ASK_EMAIL: "off",
            DUPLICATE_NAMES: "allow",
            SCOREBOARD_VISIBILITY: "hidden",
            OFFICIAL_ATTEMPT: "first",
            PASS_MARK: "70",
            DATA_PROFILE: "answers",
            SHOW_SOURCES: "off",
        },
    ),
    QuizType(
        "resit_exam",
        25,
        gettext_lazy("Exam with a resit"),
        gettext_lazy(
            "An exam with a pass mark and a second attempt; the better one counts "
            "and answers are shown after the run closes."
        ),
        {
            NAVIGATION_MODE: "step_no_back",
            SHUFFLE_QUESTIONS: "on",
            SHUFFLE_OPTIONS: "on",
            ATTEMPT_LIMIT: "30",
            REPEAT_ATTEMPTS: "allow",
            MAX_ATTEMPTS: "2",
            AFTER_PASS: "more",
            ASK_NAME: "required",
            ASK_WHEN: "start",
            ASK_EMAIL: "off",
            DUPLICATE_NAMES: "allow",
            SCOREBOARD_VISIBILITY: "hidden",
            OFFICIAL_ATTEMPT: "best",
            PASS_MARK: "70",
            REVEAL_MOMENT: "after_close",
            REVEAL_LEVEL: "explanations",
            DATA_PROFILE: "answers",
            ANSWERS_VISIBILITY: "participant",
            SHOW_SOURCES: "off",
        },
    ),
    QuizType(
        "mock_test",
        30,
        gettext_lazy("Mock test"),
        gettext_lazy("A test in 30 minutes that can be repeated, with explanations at the end."),
        {
            NAVIGATION_MODE: "step_back",
            REVEAL_MOMENT: "at_end",
            REVEAL_LEVEL: "explanations",
            SHUFFLE_QUESTIONS: "on",
            SHUFFLE_OPTIONS: "on",
            ATTEMPT_LIMIT: "30",
            REPEAT_ATTEMPTS: "allow",
            ASK_NAME: "off",
            ASK_EMAIL: "off",
            SCOREBOARD_VISIBILITY: "hidden",
            PASS_MARK: "70",
            MAX_ATTEMPTS: "0",
            DATA_PROFILE: "score",
            SHOW_SOURCES: "on",
        },
    ),
    QuizType(
        "contest",
        40,
        gettext_lazy("Contest"),
        gettext_lazy(
            "One attempt with a name and an e-mail, the scoreboard after the end; "
            "add the prize on the Rewards tab."
        ),
        {
            NAVIGATION_MODE: "step_back",
            REVEAL_MOMENT: "never",
            SHUFFLE_QUESTIONS: "on",
            SHUFFLE_OPTIONS: "on",
            ATTEMPT_LIMIT: "0",
            REPEAT_ATTEMPTS: "forbid",
            ASK_NAME: "required",
            ASK_WHEN: "end",
            ASK_EMAIL: "required",
            DUPLICATE_NAMES: "forbid",
            SCOREBOARD_VISIBILITY: "after_end",
            OFFICIAL_ATTEMPT: "first",
            REWARD_SOURCE: "quiz",
            WINNER_CONTACT: "require_email",
            DATA_PROFILE: "score",
            SHOW_SOURCES: "off",
        },
    ),
    QuizType(
        "pub_quiz",
        50,
        gettext_lazy("Pub quiz"),
        gettext_lazy(
            "One phone per team with the team name as nickname, ten questions per page "
            "and a live scoreboard."
        ),
        {
            NAVIGATION_MODE: "pages",
            PAGE_SIZE: "10",
            REVEAL_MOMENT: "at_end",
            REVEAL_LEVEL: "answers",
            SHUFFLE_QUESTIONS: "off",
            SHUFFLE_OPTIONS: "off",
            ATTEMPT_LIMIT: "0",
            REPEAT_ATTEMPTS: "forbid",
            ASK_NAME: "required",
            ASK_WHEN: "start",
            ASK_EMAIL: "off",
            DUPLICATE_NAMES: "forbid",
            SCOREBOARD_VISIBILITY: "live",
            OFFICIAL_ATTEMPT: "first",
            DATA_PROFILE: "score",
            SHOW_SOURCES: "on",
        },
    ),
    QuizType(
        "basic",
        60,
        gettext_lazy("Basic quiz"),
        gettext_lazy("Removes the quiz's own settings, so the global settings apply again."),
        resets_all=True,
    ),
)
