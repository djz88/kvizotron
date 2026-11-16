"""Module manifest. Read while settings load, so it must not import Django."""

from typing import Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.contracts import ADVANCED, BASIC, SETTING_GROUPS

Scope = Literal["global", "quiz", "question"]
ALL_SCOPES: list[Scope] = ["global", "quiz", "question"]


class SettingDeclaration(BaseModel):
    """A setting a module owns. Inherited along the whole chain unless a reason says otherwise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    choices: list[str]
    default: str
    scopes: list[Scope] = ALL_SCOPES
    scope_reason: str | None = None
    label: str  # msgids in the module's own catalogue
    value_labels: dict[str, str]
    help: str | None = None
    group: str = "technical"
    level: str = ADVANCED

    @model_validator(mode="after")
    def _consistent(self) -> SettingDeclaration:
        if self.group not in SETTING_GROUPS:
            raise ValueError(f"{self.key}: unknown group {self.group}")
        if self.level not in (BASIC, ADVANCED):
            raise ValueError(f"{self.key}: unknown level {self.level}")
        if self.default not in self.choices:
            raise ValueError(f"{self.key}: the default is not among the choices")
        if set(self.value_labels) != set(self.choices):
            raise ValueError(f"{self.key}: each choice needs one label")
        if set(self.scopes) != set(ALL_SCOPES) and not self.scope_reason:
            raise ValueError(f"{self.key}: a narrower scope needs a reason (ADR-0042)")
        return self


class SettingRequirement(BaseModel):
    """A value a module cannot work with, and the one it offers instead (ADR-0034)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    refuse: list[str]
    use: str
    reason: str  # a msgid in the module's own catalogue

    @model_validator(mode="after")
    def _use_is_allowed(self) -> SettingRequirement:
        if self.use in self.refuse:
            raise ValueError(f"{self.use} is both offered and refused")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["plugin", "provider"]
    name: str | None = None  # msgid in the module's own catalogue; without it the id is shown
    description: str | None = None  # msgid, one line on what the module does
    always_on: bool = False  # the application asks for it by name, so it cannot be disabled
    version: str
    app: str
    api_compatibility: str
    urls: str | None = None
    auth_backend: str | None = None  # dotted class path; required when providing auth
    persistence: str | None = None  # "module:Class"; required when providing persistence
    provides: list[str] = []
    requires: list[str] = []
    optional: list[str] = []
    activation_scope: list[Literal["global", "quiz"]] = ["global"]
    config_schema_version: int = 1
    settings: list[SettingDeclaration]  # required: a module with none states an empty list
    settings_requirements: dict[str, SettingRequirement] = {}
    assets: dict[str, str] = {}

    @field_validator("api_compatibility")
    @classmethod
    def _valid_specifier(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"invalid version specifier: {value}") from exc
        return value
