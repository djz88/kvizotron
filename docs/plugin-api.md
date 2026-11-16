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
    group: playing                      # settings page group; technical by default (ADR-0052)
    level: basic                        # shown in "Basic"; advanced by default
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
- `settings` lists settings the module owns. They are inherited global → quiz → question unless `scopes` is narrower, which needs `scope_reason`. Whoever adds a setting decides where it fits ([ADR-0042](_architecture/adr/0042-settings-inherited-and-declared.md)). `group` (`playing`, `answers`, `participants`, `scoreboard`, `rewards`, `data`, `look`, `technical`) and `level` (`basic`, `advanced`) only place it on the admin pages ([ADR-0052](_architecture/adr/0052-setting-groups-levels-and-step-default.md)).
- `name` and `description` are optional texts in the module's catalogue, shown on the Modules page; without a name the page shows the id. `always_on: true` marks a module the application asks for by name, which can then never be disabled.
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
    def private_assets_older_than(self, cutoff: datetime) -> Sequence[str]: ...  # participants' photos

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

@dataclass(frozen=True)
class BrandColours:
    main: str    # "#rrggbb"
    accent: str

@dataclass(frozen=True)
class DerivedPalette:
    light: Mapping[str, str]  # every name in PALETTE_TOKENS -> "#rrggbb"
    dark: Mapping[str, str]
    adjusted: bool            # main or accent changed to reach WCAG AA
    main: str                 # the colours actually used
    accent: str

class ThemePlugin(Protocol):
    id: str
    version: str
    def layout_template(self) -> str: ...
    def stylesheet_urls(self) -> Sequence[str]: ...
    def palettes(self) -> Sequence[str]: ...          # preset ids, without CUSTOM_PALETTE
    def branding_fields(self) -> frozenset[str]: ...  # a subset of BRANDING_FIELDS
    def derive_palette(self, colours: BrandColours) -> DerivedPalette: ...

class RewardPlugin(Protocol):
    id: str
    version: str
    def share(self, rule: ThresholdRule, figures: AttemptFigures) -> Decimal: ...
    def reached(self, rule: ThresholdRule, figures: AttemptFigures) -> bool: ...
    def qualifies(self, rules: Sequence[ThresholdRule], figures: AttemptFigures,
                  mode: str) -> list[str]: ...  # "highest" or "all"

class DrawingPlugin(Protocol):
    id: str
    version: str
    algorithm: str  # stored with each draw record
    def order(self, ids: Iterable[str]) -> list[str]: ...  # sorted and unique
    def fingerprint(self, ids: Iterable[str]) -> str: ...
    def select(self, ids: Iterable[str], count: int) -> list[str]: ...  # CSPRNG
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

