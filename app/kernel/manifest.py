"""Module manifest. Read while settings load, so it must not import Django."""

from typing import Any, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, field_validator


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["plugin", "provider"]
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
    settings_requirements: dict[str, Any] = {}
    assets: dict[str, str] = {}

    @field_validator("api_compatibility")
    @classmethod
    def _valid_specifier(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"invalid version specifier: {value}") from exc
        return value
