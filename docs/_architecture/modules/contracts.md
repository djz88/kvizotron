# Module: Contracts

Package: `app/contracts/` — versioned public ports and schemas. Code-level Protocols and the plugin
manifest are documented for plugin authors in [../../plugin-api.md](../../plugin-api.md).

## Module kinds

Decision: [ADR-0037](../adr/0037-providers-and-plugins.md).

### Providers (infrastructure)

Selected by the operator; changed by a controlled restart and, if needed, a data migration.

| Contract | Responsibility | Active | v1.0 reference implementation |
|---|---|---|---|
| `AuthenticationProvider` | Admin identity and login | exactly one | [`local-auth`](../providers/auth-local.md) |
| `PersistenceProvider` | Database settings and health check | exactly one | [`sqlite`](../providers/persistence-sqlite.md) |
| `MediaStorageProvider` | Upload, URL, MIME/limits, serving | exactly one | [`local-media`](../providers/media-local.md) |
| `RetentionProvider` | Deletion, anonymisation, jobs | exactly one | [`local-retention`](../providers/retention.md) |
| `ImporterProvider` / `ExporterProvider` | Data formats, validation, mapping | one per format | [CSV](../providers/csv-io.md) |

### Plugins (features)

Several can be active. Admins enable them without a restart and may select them per quiz where the
manifest allows it.

| Contract | Responsibility | v1.0 reference implementation |
|---|---|---|
| `QuestionTypePlugin` | Configuration, admin editor, public rendering, answer validation | [eight base types + image answer](../plugins/question-types.md) |
| `ScoringStrategyPlugin` | Evaluation of supported type, breakdown, max points | [basic and partial](../plugins/scoring.md) |
| `QuizFlowPlugin` | Navigation, back-navigation control, progress | [all-at-once / step](../plugins/quiz-flow.md) |
| `ParticipantPolicyPlugin` | Attempts, cookie identity, repetition rules | [browser-anonymous](../plugins/participants.md) |
| `ResultViewPlugin` | Result projections, scoreboard, statistics and dashboards; storage stays in the domain | [local-results](../plugins/results-scoreboard.md) |
| `RewardPlugin` | Performance thresholds and entitlement records | [threshold-rewards](../plugins/rewards.md) |
| `DrawingPlugin` | Eligible selection, draw, audit | [manual-draw](../plugins/drawing.md) |
| `ThemePlugin` | Templates, components, branding tokens | [default-theme](../plugins/theme-default.md) |

`QuestionTypePlugin` renders its editor (`render_admin`) and reads the submitted form back
(`parse_admin`). Public inputs are named `<id>:<field>`, with `id` added to `public_config` by the domain.
Answers arrive as form strings. `ThemePlugin` names its layout template and stylesheets, and a theme
template with the name of a page template replaces that page.

One package may implement several contracts. Contracts do not imply a separate process or a separate
database.

## Contract invariants

1. `public_payload()` never contains the answer key, scoring rules that allow deriving the solution,
   or private data.
2. `ScoringStrategy.evaluate()` is a pure server-side operation over the immutable definition and the
   supplied answer, with no trust in client-provided scores.
3. Rendering may use declared server templates and the module's static assets. A module changes other
   modules' tables only through their public services; this is checked in code review, because modules
   are trusted and run in-process.
4. Persistence ensures atomic transactions and each module owns its migrations; replacing the provider
   requires a dedicated data migration.
5. Result, reward and drawing modules **MUST** use the same run/revision/attempt identifiers and the
   same eligibility policy.
6. Module runtime configuration is validated by its declared schema (JSON Schema / Pydantic) and is
   snapshotted into the revision or run if it affects evaluation.
7. The module API uses contract tests; changes to public contracts respect version compatibility.

## Versioning

- Contract version (`api_compatibility`, kernel side) and module data version
  (`config_schema_version`) are distinct. See [ADR-0021](../adr/0021-plugin-manifest-and-versioning.md).
- Every module **MUST** pass the shared contract test suite in `tests/contracts/`
  ([AC-01](../acceptance-criteria.md), [AC-02](../acceptance-criteria.md)).
