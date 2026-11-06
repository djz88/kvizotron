"""Public contracts between the kernel and modules. Must not import Django."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

CONTRACT_VERSION = "1.0"

# Infrastructure with exactly one active provider per process (ADR-0037).
EXACTLY_ONE: frozenset[str] = frozenset({"auth", "persistence", "media_storage", "retention"})

# Capabilities that must be present to start.
REQUIRED_CAPABILITIES: frozenset[str] = frozenset({"auth", "persistence"})


JSON = Mapping[str, Any]


class AdminFormError(ValueError):
    """An editor form cannot be read; `config` is what could be, so the form keeps the input."""

    def __init__(self, message: str, config: JSON) -> None:
        super().__init__(message)
        self.config = config


@dataclass(frozen=True)
class ScoreBreakdown:
    earned_points: float  # the automatic part only
    max_points: float  # includes any manual part
    correct_count: int | None
    details: JSON


@runtime_checkable
class QuestionTypePlugin(Protocol):
    id: str
    version: str

    def config_schema(self) -> JSON: ...
    def answer_schema(self) -> JSON: ...
    def available_scoring_strategies(self) -> Sequence[str]: ...
    def validate_definition(self, config: JSON, locale: str) -> None: ...
    def validate_submission(self, config: JSON, answer: JSON) -> None: ...
    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON: ...
    def render_admin(self, config: JSON, locales: Sequence[str]) -> str: ...
    def render_public(self, public_config: JSON, locale: str) -> str: ...
    def public_payload(self, config: JSON, locale: str) -> JSON: ...


@runtime_checkable
class ScoringStrategyPlugin(Protocol):
    id: str
    version: str

    def supports(self, question_type_id: str) -> bool: ...
    def max_score(self, definition: JSON, settings: JSON) -> float: ...
    def evaluate(self, definition: JSON, answer: JSON, settings: JSON) -> ScoreBreakdown: ...


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


# Contracts reached through the registry. Providers are wired through settings instead.
PORTS: dict[str, type] = {
    "question_type": QuestionTypePlugin,
    "scoring_strategy": ScoringStrategyPlugin,
    "theme": ThemePlugin,
}
