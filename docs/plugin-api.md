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
settings:                     # required; a module with none states []
  - key: my_setting
    choices: [a, b]
    default: a
    scopes: [global, quiz, question]   # the default; narrower needs scope_reason
    label: Text in the module's catalogue
    value_labels: {a: Text, b: Text}
settings_requirements:        # optional; see modules/kernel.md (FR-46)
  reveal_moment: {refuse: [after_each], use: at_end, reason: Text in the module's catalogue}
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
- `settings` lists settings the module owns. They are inherited global → quiz → question unless `scopes` is narrower, which needs `scope_reason`. Whoever adds a setting decides where it fits ([ADR-0042](_architecture/adr/0042-settings-inherited-and-declared.md)).
- `settings_requirements` lists settings the module needs: per key, the values it refuses, the value `Use` applies, not among those refused, and a reason. Declarative values only; an unknown key or value stops the start. Modules whose requirements contradict each other block a quiz using both.
- `api_compatibility` (contract version) and `config_schema_version` (plugin's own data version) are
  different things.

How the kernel enforces compatibility, activation and replacement:
[modules/kernel.md](_architecture/modules/kernel.md#module-installation-and-activation).

## Contracts (illustrative Python Protocols)

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence

JSON = Mapping[str, Any]

@dataclass(frozen=True)
class ItemGrade:
    right: int
    wrong: int
    total: int

@dataclass(frozen=True)
class ScoreBreakdown:
    earned_points: Decimal
    max_points: Decimal
    correct_count: int | None
    details: JSON
    # max_points includes any manual part; earned_points is the automatic part only.

class QuestionTypePlugin(Protocol):
    id: str
    version: str
    def label(self) -> str: ...
    def config_schema(self) -> JSON: ...
    def answer_schema(self) -> JSON: ...
    def available_scoring_strategies(self) -> Sequence[str]: ...
    def validate_definition(self, config: JSON, locale: str) -> None: ...
    def validate_submission(self, config: JSON, answer: JSON) -> None: ...
    def parse_admin(self, form: Mapping[str, Sequence[str]],
                    locales: Sequence[str]) -> JSON: ...   # raises ValueError or AdminFormError
    def render_admin(self, config: JSON, locales: Sequence[str]) -> str: ...
    def render_public(self, public_config: JSON, locale: str,
                      answer: JSON | None = None) -> str: ...
    def describe_definition(self, config: JSON,
                            locales: Sequence[str]) -> Sequence[DefinitionRow]: ...
    def question_settings(self) -> Sequence[str]: ...  # settings set per question of this type
    def public_payload(self, config: JSON, locale: str,
                       quiz_settings: JSON | None = None) -> JSON: ...
    # quiz_settings: quiz-level values a type may need, passed by the API; a plugin reads no settings.
    # quiz_settings may hold `shuffle_seed`: a type with options orders them from it, the same way every time.
    def presets(self) -> Sequence[JSON]: ...    # [{"id": ..., "label": ...}] extra items of the add menu
    def initial(self, preset: str, locales: Sequence[str]) -> JSON: ...  # prefilled definition, or {}
    def grade(self, config: JSON, answer: JSON) -> ItemGrade: ...  # after validate_submission

class ScoringStrategyPlugin(Protocol):
    id: str
    version: str
    def label(self) -> str: ...
    def supports(self, question_type_id: str) -> bool: ...
    def max_score(self, settings: JSON) -> Decimal: ...
    def evaluate(self, grade: ItemGrade, settings: JSON) -> ScoreBreakdown: ...

class MediaStorageProvider(Protocol):
    id: str
    def check_image_address(self, url: str) -> None: ...  # raises ImageAddressInvalid
    def fetch_image(self, url: str, *, allow_internal: bool, deadline: float) -> str: ...
    def check_addresses(self, urls, *, allow_internal, per_address=3.0, total=10.0,
                        max_age=timedelta(hours=1)) -> None: ...
    def address_status(self, urls) -> Mapping[str, AddressStatus]: ...
    def store_image(self, data: bytes) -> str: ...  # raises ImageRefused; returns the asset id
    def exists(self, asset_id: str) -> bool: ...
    def load(self, asset_id: str) -> StoredImage | None: ...  # StoredImage(path, mime_type)

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

- `label()` returns the readable name of the type in the active language, for the question list and the add menu.
- `public_config` passed to `render_public` also contains `id`. Name inputs `<id>:<field>`, for example
  `name="{{ q.id }}:option"`; the answer then arrives as `{"option": "..."}`, with string values.
- Render through a Jinja2 template, which escapes admin-entered text.
- `render_public` shows `answer` as already filled in when it is given, in the shape `validate_submission`
  accepts. A participant who moves to a new revision keeps answers this way.
- `describe_definition` returns plain-text `DefinitionRow(key, label, locale, value)` rows; `locales[0]` is the
  default language. `key` must stay the same across revisions of a question, and a change in any definition
  field must change the rows, because the overview before publication is built from them, including correct answers.
- `parse_admin` raises `AdminFormError(message, config)` when the form cannot be used, so the editor keeps
  what was typed. Drafts may be incomplete; `validate_definition` runs per language at publication.

- `csv_columns`, `from_csv` and `to_csv` read and write the type's columns of an import file ([ADR-0032](_architecture/adr/0032-csv-schema.md)). `from_csv` raises `CsvRowError(column, message)` and generates ids; an image is `{"asset": None, "source": <the cell>, "alt": {...}}`, and the importer decides whether the cell is an address or a file name. `to_csv` writes `image["source"]`.

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

## Showing the solution

`render_solution(config, locale, answer) -> str` draws the correct answer for one locale, with the participant's answer beside it; `answer` may be `None`. Only the reveal path calls it, and `public_payload()` stays free of the key. `config` is the stored definition with `url` added to each image. Escape through a template, as in `render_public`.

## Quiz flow

`QuizFlowPlugin` (port `quiz_flow`) names the navigation modes and tells the page what to offer:

```python
def modes(self) -> Sequence[str]: ...
def client_options(self, mode: str, moment: str) -> JSON: ...  # {"step": bool, "back": bool, "check": bool}
```

The page enforces the result; it is not a security boundary (ADR-0035). Without such a module every quiz is one page, which works without JavaScript.
