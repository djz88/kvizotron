# Plugin API

Audience: developers writing Kvízotron modules, that is plugins and providers
([ADR-0037](_architecture/adr/0037-providers-and-plugins.md)). Architectural rules: [_architecture/modules/kernel.md](_architecture/modules/kernel.md),
[_architecture/modules/contracts.md](_architecture/modules/contracts.md). Decisions:
[ADR-0004](_architecture/adr/0004-entry-points-typed-registry-pydantic.md), [ADR-0021](_architecture/adr/0021-plugin-manifest-and-versioning.md).

## Packaging

A module is a Python package containing a Django app, with its own models, migrations, Jinja2 templates
(`jinja2/<module>/`), static files and routes. It is announced through the `kvizotron.modules` entry
point group, whose target is the manifest.

Rule: importing the manifest **MUST NOT** import Django, because manifests are read while Django's
settings load. Register ports in `AppConfig.ready()`.

## Manifest

Every module declares at least:

```yaml
id: question.video
kind: plugin                  # plugin or provider
version: 1.0.0
app: kvz_video.apps.VideoConfig   # Django AppConfig
urls: kvz_video.urls          # optional; mounted under the module's own prefix
api_compatibility: '>=1.0,<2.0'
provides: [question_type]
requires: [media_storage]
optional: []
activation_scope: [global, quiz]
config_schema_version: 1
settings_requirements:        # optional; see modules/kernel.md (FR-46)
  scoreboard.visibility: {allowed: [HIDDEN, AFTER_GRADING]}
  retention.profile: {allowed: [ANSWERS, DETAILED]}
assets:
  admin: assets/admin.js
  public: assets/public.js
```

Field meaning:

- `id` is namespaced and stable.
- `kind` selects the activation rules ([contracts](_architecture/modules/contracts.md#module-kinds)).
  When several providers of an exactly-one capability are installed, the operator chooses with
  `KVZ_PROVIDER_<CAPABILITY>`, for example `KVZ_PROVIDER_AUTH=auth.local`.
- `urls` are mounted under `/m/<module id>/`.
- `persistence` (`module:Class`) is required for a provider of `persistence`. The module and class are
  loaded while settings load, so they **MUST NOT** import Django at module level.
- `auth_backend` (dotted class path) is required for a provider of `auth`.
- `settings_requirements` lists settings the module needs; names shown are illustrative.
- `api_compatibility` (contract version) and `config_schema_version` (plugin's own data version) are
  different things.

How the kernel enforces compatibility, activation and replacement:
[modules/kernel.md](_architecture/modules/kernel.md#module-installation-and-activation).

## Contracts (illustrative Python Protocols)

```python
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

JSON = Mapping[str, Any]

@dataclass(frozen=True)
class ScoreBreakdown:
    earned_points: float
    max_points: float
    correct_count: int | None
    details: JSON
    # max_points includes any manual part; earned_points is the automatic part only.

class QuestionTypePlugin(Protocol):
    id: str
    version: str
    def config_schema(self) -> JSON: ...
    def answer_schema(self) -> JSON: ...
    def available_scoring_strategies(self) -> Sequence[str]: ...
    def validate_definition(self, config: JSON, locale: str) -> None: ...
    def validate_submission(self, config: JSON, answer: JSON) -> None: ...
    def parse_admin(self, form: Mapping[str, Sequence[str]],
                    locales: Sequence[str]) -> JSON: ...   # raises ValueError or AdminFormError
    def render_admin(self, config: JSON, locales: Sequence[str]) -> str: ...
    def render_public(self, public_config: JSON, locale: str) -> str: ...
    def public_payload(self, config: JSON, locale: str) -> JSON: ...

class ScoringStrategyPlugin(Protocol):
    id: str
    version: str
    def supports(self, question_type_id: str) -> bool: ...
    def max_score(self, definition: JSON, settings: JSON) -> float: ...
    def evaluate(self, definition: JSON, answer: JSON,
                 settings: JSON) -> ScoreBreakdown: ...

class AuthenticationProvider(Protocol):
    # A Django authentication backend, named by `auth_backend` in the manifest.
    # Users are the kernel's user model; sessions are Django sessions.
    def authenticate(self, request, username: str, password: str) -> Any | None: ...
    def get_user(self, user_id: Any) -> Any | None: ...

class PersistenceProvider(Protocol):
    id: str
    # Read while settings load, so this method must not import Django.
    def database_settings(self) -> JSON: ...      # one Django DATABASES entry
    def healthcheck(self) -> bool: ...

class ThemePlugin(Protocol):
    id: str
    version: str
    def layout_template(self) -> str: ...
    def stylesheet_urls(self) -> Sequence[str]: ...

class DrawingPlugin(Protocol):
    id: str
    def preview_eligible(self, run_id: str, rules: JSON) -> Sequence[str]: ...
    def draw(self, run_id: str, rules: JSON, admin_id: str) -> JSON: ...
```

Rules for question types:

- `public_config` passed to `render_public` also contains `id`. Name inputs `<id>:<field>`, for example
  `name="{{ q.id }}:option"`; the answer then arrives as `{"option": "..."}`, with string values.
- Render through a Jinja2 template, which escapes admin-entered text.
- `parse_admin` raises `AdminFormError(message, config)` when the form cannot be used, so the editor keeps
  what was typed. Drafts may be incomplete; `validate_definition` runs per language at publication.

Translations: put `locale/<lang>/LC_MESSAGES/django.{po,mo}` in the module and use `_()` in templates.
Add the module to `ROOTS` in `tools/messages.py` to include it in `make messages`.

The remaining contracts (`QuizFlowPlugin`, `ParticipantPolicyPlugin`, `ResultViewPlugin`,
`RewardPlugin`, `ImporterProvider`/`ExporterProvider`, `MediaStorageProvider`,
`RetentionProvider`) are defined in Stage A–D as they are implemented.

## Invariants every module must respect

See [contract invariants](_architecture/modules/contracts.md#contract-invariants) (1–7).

## Testing

- Every module must pass the shared suite in `tests/contracts/`.
- Changes to public contracts respect version compatibility.
- Acceptance: adding a sample new question type to a deployment requires no kernel code change
  ([AC-01](_architecture/acceptance-criteria.md)).
