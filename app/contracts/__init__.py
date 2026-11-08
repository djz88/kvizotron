"""Public contracts between the kernel and modules. Must not import Django."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

CONTRACT_VERSION = "1.0"

# Infrastructure with exactly one active provider per process (ADR-0037).
EXTERNAL_IMAGE_MODE = "external_image_mode"
IMAGE_MODE_COPY = "copy"
IMAGE_MODE_EXTERNAL = "external"
ALLOW_INTERNAL_IMAGE_ADDRESSES = "allow_internal_image_addresses"
PHOTO_VISIBILITY = "photo_visibility"
PHOTO_ADMINS = "admins"
PHOTO_AUTHOR = "author"
PHOTO_PUBLIC = "public"
MAX_PHOTO_BYTES = 15 * 1024 * 1024  # ADR-0028
REPEAT_ATTEMPTS = "repeat_attempts"  # allow, forbid
UNFINISHED_ATTEMPT = "unfinished_attempt"  # continue, used, submitted
ASK_NAME = "ask_name"  # off, optional, required
ASK_EMAIL = "ask_email"  # off, optional, required
ASK_WHEN = "ask_when"  # end, start
DUPLICATE_NAMES = "duplicate_names"  # allow, forbid
LOCAL_RESUME = "local_resume"  # on, off
SCOREBOARD_VISIBILITY = "scoreboard_visibility"  # hidden, live, after_end
SCOREBOARD_LIVE_NAMES = "scoreboard_live_names"  # shown, anonymised
SCOREBOARD_UNNAMED = "scoreboard_unnamed"  # anonymous, unlisted
OFFICIAL_ATTEMPT = "official_attempt"  # best, first
SCOREBOARD_SHOW_SCORE = "scoreboard_show_score"  # on, off
SCOREBOARD_SHOW_PERCENT = "scoreboard_show_percent"  # on, off
SCOREBOARD_SHOW_TIME = "scoreboard_show_time"  # on, off
SCOREBOARD_SHOW_DURATION = "scoreboard_show_duration"  # on, off
SCOREBOARD_SECOND_SORT = "scoreboard_second_sort"  # submitted, duration
TIE_BREAK_POLICY = "tie_break_policy"  # shared, earlier, random (ADR-0026)
REVISION_MODE = "revision_mode"  # separate, latest; "merged" is an admin action (ADR-0008)
ARCHIVED_RESULTS = "archived_results"  # off, on (ADR-0031)
REWARD_SOURCE = "reward_source"  # none, previous_run, quiz; only fills a new run
REWARD_THRESHOLDS = "reward_thresholds"  # highest, all
WINNER_CONTACT = "winner_contact"  # warn, require_email, silent
# Where a setting shows on the settings pages, and whether "Basic" shows it (ADR-0052)
SETTING_GROUPS = ("playing", "answers", "participants", "scoreboard", "data", "look", "technical")
BASIC = "basic"
ADVANCED = "advanced"
PARTICIPANT_KEYS: tuple[str, ...] = (
    REPEAT_ATTEMPTS,
    UNFINISHED_ATTEMPT,
    ASK_NAME,
    ASK_EMAIL,
    ASK_WHEN,
    DUPLICATE_NAMES,
)
RESULT_KEYS: tuple[str, ...] = (
    SCOREBOARD_VISIBILITY,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_UNNAMED,
    OFFICIAL_ATTEMPT,
    SCOREBOARD_SHOW_SCORE,
    SCOREBOARD_SHOW_PERCENT,
    SCOREBOARD_SHOW_TIME,
    SCOREBOARD_SHOW_DURATION,
    SCOREBOARD_SECOND_SORT,
    TIE_BREAK_POLICY,
    REVISION_MODE,
    ARCHIVED_RESULTS,
)
# What only changes what is shown, so it may change on a running, ended or archived run.
RESULT_DISPLAY_KEYS: tuple[str, ...] = tuple(
    key for key in RESULT_KEYS if key not in (OFFICIAL_ATTEMPT, TIE_BREAK_POLICY, REVISION_MODE)
)
# Copied onto the run with its rewards, fixed once the run opens.
REWARD_RUN_KEYS: tuple[str, ...] = (REWARD_THRESHOLDS, WINNER_CONTACT)
EXACTLY_ONE: frozenset[str] = frozenset({"auth", "persistence", "media_storage", "retention"})

# Capabilities that must be present to start.
REQUIRED_CAPABILITIES: frozenset[str] = frozenset({"auth", "persistence"})


JSON = Mapping[str, Any]


class AdminFormError(ValueError):
    """An editor form cannot be read; `config` is what could be, so the form keeps the input."""

    def __init__(self, message: str, config: JSON) -> None:
        super().__init__(message)
        self.config = config


class CsvRowError(ValueError):
    """A row of an import cannot be used. `column` names the cell, when one is to blame."""

    def __init__(self, column: str | None, message: str) -> None:
        super().__init__(message)
        self.column = column


@dataclass(frozen=True)
class ItemGrade:
    """How an answer compares with the definition. Only the question type can tell."""

    right: int
    wrong: int
    total: int


@dataclass(frozen=True)
class ScoreBreakdown:
    earned_points: Decimal  # the automatic part only
    max_points: Decimal  # includes any manual part
    correct_count: int | None
    details: JSON


class ImageRefused(ValueError):
    """An uploaded file cannot be stored. The message is translated and meant for the admin."""


@dataclass(frozen=True)
class AddressStatus:
    ok: bool
    checked_at: datetime


class ImageAddressInvalid(ImageRefused):
    """The address itself is wrong, so no mode can use it."""


@dataclass(frozen=True)
class StoredImage:
    path: str
    mime_type: str
    private: bool = False  # a participant's photo: served only where the right is checked


@dataclass(frozen=True)
class DefinitionRow:
    """One line of a readable description of a question, for comparing revisions."""

    key: str  # stable across revisions of the same question, for example "option:aaaa1111"
    label: str  # follows the active translation
    locale: str | None
    value: str  # plain text, never markup


@dataclass(frozen=True)
class AnswerCount:
    """How many gave one answer. `key` tells answers apart, `label` is plain text to show."""

    key: str
    label: str
    count: int


def counted(pairs: Iterable[tuple[str, str]]) -> list[AnswerCount]:
    """From `(key, label)` per answer: the commonest label speaks for its key, ties keep order."""
    labels: dict[str, Counter[str]] = {}
    for key, label in pairs:
        labels.setdefault(key, Counter())[label] += 1
    rows = [
        AnswerCount(key, found.most_common(1)[0][0], found.total()) for key, found in labels.items()
    ]
    return sorted(rows, key=lambda row: -row.count)


@runtime_checkable
class QuestionTypePlugin(Protocol):
    id: str
    version: str

    def label(self) -> str: ...
    def config_schema(self) -> JSON: ...
    def answer_schema(self) -> JSON: ...
    def available_scoring_strategies(self) -> Sequence[str]: ...
    def question_settings(self) -> Sequence[str]: ...  # settings an admin can set per question
    def validate_definition(self, config: JSON, locale: str) -> None: ...
    def validate_submission(self, config: JSON, answer: JSON) -> None: ...
    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON: ...
    def render_admin(self, config: JSON, locales: Sequence[str]) -> str: ...
    def render_public(
        self, public_config: JSON, locale: str, answer: JSON | None = None
    ) -> str: ...
    def describe_definition(
        self, config: JSON, locales: Sequence[str]
    ) -> Sequence[DefinitionRow]: ...
    def public_payload(
        self, config: JSON, locale: str, quiz_settings: JSON | None = None
    ) -> JSON: ...
    def presets(self) -> Sequence[JSON]: ...
    def initial(self, preset: str, locales: Sequence[str]) -> JSON: ...
    def grade(self, config: JSON, answer: JSON) -> ItemGrade: ...
    def file_fields(self, config: JSON) -> Sequence[str]: ...  # answer fields a page uploads
    def needs_grading(self, config: JSON, answer: JSON | None) -> bool: ...  # a person finishes it
    def render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str: ...
    def summarize(
        self, config: JSON, answers: Sequence[JSON], locale: str
    ) -> Sequence[AnswerCount]:
        """What people answered, most frequent first, leaving out what says nothing."""
        ...

    def csv_columns(self, locales: Sequence[str]) -> Sequence[str]: ...
    def from_csv(self, cells: Mapping[str, str], locales: Sequence[str]) -> JSON:
        """Raises `CsvRowError`. An image is `{"asset": None, "source": <the cell>, "alt": …}`."""
        ...

    def to_csv(self, config: JSON, locales: Sequence[str]) -> Mapping[str, str]: ...


@runtime_checkable
class ScoringStrategyPlugin(Protocol):
    id: str
    version: str

    def label(self) -> str: ...
    def supports(self, question_type_id: str) -> bool: ...
    def max_score(self, settings: JSON) -> Decimal: ...
    def evaluate(self, grade: ItemGrade, settings: JSON) -> ScoreBreakdown: ...


@runtime_checkable
class QuizFlowPlugin(Protocol):
    """How a participant moves through the questions. The page enforces it (ADR-0035)."""

    id: str
    version: str

    def modes(self) -> Sequence[str]: ...
    def client_options(self, mode: str, moment: str) -> JSON: ...


OpenAttempt = Literal["none", "running", "expired"]
StartDecision = Literal["new", "resume", "replace", "played", "time_up"]


@runtime_checkable
class ParticipantPolicyPlugin(Protocol):
    """Who may start an attempt and how a nickname and an e-mail are read."""

    id: str
    version: str

    def clean_name(self, raw: str) -> str:
        """Spaces collapsed; `""` when empty. Raises `ValueError` over 40 characters."""
        ...

    def name_key(self, clean: str) -> str: ...
    def valid_email(self, raw: str) -> bool: ...
    def on_start(
        self, rules: Mapping[str, str], *, finished: bool, open_attempt: OpenAttempt
    ) -> StartDecision:
        """`replace` closes the open attempt and starts a new one."""
        ...


@dataclass(frozen=True)
class ScoreEntry:
    key: str  # the participant id, or "a:" + attempt id without one; never shown
    attempt_id: str
    name: str  # "" when none
    score: Decimal
    max_score: Decimal
    submitted_at: datetime
    duration_ms: int | None


@dataclass(frozen=True)
class RankedRow:
    rank: int
    entry: ScoreEntry


@dataclass(frozen=True)
class ScoreSummary:
    count: int
    average: Decimal | None
    median: Decimal | None
    lowest: Decimal | None
    highest: Decimal | None
    bands: tuple[int, ...]  # ten counts, by tenths of the maximum


@runtime_checkable
class ResultViewPlugin(Protocol):
    """Pure rules over submitted results: storage and queries stay in the domain (ADR-0026)."""

    id: str
    version: str

    def pick_official(self, entries: Sequence[ScoreEntry], rule: str) -> ScoreEntry: ...
    def rank(
        self, entries: Sequence[ScoreEntry], rules: Mapping[str, str], seed: str
    ) -> list[RankedRow]: ...
    def summarize(self, scores: Sequence[Decimal], max_score: Decimal) -> ScoreSummary: ...


@dataclass(frozen=True)
class ThresholdRule:
    id: str
    unit: str  # percent, points, correct
    value: Decimal


@dataclass(frozen=True)
class AttemptFigures:
    score: Decimal
    max_score: Decimal  # of this attempt, manual part included
    correct: int
    questions: int  # of this attempt


@runtime_checkable
class RewardPlugin(Protocol):
    """Which threshold rules an attempt reaches, on exact values; storage stays in the domain."""

    id: str
    version: str

    def share(self, rule: ThresholdRule, figures: AttemptFigures) -> Decimal:
        """The threshold as a share 0-1 of this attempt; above 1 when the maximum is 0."""
        ...

    def reached(self, rule: ThresholdRule, figures: AttemptFigures) -> bool: ...
    def qualifies(
        self, rules: Sequence[ThresholdRule], figures: AttemptFigures, mode: str
    ) -> list[str]:
        """Ids of the reached rules; under `highest` only the largest share, ties by order."""
        ...


@runtime_checkable
class DrawingPlugin(Protocol):
    """Snapshot order, fingerprint and secure selection of a draw; records stay in the domain."""

    id: str
    version: str
    algorithm: str

    def order(self, ids: Iterable[str]) -> list[str]:
        """Sorted and unique."""
        ...

    def fingerprint(self, ids: Iterable[str]) -> str: ...
    def select(self, ids: Iterable[str], count: int) -> list[str]: ...


@runtime_checkable
class AuthenticationProvider(Protocol):
    """A Django authentication backend, named by `auth_backend` in the manifest."""

    def authenticate(self, request: Any, username: str, password: str) -> Any | None: ...
    def get_user(self, user_id: Any) -> Any | None: ...


@runtime_checkable
class PersistenceProvider(Protocol):
    id: str

    def database_settings(self) -> JSON: ...
    def healthcheck(self) -> bool: ...


@runtime_checkable
class ThemePlugin(Protocol):
    id: str
    version: str

    def layout_template(self) -> str: ...
    def stylesheet_urls(self) -> Sequence[str]: ...


@runtime_checkable
class MediaStorageProvider(Protocol):
    id: str

    def store_image(self, data: bytes) -> str: ...  # raises ImageRefused; returns the asset id
    def check_image_address(self, url: str) -> None: ...  # raises ImageAddressInvalid
    def fetch_image(self, url: str, *, allow_internal: bool, deadline: float) -> str:
        """Returns the asset id. `deadline` is on `time.monotonic()`. Raises `ImageRefused`."""
        ...

    def check_addresses(
        self,
        urls: Sequence[str],
        *,
        allow_internal: bool,
        per_address: float = 3.0,
        total: float = 10.0,
        max_age: timedelta = timedelta(hours=1),
    ) -> None:
        """Checks those not checked within `max_age`. What does not fit `total` waits."""
        ...

    def address_status(self, urls: Sequence[str]) -> Mapping[str, AddressStatus]: ...
    def store_participant_image(self, data: bytes, *, run_assets: Sequence[str]) -> str:
        """A private photo, within the limit of its run. Raises `ImageRefused`."""
        ...

    def check_participant_image(self, data: bytes) -> None: ...  # as above, storing nothing
    def delete_image(self, asset_id: str) -> None: ...
    def exists(self, asset_id: str) -> bool: ...
    def load(self, asset_id: str) -> StoredImage | None: ...


# Contracts reached through the registry. Providers are wired through settings instead.
class ImportRefused(Exception):
    """The whole file cannot be used. The message is for the admin."""


class ImportJobGone(Exception):
    """Expired, replaced, or another admin's."""


