# Logical Data Model

The model is **logical**; Django models may adjust physical SQL tables and JSON
structures. Fields shown deliberately expose keys and invariants. Physical schema is owned by
[providers/persistence-sqlite.md](providers/persistence-sqlite.md) and each module's migrations.
ID format: UUIDv7 ([ADR-0023](adr/0023-id-format.md)).

## Entities

| Entity / table | Key fields and meaning | Owner |
|---|---|---|
| `admin_user` | `id`, `login UNIQUE`, `password`, `is_active`, `last_login`, `created_at` | kernel (shared by auth providers) |
| `django_session` | Django database sessions | Django |
| `plugin_installation` | `plugin_id`, `version`, `manifest_json`, `enabled`, `status` | kernel |
| `plugin_configuration` | `plugin_id`, `scope=global/quiz/run`, `scope_id`, `settings_json`, `schema_version` | kernel |
| `quiz` | `id`, `slug UNIQUE`, `title` (locale → text), `description` (locale → text), `default_locale`, `supported_locales`, `featured`, `archived_at` | domain |
| `quiz_revision` | `id`, `quiz_id`, `revision_no`, `status`, `snapshot_json`, `plugins_json`, `max_score`, `checksum`, `published_at` | domain |
| `app_setting` | `key`, `value_json`, `quiz_id` nullable (global when empty); one value per key and scope; a question value lives in the question ([ADR-0042](adr/0042-settings-inherited-and-declared.md)) | domain |
| `question_bank` | `id`, `name`, `created_by`, `created_at` | domain |
| `bank_question` | `id`, `bank_id`, `question_json` (the shape of a quiz question in a draft), `tags`, `created_at` | domain |
| `media_asset` | `id`, `kind`, `storage_key`, `mime_type`, `size`, `sha256`, `created_at`, `private` (a participant's photo, never on `/media/`) | media-local |
| `media_address_check` | `address`, `ok`, `checked_at`; the last check of an address some quiz loads an image from. An address itself lives in the question definition as `source` ([ADR-0043](adr/0043-external-images.md)) | media-local |
| `quiz_run` | `id`, `quiz_id`, `run_no`, `current_revision_id`, `status`, `starts_at`, `deadline_at`, `attempt_limit_sec`, `config_json`, `retention_json` | domain |
| `run_revision` | `id`, `run_id`, `revision_id`, `active_from`, `active_to` (empty on the current row), `max_score`, `switch_mode` (`finish`/`switch`) | domain |
| `participant` | `id`, `run_id`, `anonymous_key_hash`, `display_name`, `email_nullable`, `created_at`, `redacted_at` | participants |
| `attempt` | `id`, `run_id`, `revision_id`, `participant_id`, `started_at`, `submitted_at`, `status` (incl. `SWITCHED`, `PENDING_GRADING`), `replaced_by`, `score`, `max_score`, `duration_ms`, `submission_key`, `selection_json` (questions given, and a seed for option order), `auto_score` (what the server gave; `score` adds what admins decide), `settings_json` (navigation, reveal and `store_answers` frozen at start) | domain |
| `attempt_question` | `id`, `attempt_id`, `question_snapshot_id`, `sequence_no`, `option_order_json` (proof of the concrete selection) | domain |
| `attempt_answer` | `id`, `attempt_id`, `question_id`, `answer_json`, `auto_points`, `manual_max`, `manual_points`, `graded_by`, `graded_at`, `asset_id`, `removed`, `approved`; unique per attempt and question; only what `store_answers` keeps and what a person grades ([ADR-0046](adr/0046-stored-answers-and-who-sees-them.md)) | domain |
| `hidden_answer_value` | `id`, `run_id`, `question_id`, `value_key` (a hash of the value), `hidden_by`, `created_at`; what an admin took off a walkthrough | domain |
| `scoreboard_policy` | `run_id`, `revision_mode`, `visibility`, `public_columns_json`, `sort_json`, `attempt_selection_policy`, `tie_break_policy`, `tie_break_seed` | results |
| `reward_rule` | `id`, `run_id`, `type`, `threshold_unit`, `threshold_value`, `description_json`, `fulfilment_json` | rewards |
| `reward_entitlement` | `id`, `run_id`, `participant_id`, `rule_id`, `attempt_id`, `status`, `created_at` | rewards |
| `draw` | `id`, `run_id`, `rule_id`, `admin_id`, `created_at`, `eligible_count`, `eligible_set_hash`, `algorithm`, `audit_json` | drawing |
| `draw_entry` / `draw_winner` | `draw_id`, `participant_id` or pseudonymised key, `selected`, `rank` | drawing |
| `audit_event` | `id`, `actor_type`, `actor_id`, `action`, `entity_type`, `entity_id`, `created_at`, `details_json` | kernel |
| `import_job` | `id`, `admin_id`, `status`, `target_json`, `mapping_json`, `report_json`, `created_at`, `expires_at` | csv-io |
| `export_job` | `id`, `admin_id`, `kind`, `status`, `report_json`, `created_at`, `expires_at` (D2) | csv-io |
| `test_link` | `id`, `run_id`, `token`, `expires_at`, `created_by`, `created_at`; the run has kind `test`, and its revision may have status `TEST_COPY` | domain |
| `retention_job` | `id`, `run_id`, `policy`, `cutoff_at`, `executed_at`, `counts_json` | retention |
| `branding_configuration` | `scope`, `scope_id`, `theme_id`, `tokens_json`, `assets_json` | theme |

The "Owner" column is a documentation proposal mapping tables to modules.

## Relationships (core)

```
 quiz 1───N quiz_revision          quiz 1───N quiz_run 1───N run_revision N───1 quiz_revision
                │                                │
                │ 1                              ├──N participant 1───N attempt
                └────────────N attempt N─────────┘                       │
                                                         attempt 1───N attempt_answer
 quiz_run 1───N reward_rule 1───N reward_entitlement N───1 participant
 quiz_run 1───N draw 1───N draw_entry
```

## Important indexes and constraints

- Unique: `quiz.slug`, `quiz_revision(quiz_id, revision_no)`, `quiz_run(quiz_id, run_no)`,
  `attempt.submission_key` (idempotence).
- Indexes: `(run_id, submitted_at)`, `(run_id, participant_id)`, `(run_id, score)`, `(run_id, revision_id)`.
- If duplicate nicknames are forbidden, normalised `display_name` is checked within the run in an
  atomic transaction (not only in UI).
- "Result history" means history **for as long as the configured retention lasts**.

## Privacy distinction

`attempt` / `attempt_answer` / `participant` records are created only within the scope of the active
retention policy. If results are not stored, the final result may be computed stateless and sent to
the client; later export or retrospective statistics cannot be expected
([ADR-0012](adr/0012-configurable-retention-profiles-and-stateless-mode.md), [AC-09](acceptance-criteria.md)).
