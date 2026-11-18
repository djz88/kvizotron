"""Application settings: a quiz override beats the global value, which beats the default.

Each setting states where it can be set (ADR-0042). Module configuration is a different thing and
belongs to `plugin_configuration`, created when a module first needs it (ADR-0057).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from django.db import transaction
from django.utils.translation import gettext_lazy

from app.contracts import (
    ADVANCED,
    ALLOW_INTERNAL_IMAGE_ADDRESSES,
    BASIC,
    EXTERNAL_IMAGE_MODE,
    IMAGE_MODE_COPY,
    PHOTO_ADMINS,
    PHOTO_VISIBILITY,
)
from app.domain.models import AppSetting, Quiz
from app.kernel import audit
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest

REVISION_SWITCH_POLICY = "revision_switch_policy"
NONE_OPTION = "none_option"
SHOW_SOURCES = "show_sources"
SHOW_HERO_LOGO = "show_hero_logo"
NAVIGATION_MODE = "navigation_mode"
PAGE_SIZE = "page_size"
REVEAL_MOMENT = "reveal_moment"
REVEAL_LEVEL = "reveal_level"
SHUFFLE_QUESTIONS = "shuffle_questions"
SHUFFLE_OPTIONS = "shuffle_options"
DATA_PROFILE = "data_profile"
RETENTION_PERIOD = "retention_period"
ANSWERS_VISIBILITY = "answers_visibility"
GRADING_VIEW = "grading_view"
TIME_ZONE = "time_zone"
ATTEMPT_LIMIT = "attempt_limit"
ANNOUNCE_PLANNED = "announce_planned"
NO_LIMIT = "0"
MAX_LIMIT_MINUTES = 1440
DEFAULT_TIME_ZONE = "Europe/Prague"
ALL_SCOPES = ("global", "quiz", "question")
QUIZ_WIDE = ("global", "quiz")
# Offered on a question of any type; the rest only on types that name them.
ALL_TYPES_QUESTION_SETTINGS = {SHOW_SOURCES}


class Policy(StrEnum):
    ASK = "ask"
    NOTIFY_SWITCH = "notify_switch"
    LET_FINISH = "let_finish"


class NoneOption(StrEnum):
    """Where the translated answer "None of the answers" appears."""

    ALL_QUESTIONS = "all_questions"
    TRICK_QUESTIONS = "trick_questions"


class ShowSources(StrEnum):
    """Whether a result lists the sources for the correct answers."""

    ON = "on"
    OFF = "off"


class Navigation(StrEnum):
    ALL_AT_ONCE = "all_at_once"
    STEP_BACK = "step_back"
    STEP_NO_BACK = "step_no_back"
    PAGES = "pages"


class RevealMoment(StrEnum):
    NEVER = "never"
    AT_END = "at_end"
    AFTER_EACH = "after_each"
    AFTER_CLOSE = "after_close"


class RevealLevel(StrEnum):
    """Cumulative: each level shows what the one before it does and more."""

    VERDICT = "verdict"
    ANSWERS = "answers"
    EXPLANATIONS = "explanations"


class DataProfile(StrEnum):
    """What a run keeps about an attempt, from nothing to everything."""

    NONE = "none"
    SCORE = "score"
    ANSWERS = "answers"
    DETAILED = "detailed"


class RetentionPeriod(StrEnum):
    D30 = "30d"
    D90 = "90d"
    D180 = "180d"
    Y1 = "1y"
    Y3 = "3y"
    PERMANENT = "permanent"


class AnswersVisibility(StrEnum):
    """Cumulative. Photos have their own setting, as the image answer owns them."""

    ADMINS = "admins"
    PARTICIPANT = "participant"
    PUBLIC = "public"


class GradingView(StrEnum):
    BY_QUESTION = "by_question"
    BY_ATTEMPT = "by_attempt"


class Switch(StrEnum):
    OFF = "off"
    ON = "on"


class UnknownSetting(Exception):
    pass


class InvalidSettingValue(Exception):
    pass


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    choices: tuple[str, ...]
    default: str
    label: Any
    value_labels: Mapping[str, Any]
    scopes: tuple[str, ...] = ALL_SCOPES
    scope_reason: str | None = None  # required when `scopes` is narrower than the whole chain
    help: Any = None
    group: str = "technical"  # one of SETTING_GROUPS
    level: str = ADVANCED  # BASIC shows it in the "Basic" view


_YES_NO: dict[str, Any] = {Switch.OFF: gettext_lazy("No"), Switch.ON: gettext_lazy("Yes")}
CATALOGUE = {
    REVISION_SWITCH_POLICY: SettingDefinition(
        REVISION_SWITCH_POLICY,
        tuple(Policy),
        Policy.ASK.value,
        gettext_lazy("When a new version is published during a run"),
        {
            Policy.ASK: gettext_lazy("Ask at publication"),
            Policy.NOTIFY_SWITCH: gettext_lazy("Notify participants and let them switch"),
            Policy.LET_FINISH: gettext_lazy("Let participants finish on the old version"),
        },
        QUIZ_WIDE,
        "A new revision replaces the whole quiz, not one question.",
        group="technical",
    ),
    NONE_OPTION: SettingDefinition(
        NONE_OPTION,
        tuple(NoneOption),
        NoneOption.ALL_QUESTIONS.value,
        gettext_lazy('Answer "None of the answers"'),
        {
            NoneOption.ALL_QUESTIONS: gettext_lazy(
                "On every question, which hides trick questions"
            ),
            NoneOption.TRICK_QUESTIONS: gettext_lazy("Only on trick questions"),
        },
        group="playing",
    ),
    DATA_PROFILE: SettingDefinition(
        DATA_PROFILE,
        tuple(DataProfile),
        DataProfile.SCORE.value,
        gettext_lazy("What a run keeps"),
        {
            DataProfile.NONE: gettext_lazy("Nothing: only counts"),
            DataProfile.SCORE: gettext_lazy("Score and photos"),
            DataProfile.ANSWERS: gettext_lazy("Score and all answers"),
            DataProfile.DETAILED: gettext_lazy("Score, all answers and times"),
        },
        QUIZ_WIDE,
        "A run copies this when it opens, and an attempt is stored as a whole.",
        group="data",
        level=BASIC,
    ),
    RETENTION_PERIOD: SettingDefinition(
        RETENTION_PERIOD,
        tuple(RetentionPeriod),
        RetentionPeriod.D90.value,
        gettext_lazy("How long a run keeps its data"),
        {
            RetentionPeriod.D30: gettext_lazy("30 days"),
            RetentionPeriod.D90: gettext_lazy("90 days"),
            RetentionPeriod.D180: gettext_lazy("180 days"),
            RetentionPeriod.Y1: gettext_lazy("1 year"),
            RetentionPeriod.Y3: gettext_lazy("3 years"),
            RetentionPeriod.PERMANENT: gettext_lazy("Permanently"),
        },
        QUIZ_WIDE,
        "A run copies this when it opens, and the whole run is kept or removed together.",
        group="data",
    ),
    ANSWERS_VISIBILITY: SettingDefinition(
        ANSWERS_VISIBILITY,
        tuple(AnswersVisibility),
        AnswersVisibility.ADMINS.value,
        gettext_lazy("Who sees stored answers"),
        {
            AnswersVisibility.ADMINS: gettext_lazy("Admins"),
            AnswersVisibility.PARTICIPANT: gettext_lazy("Admins and the participant"),
            AnswersVisibility.PUBLIC: gettext_lazy("Everyone, after the run ends"),
        },
        QUIZ_WIDE,
        "A walkthrough shows a run as a whole, so one quiz has one answer to this.",
        gettext_lazy(
            "Needs a profile that keeps all answers. Free text can say anything: "
            "in a public walkthrough a value is shown until an admin hides it."
        ),
        group="answers",
    ),
    GRADING_VIEW: SettingDefinition(
        GRADING_VIEW,
        tuple(GradingView),
        GradingView.BY_QUESTION.value,
        gettext_lazy("Grading page"),
        {
            GradingView.BY_QUESTION: gettext_lazy("By question"),
            GradingView.BY_ATTEMPT: gettext_lazy("By attempt"),
        },
        QUIZ_WIDE,
        "It arranges a whole page of a quiz, not one question.",
        group="technical",
    ),
    SHOW_SOURCES: SettingDefinition(
        SHOW_SOURCES,
        tuple(ShowSources),
        ShowSources.ON.value,
        gettext_lazy("Sources on the result"),
        {
            ShowSources.ON: gettext_lazy("Show"),
            ShowSources.OFF: gettext_lazy("Hide"),
        },
        group="answers",
    ),
    SHOW_HERO_LOGO: SettingDefinition(
        SHOW_HERO_LOGO,
        tuple(Switch),
        Switch.ON.value,
        gettext_lazy("Large logo on the home and About pages"),
        {Switch.ON: gettext_lazy("Show"), Switch.OFF: gettext_lazy("Hide")},
        ("global",),
        "The large logo is shown on pages that belong to no quiz.",
        group="look",
        level=BASIC,
    ),
    NAVIGATION_MODE: SettingDefinition(
        NAVIGATION_MODE,
        tuple(Navigation),
        Navigation.STEP_BACK.value,  # existing installations keep all at once (0015)
        gettext_lazy("Moving through the questions"),
        {
            Navigation.ALL_AT_ONCE: gettext_lazy("All questions at once"),
            Navigation.STEP_BACK: gettext_lazy("One by one, with going back"),
            Navigation.STEP_NO_BACK: gettext_lazy("One by one, without going back"),
            Navigation.PAGES: gettext_lazy("Pages of questions"),
        },
        QUIZ_WIDE,
        "An attempt is walked through in one way from start to end.",
        group="playing",
        level=BASIC,
    ),
    PAGE_SIZE: SettingDefinition(
        PAGE_SIZE,
        tuple(str(size) for size in range(2, 21)),
        "5",
        gettext_lazy("Questions per page"),
        {str(size): str(size) for size in range(2, 21)},
        QUIZ_WIDE,
        "Applies to the whole attempt, not to one question.",
        help=gettext_lazy("Only for pages of questions."),
        group="playing",
        level=BASIC,
    ),
    REVEAL_MOMENT: SettingDefinition(
        REVEAL_MOMENT,
        tuple(RevealMoment),
        RevealMoment.NEVER.value,
        gettext_lazy("When to show the answers"),
        {
            RevealMoment.NEVER: gettext_lazy("Never"),
            RevealMoment.AT_END: gettext_lazy("At the end"),
            RevealMoment.AFTER_EACH: gettext_lazy("After each question"),
            RevealMoment.AFTER_CLOSE: gettext_lazy("After the run closes"),
        },
        QUIZ_WIDE,
        "It depends on how the whole attempt is walked through.",
        group="answers",
        level=BASIC,
    ),
    REVEAL_LEVEL: SettingDefinition(
        REVEAL_LEVEL,
        tuple(RevealLevel),
        RevealLevel.VERDICT.value,
        gettext_lazy("What to show"),
        {
            RevealLevel.VERDICT: gettext_lazy("Whether each answer is right"),
            RevealLevel.ANSWERS: gettext_lazy("And the correct answers"),
            RevealLevel.EXPLANATIONS: gettext_lazy("And the correct answers and explanations"),
        },
        QUIZ_WIDE,
        "An attempt reveals one level of detail throughout.",
        group="answers",
    ),
    SHUFFLE_QUESTIONS: SettingDefinition(
        SHUFFLE_QUESTIONS,
        tuple(Switch),
        Switch.OFF.value,
        gettext_lazy("Shuffle the questions"),
        _YES_NO,
        QUIZ_WIDE,
        "It orders the whole attempt, not one question.",
        group="playing",
    ),
    SHUFFLE_OPTIONS: SettingDefinition(
        SHUFFLE_OPTIONS,
        tuple(Switch),
        Switch.OFF.value,
        gettext_lazy("Shuffle the options"),
        _YES_NO,
        group="playing",
    ),
    ATTEMPT_LIMIT: SettingDefinition(
        ATTEMPT_LIMIT,
        (NO_LIMIT, *map(str, range(1, MAX_LIMIT_MINUTES + 1))),
        NO_LIMIT,
        gettext_lazy("Time limit for an attempt (minutes)"),
        {
            NO_LIMIT: gettext_lazy("No limit"),
            **{str(minutes): str(minutes) for minutes in range(1, MAX_LIMIT_MINUTES + 1)},
        },
        QUIZ_WIDE,
        "It counts from the start of an attempt, so a question has no use for it.",
        group="playing",
        level=BASIC,
    ),
    ANNOUNCE_PLANNED: SettingDefinition(
        ANNOUNCE_PLANNED,
        tuple(Switch),
        Switch.OFF.value,
        gettext_lazy('Show a planned quiz under "Coming up" on the public list'),
        _YES_NO,
        QUIZ_WIDE,
        "It concerns a whole quiz on the public list, not one question.",
        group="look",
    ),
    TIME_ZONE: SettingDefinition(
        TIME_ZONE,
        tuple(sorted(available_timezones())),
        DEFAULT_TIME_ZONE,
        gettext_lazy("Time zone"),
        {name: name for name in available_timezones()},
        ("global",),
        "One installation serves one place, and different zones in one list would mislead.",
        group="technical",
        level=BASIC,
    ),
}


def register_modules(modules: Sequence[Manifest]) -> None:
    """Settings live and die with their module. A key owned twice cannot be resolved."""
    for module in modules:
        for declared in module.settings:
            if declared.key in CATALOGUE:
                raise StartupError(f"Module {module.id}: setting {declared.key} already exists")
            CATALOGUE[declared.key] = SettingDefinition(
                declared.key,
                tuple(declared.choices),
                declared.default,
                gettext_lazy(declared.label),  # noqa: INT001  # the module's catalogue has it
                {
                    value: gettext_lazy(text)  # noqa: INT001
                    for value, text in declared.value_labels.items()
                },
                tuple(declared.scopes),
                declared.scope_reason,
                gettext_lazy(declared.help) if declared.help else None,  # noqa: INT001
                declared.group,
                declared.level,
            )
    check_requirements(modules)


def check_requirements(modules: Sequence[Manifest]) -> None:
    """After every module's settings are known, as a requirement may name another module's."""
    for module in modules:
        for key, requirement in module.settings_requirements.items():
            definition = CATALOGUE.get(key)
            if definition is None:
                raise StartupError(f"Module {module.id}: requires unknown setting {key}")
            for value in (*requirement.refuse, requirement.use):
                if value not in definition.choices:
                    raise StartupError(f"Module {module.id}: {key} does not offer {value}")


def keys_for(scope: str) -> list[str]:
    return [key for key, definition in CATALOGUE.items() if scope in definition.scopes]


@dataclass(frozen=True)
class Flow:
    """How a quiz behaves for an attempt started now."""

    navigation: str
    moment: str
    level: str
    shuffle_questions: bool
    shuffle_options: bool
    conflict: bool  # a later global change broke the combination; `moment` has fallen back
    page_size: int = 1  # questions per step; more than one only for pages


def _definition(key: str) -> SettingDefinition:
    try:
        return CATALOGUE[key]
    except KeyError as exc:
        raise UnknownSetting(key) from exc


def _checked(key: str, value: str) -> str:
    if value not in _definition(key).choices:
        raise InvalidSettingValue(f"{key}={value}")
    return value


def _offered(definition: SettingDefinition, stored: AppSetting) -> bool:
    """A later release may retire a value that is still stored."""
    return stored.value_json in definition.choices


def question_value(key: str, question: Mapping[str, Any]) -> str | None:
    """A stored value that is no longer offered counts as none, as it does on the other levels."""
    value = (question.get("settings") or {}).get(key)
    return value if value in _definition(key).choices else None


def resolve(key: str, quiz: Quiz | None = None, question: Mapping[str, Any] | None = None) -> str:
    definition = _definition(key)
    if question is not None:
        value = question_value(key, question)
        if value is not None:
            return value
    override = quiz_override(key, quiz) if quiz is not None else None
    if override is not None:
        return override
    stored = AppSetting.objects.filter(key=key, quiz__isnull=True).first()
    return stored.value_json if stored and _offered(definition, stored) else definition.default


def attempt_limit_seconds(quiz: Quiz) -> int | None:
    minutes = int(resolve(ATTEMPT_LIMIT, quiz))
    return minutes * 60 or None


def zone() -> ZoneInfo:
    return ZoneInfo(resolve(TIME_ZONE))


def image_mode(quiz: Quiz | None = None, question: Mapping[str, Any] | None = None) -> str:
    """Without a media provider the setting does not exist, and neither do images."""
    if EXTERNAL_IMAGE_MODE not in CATALOGUE:
        return IMAGE_MODE_COPY
    return resolve(EXTERNAL_IMAGE_MODE, quiz, question)


def internal_addresses_allowed() -> bool:
    return (
        ALLOW_INTERNAL_IMAGE_ADDRESSES in CATALOGUE
        and resolve(ALLOW_INTERNAL_IMAGE_ADDRESSES) == "on"
    )


def is_flow_conflict(navigation: str, moment: str) -> bool:
    """Showing answers after each question needs a next question to go on to."""
    return moment == RevealMoment.AFTER_EACH and navigation in (
        Navigation.ALL_AT_ONCE,
        Navigation.PAGES,
    )


def is_visibility_conflict(profile: str, visibility: str) -> bool:
    """What was not stored cannot be shown."""
    return visibility != AnswersVisibility.ADMINS and profile not in (
        DataProfile.ANSWERS,
        DataProfile.DETAILED,
    )


def visibility_conflict(quiz: Quiz) -> bool:
    return is_visibility_conflict(resolve(DATA_PROFILE, quiz), resolve(ANSWERS_VISIBILITY, quiz))


def answers_visibility(quiz: Quiz) -> str:
    """A global change can fall into the conflict later, so it is resolved here as well."""
    if visibility_conflict(quiz):
        return AnswersVisibility.ADMINS.value
    return resolve(ANSWERS_VISIBILITY, quiz)


def photo_level(quiz: Quiz, question: Mapping[str, Any] | None = None) -> str:
    """Admins only when the module that owns the setting is gone."""
    if PHOTO_VISIBILITY not in CATALOGUE:
        return PHOTO_ADMINS
    return resolve(PHOTO_VISIBILITY, quiz, question)


# `show_sources` is per question and lives only in `run_flow.KEYS`; a new flow key goes in both.
FLOW_KEYS = (
    NAVIGATION_MODE,
    PAGE_SIZE,
    REVEAL_MOMENT,
    REVEAL_LEVEL,
    SHUFFLE_QUESTIONS,
    SHUFFLE_OPTIONS,
)


def flow_of(values: Mapping[str, str]) -> Flow:
    """The flow of the given resolved values, as a run keeps them (ADR-0069)."""
    navigation = values[NAVIGATION_MODE]
    moment = values[REVEAL_MOMENT]
    conflict = is_flow_conflict(navigation, moment)
    return Flow(
        navigation=navigation,
        moment=RevealMoment.AT_END.value if conflict else moment,
        level=values[REVEAL_LEVEL],
        shuffle_questions=values[SHUFFLE_QUESTIONS] == Switch.ON,
        shuffle_options=values[SHUFFLE_OPTIONS] == Switch.ON,
        conflict=conflict,
        page_size=int(values[PAGE_SIZE]),
    )


def flow(quiz: Quiz) -> Flow:
    return flow_of({key: resolve(key, quiz) for key in FLOW_KEYS})


def quiz_override(key: str, quiz: Quiz) -> str | None:
    definition = _definition(key)
    stored = AppSetting.objects.filter(key=key, quiz=quiz).first()
    return stored.value_json if stored and _offered(definition, stored) else None


def set_global(key: str, value: str, *, admin_id: str | None) -> None:
    _checked(key, value)
    with transaction.atomic():
        AppSetting.objects.update_or_create(key=key, quiz=None, defaults={"value_json": str(value)})
        _audit(key, value, "global", admin_id)


def set_override(key: str, quiz: Quiz, value: str | None, *, admin_id: str | None) -> None:
    """`None` deletes the override, so the quiz follows the global value again."""
    _definition(key)
    with transaction.atomic():
        if value is None:
            AppSetting.objects.filter(key=key, quiz=quiz).delete()
        else:
            _checked(key, value)
            AppSetting.objects.update_or_create(
                key=key, quiz=quiz, defaults={"value_json": str(value)}
            )
        _audit(key, value, str(quiz.id), admin_id)


def _audit(key: str, value: str | None, scope: str, admin_id: str | None) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action="setting.changed",
        entity_type="setting",
        entity_id=scope,
        details={"key": key, "value": str(value) if value is not None else None},
    )