@dataclass(frozen=True)
class CsvRow:
    number: int  # record number in the file, the header being 1
    cells: Mapping[str, str]
    error: str | None = None


@dataclass(frozen=True)
class ParsedFile:
    columns: Sequence[str]
    rows: Sequence[CsvRow]
    files: frozenset[str]  # entry names, empty for a plain CSV


@dataclass(frozen=True)
class ImportJob:
    id: str
    target: Mapping[str, str]  # {"kind": "new_quiz" | "draft" | "bank", "id": str}
    mapping: Mapping[str, str]
    report: Mapping[str, Any] | None


@dataclass(frozen=True)
class ExportedFile:
    extension: str  # "csv" or "zip"
    content_type: str
    data: bytes


@runtime_checkable
class ImporterProvider(Protocol):
    """Files and rows. What a row means is the domain's and the question type's concern."""

    id: str

    def begin(self, admin_id: str, target: Mapping[str, str], chunks: Iterable[bytes]) -> str: ...
    def job(self, job_id: str, admin_id: str) -> ImportJob: ...
    def read(self, job_id: str) -> ParsedFile: ...
    def read_image(self, job_id: str, name: str) -> bytes: ...
    def set_mapping(self, job_id: str, mapping: Mapping[str, str]) -> None: ...
    def claim(self, job_id: str) -> bool: ...  # False when already confirmed
    def finish(self, job_id: str, report: Mapping[str, Any]) -> None: ...
    def guide(self, name: str) -> bytes: ...  # `quiz-sample.csv` or `csv-format.md`


@runtime_checkable
class ExporterProvider(Protocol):
    id: str

    def write(
        self, columns: Sequence[str], rows: Sequence[Mapping[str, str]], files: Mapping[str, bytes]
    ) -> ExportedFile: ...


PORTS: dict[str, type] = {
    "importer": ImporterProvider,
    "exporter": ExporterProvider,
    "question_type": QuestionTypePlugin,
    "scoring_strategy": ScoringStrategyPlugin,
    "quiz_flow": QuizFlowPlugin,
    "participant_policy": ParticipantPolicyPlugin,
    "result_view": ResultViewPlugin,
    "reward": RewardPlugin,
    "drawing": DrawingPlugin,
    "theme": ThemePlugin,
    "media_storage": MediaStorageProvider,
}