The remaining contracts (`QuizFlowPlugin`, `ParticipantPolicyPlugin`, `ResultViewPlugin` (below),
`ImporterProvider`/`ExporterProvider`, `MediaStorageProvider`) are defined in Stage A–D as they are
implemented. `RetentionProvider` is under [Retention](#retention).

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
def client_options(self, mode: str, moment: str) -> JSON: ...  # {"step", "back", "check", "pages": bool}
```

The page enforces the result; it is not a security boundary (ADR-0035). Without such a module every quiz is one page, which works without JavaScript.

## Quiz types

`QuizTypePlugin` (port `quiz_type`) is a named bundle of quiz settings ([ADR-0062](_architecture/adr/0062-quiz-type-port.md)). It holds only the definition; applying it to a quiz is the domain's.

```python
id: str
version: str
order: int          # position in lists, ascending
resets_all: bool    # True only for a type that removes every quiz override
def label(self) -> str: ...
def description(self) -> str: ...
def values(self) -> Mapping[str, str]: ...  # setting key -> value; {} when resets_all
```

Every key must be a setting a quiz may override and every value one of its choices; the values must pass the clash rules of the settings forms (`app/domain/setting_rules.py`), such as navigation against reveal and the data profile against the answers visibility. The shared suite `tests/contracts/quiz_type.py` checks it. The module `quiz_types.basic` registers seven types and declares no settings ([plugins/quiz-types.md](_architecture/plugins/quiz-types.md)).

## Participant policy

`ParticipantPolicyPlugin` (port `participant_policy`) holds the pure rules about a participant. It reads nothing from the request or the database; the API hands it the facts.

```python
def clean_name(self, raw: str) -> str: ...  # spaces collapsed; "" when empty; ValueError over 40
def name_key(self, clean: str) -> str: ...  # case-folded, for comparing nicknames
def valid_email(self, raw: str) -> bool: ...
def on_start(self, rules: Mapping[str, str], *, finished: bool, used: int, passed: bool, open_attempt: OpenAttempt) -> StartDecision: ...
```

`rules` holds the resolved `repeat_attempts`, `unfinished_attempt`, `max_attempts` and `after_pass`. `used` is the participant's started attempts other than the open one (submitted, waiting for grading, abandoned, or in progress; a switched one never counts), `passed` says the kept score reached the pass mark (contract 1.1: `used` and `passed` are new). The domain always passes both, so a participant policy written for 1.0 must add them to its `on_start` signature before it runs on 1.1, although its `api_compatibility` (`>=1.0,<2.0`) still accepts the kernel. `open_attempt` is `none`, `running` or `expired`. The result is `new`, `resume`, `replace` (close the open attempt, then start a new one), `played` or `time_up`.

| repeat | unfinished | finished | open | result |
|---|---|---|---|---|
| allow | any | any | any | new |
| forbid | any | yes | any | played |
| forbid | continue | no | running | resume |
| forbid | continue | no | expired | time_up |
| forbid | used | no | running or expired | played |
| forbid | submitted | no | running or expired | replace |
| forbid | any | no | none | new |

Under `allow` with `max_attempts` N (0 is no limit), checked in this order. "after pass" is `after_pass=stop` with `passed`; it ends the test whatever N is.

| after pass | open | unfinished | used vs N | result |
|---|---|---|---|---|
| yes | any | any | any | played |
| no | none | - | N = 0 or used < N | new |
| no | none | - | used >= N | played |
| no | running | continue | - | resume |
| no | running | used or submitted | used + 1 < N | replace |
| no | running | used or submitted | used + 1 >= N | played |
| no | expired | any | used + 1 < N | replace |
| no | expired | any | used + 1 >= N | played |

Under a limit an expired attempt counts as used and never locks the participant out with `time_up`; `time_up` stays only for `forbid`.

With N = 0 and no pass that ends the test, `allow` is `new` as before. The module also declares the settings `repeat_attempts`, `unfinished_attempt`, `max_attempts`, `after_pass`, `ask_name`, `ask_email`, `ask_when` and `duplicate_names` (global and quiz).

## Result view

`ResultViewPlugin` (port `result_view`) holds the pure rules of a scoreboard and of score summaries ([ADR-0026](_architecture/adr/0026-scoreboard-tie-break-rule.md), [ADR-0051](_architecture/adr/0051-scoreboard-participants-and-official-attempt.md)). The domain reads attempts, decides visibility and names, and hands it `ScoreEntry` values.

```python
def pick_official(self, entries: Sequence[ScoreEntry], rule: str) -> ScoreEntry: ...  # "best", "first", "last" or "average" (ADR-0063; an unknown rule raises ValueError)
def rank(self, entries: Sequence[ScoreEntry], rules: Mapping[str, str], seed: str) -> list[RankedRow]: ...
def summarize(self, scores: Sequence[Decimal], max_score: Decimal) -> ScoreSummary: ...
```

`rank` orders by score, then `scoreboard_second_sort` (`submitted` or `duration`), then `tie_break_policy`: `shared` gives equal places, `earlier` the earlier submission, `random` a hash of the run's `seed` and the entry key. `summarize` gives count, average, median, extremes and ten bands. The module `results.local` also declares the twelve scoreboard settings (global and quiz).

## Rewards and draw

`RewardPlugin` (port `reward`) and `DrawingPlugin` (port `drawing`) hold only pure rules ([ADR-0053](_architecture/adr/0053-rewards-tiers-alternates-and-draw-history.md)). The domain hands the reward plugin `ThresholdRule(id, unit, value)` and `AttemptFigures(score, max_score, correct, questions)` of the official attempt; `qualifies` returns the ids of the reached threshold rules, under `highest` only the one with the largest share. The drawing plugin gets participant ids and never sees names. The module `rewards.threshold` also declares `reward_source`, `reward_thresholds` and `winner_contact` (global and quiz); `drawings.manual` declares no settings.

## Results export and table sinks

`ResultsExporterProvider` (port `results_exporter`) keeps background export jobs and their files; `TableSinkProvider` (port `table_sink`) is the Google Sheets contract (FR-44) and has no implementation in v1.0 ([ADR-0055](_architecture/adr/0055-results-export-background-job-and-csv-dialect.md), [providers/csv-io.md](_architecture/providers/csv-io.md)). Both take tables the domain builds:

```python
@dataclass(frozen=True)
class ExportTable:
    name: str
    columns: Sequence[str]  # keys of each row
    headers: Sequence[str]  # translated labels, same length
    rows: Sequence[Mapping[str, str]]
    numeric: frozenset[str] = frozenset()  # columns whose numbers skip formula protection

class TableSinkProvider(Protocol):
    id: str
    def send(self, title: str, tables: Sequence[ExportTable]) -> str: ...  # where it went

class ResultsExporterProvider(Protocol):
    id: str
    def create(self, admin_id: str, choices: Mapping[str, Any]) -> str: ...
    def job(self, job_id: str, admin_id: str) -> ExportJobView: ...  # raises ExportJobGone
    def jobs(self, admin_id: str) -> Sequence[ExportJobView]: ...  # unexpired, newest first
    def claim_next(self) -> ExportJobView | None: ...  # the job it set running, with choices
    def write(self, job_id: str, tables: Sequence[ExportTable],
              photos: Mapping[str, str], bundle: bool) -> None: ...  # photos: name in ZIP -> path
    def fail(self, job_id: str, code: str) -> None: ...
    def restart(self, job_id: str, admin_id: str) -> str: ...  # only interrupted or failed
    def path(self, job_id: str, admin_id: str, name: str) -> str: ...  # raises ExportJobGone
    def delete_for_runs(self, quiz_id: str, run_ids: Sequence[str]) -> None: ...
```

`delete_for_runs` covers a job naming one of the runs and a job of all runs of that quiz. A queued or running job ends as failed with error `run_data_deleted`, so a file cannot appear after the deletion; any other job goes with its files. It is safe to repeat: a job already stopped this way stays, so its admin can restart it. It raises when files cannot be removed and keeps that job's row, so the caller can try again.

A sink must not change the tables it gets. The shared suite is `tests/contracts/table_sink.py` (`TableSinkSuite(sink).run()`).

## Retention

`RetentionProvider` (port `retention`, [providers/retention.md](_architecture/providers/retention.md)) keeps the trail of deletions. What is due and what is deleted is the domain's concern.

```python
@dataclass(frozen=True)
class RetentionRecord:
    id: str
    run_id: str
    trigger: str  # "automatic" | "manual" | "erasure"
    admin_id: str | None  # None when automatic
    policy: str
    cutoff_at: datetime | None
    executed_at: datetime
    counts: Mapping[str, int]  # rows and files deleted, by kind
    has_fingerprint: bool  # the fingerprint itself is never handed out

class RetentionProvider(Protocol):
    id: str
    def record(self, run_id: str, *, trigger: str, admin_id: str | None, policy: str,
               cutoff_at: datetime | None, counts: Mapping[str, int],
               fingerprint: str | None = None) -> str: ...
    def history(self, limit: int = 200, offset: int = 0) -> Sequence[RetentionRecord]: ...  # newest first
    def for_run(self, run_id: str) -> Sequence[RetentionRecord]: ...  # newest first
    def erased(self, fingerprint: str) -> Sequence[RetentionRecord]: ...  # newest first
```

A record holds no personal value. The shared suite is `tests/contracts/retention.py` (`RetentionSuite(provider).run()`).
