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
| `quiz` | `id`, `slug UNIQUE`, `title` (locale → text), `description` (locale → text), `anonymous_label` (locale → text with `NN`, read live by the scoreboard), `default_locale`, `supported_locales`, `featured`, `archived_at` | domain |
| `quiz_revision` | `id`, `quiz_id`, `revision_no`, `status`, `snapshot_json`, `plugins_json`, `max_score`, `checksum`, `published_at` | domain |
| `app_setting` | `key`, `value_json`, `quiz_id` nullable (global when empty); one value per key and scope; a question value lives in the question ([ADR-0042](adr/0042-settings-inherited-and-declared.md)) | domain |
| `question_bank` | `id`, `name`, `created_by`, `created_at` | domain |
| `bank_question` | `id`, `bank_id`, `question_json` (the shape of a quiz question in a draft), `tags`, `created_at` | domain |
| `media_asset` | `id`, `kind`, `storage_key`, `mime_type`, `size`, `sha256`, `created_at`, `private` (a participant's photo, never on `/media/`) | media-local |
| `media_address_check` | `address`, `ok`, `checked_at`; the last check of an address some quiz loads an image from. An address itself lives in the question definition as `source` ([ADR-0043](adr/0043-external-images.md)) | media-local |
| `quiz_run` | `id`, `quiz_id`, `run_no`, `current_revision_id`, `status`, `opened_at`, `closed_at`, `starts_at`, `deadline_at`, `attempt_limit_sec`, `participant_rules_json` (participant rules copied when planned or opened), `access_code_hash`, `config_json`, `retention_json` (`profile` and `period` copied when planned or opened; a test run reads the quiz live), `stateless_submitted` (submitted attempts counted under profile `none`), `results_json` (scoreboard settings copied when planned or opened, the tie `seed`, and `merged` set by the merge action; empty reads as a hidden board), `rewards_json` (`reward_thresholds` and `winner_contact` copied when planned or opened; a test run reads the quiz live) | domain |
| `run_revision` | `id`, `run_id`, `revision_id`, `active_from`, `active_to` (empty on the current row), `max_score`, `switch_mode` (`finish`/`switch`) | domain |
| `participant` | `id`, `run_id`, `anonymous_key_hash` (HMAC of the cookie key with the run id, unique per run), `display_name`, `name_key` (for comparing names), `email` (nullable), `name_dropped` (a taken name dropped at automatic submission), `created_at`; `redacted_at` arrives with D3 | domain, rules in participants |
| `attempt` | `id`, `run_id`, `revision_id`, `participant_id`, `started_at`, `submitted_at`, `status` (incl. `SWITCHED`, `PENDING_GRADING`, `ABANDONED`), `replaced_by`, `score`, `max_score`, `duration_ms`, `submission_key`, `selection_json` (questions given, and a seed for option order), `auto_score` (what the server gave; `score` adds what admins decide), `settings_json` (navigation with its page size, reveal and the data profile frozen at start; attempts from before C3 hold `store_answers`) | domain |
| `attempt_question` | `id`, `attempt_id`, `question_snapshot_id`, `sequence_no`, `option_order_json` (proof of the concrete selection) | domain |
| `attempt_answer` | `id`, `attempt_id`, `question_id`, `answer_json`, `auto_points`, `manual_max`, `manual_points`, `graded_by`, `graded_at`, `asset_id`, `removed`, `approved`; unique per attempt and question; only what the data profile keeps and what a person grades ([ADR-0046](adr/0046-stored-answers-and-who-sees-them.md)) | domain |
| `hidden_answer_value` | `id`, `run_id`, `question_id`, `value_key` (a hash of the value), `hidden_by`, `created_at`; what an admin took off a walkthrough | domain |
| (scoreboard) | no table: the settings live in `quiz_run.results_json` and the board is computed from `attempt` ([ADR-0051](adr/0051-scoreboard-participants-and-official-attempt.md)) | results |
| `reward_rule` | `id`, `quiz_id`, `run_id` (empty for a rule of the quiz's template), `position`, `kind` (`threshold`, `participation`, `manual`, `draw`), `threshold_unit` and `threshold_value` (`percent`, `points` or `correct`), `min_unit` and `min_value` (who may be drawn; empty means everyone), `winners`, `alternates`, `texts_json` (locale → `name`, `description`, `claim`), `winners_public`, `created_at`; a run's rules are copies made when it is planned or opened ([ADR-0053](adr/0053-rewards-tiers-alternates-and-draw-history.md)) | domain, rules in rewards |
| `reward_entitlement` | `id`, `run_id`, `rule_id`, `participant_id`, `attempt_id` (the official attempt when granted), `status` (`granted`, `handed_over`, `cancelled`), `source` (`auto`, `manual`, `draw`), `reason`, `created_at`, `changed_at`, `changed_by` (an admin id; empty for an automatic change); at most one not cancelled per rule and participant | domain, rules in rewards |
| `draw` | `id`, `run_id`, `rule_id`, `action` (`draw`, `redraw`, `move_up`, `substitute`), `parent_id` (the draw an action amends or a redraw supersedes), `admin_id`, `created_at`, `eligible_count`, `eligible_set_hash`, `algorithm`, `rules_version` (SHA-256 of the rule's structure), `reason` (required except for `draw`), `audit_json` (pseudonyms selected, count, requested); never updated | domain, rules in drawings |
| `draw_entry` | `id`, `draw_id`, `participant_id` (nullable, so D3 can drop it), `pseudonym` (salted HMAC-SHA256 of the participant id), `position`, `role` (`winner`, `alternate`, `out` for a replaced winner) | domain, rules in drawings |
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
 quiz 1───N reward_rule (template, no run)
 quiz_run 1───N reward_rule 1───N reward_entitlement N───1 participant
 reward_rule 1───N draw 1───N draw_entry N───0..1 participant
```

## Important indexes and constraints

- Unique: `quiz.slug`, `quiz_revision(quiz_id, revision_no)`, `quiz_run(quiz_id, run_no)`,
  `attempt.submission_key` (idempotence).
- Unique while not cancelled: `reward_entitlement(rule_id, participant_id)`.
- Indexes: `(run_id, submitted_at)`, `(run_id, participant_id)`, `(run_id, score)`, `(run_id, revision_id)`.
- If duplicate nicknames are forbidden, normalised `display_name` is checked within the run in an
  atomic transaction (not only in UI).
- "Result history" means history **for as long as the configured retention lasts**.

## Privacy distinction

`attempt` / `attempt_answer` / `participant` records are created only within the scope of the active
retention policy. If results are not stored, the final result may be computed stateless and sent to
the client; later export or retrospective statistics cannot be expected
([ADR-0012](adr/0012-configurable-retention-profiles-and-stateless-mode.md), [ADR-0050](adr/0050-data-profile-and-local-resume.md), [AC-09](acceptance-criteria.md)).
Under profile `none` an attempt row exists only from start to submission and is then deleted with the attempts it replaced; the run keeps a count, `stateless_submitted`.
