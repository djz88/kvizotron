# Logical Data Model

The model is **logical**; Django models may adjust physical SQL tables and JSON
structures. Fields shown deliberately expose keys and invariants. Physical schema is owned by
[providers/persistence-sqlite.md](providers/persistence-sqlite.md) and each module's migrations.
ID format: UUIDv7 ([ADR-0023](adr/0023-id-format.md)).

Milestone D5 (limits, backup, restore) added no table and no column: limit counters live in process memory, and a backup is a directory of files in the `backups` volume ([ADR-0058](adr/0058-rate-limit-buckets.md), [ADR-0059](adr/0059-backup-and-restore.md)). A backup holds a copy of every table, so the retention of backups bounds how long deleted rows can be restored ([privacy.md](../privacy.md#backups)).

## Entities

| Entity / table | Key fields and meaning | Owner |
|---|---|---|
| `admin_user` | `id`, `login UNIQUE`, `password`, `is_active`, `email` (optional, may appear in quiz footers), `last_login`, `created_at` | kernel (shared by auth providers) |
| `django_session` | Django database sessions | Django |
| `plugin_installation` | `plugin_id`, `version`, `manifest_json`, `enabled`, `status` | kernel |
| `plugin_configuration` (not created yet, [ADR-0057](adr/0057-plugin-admin-reasons-locks-no-configuration-table.md)) | `plugin_id`, `scope=global/quiz/run`, `scope_id`, `settings_json`, `schema_version` | kernel |
| `quiz` | `id`, `slug UNIQUE`, `title` (locale → text), `description` (locale → text), `anonymous_label` (locale → text with `NN`, read live by the scoreboard), `default_locale`, `supported_locales`, `featured`, `created_by` (admin id; filled for older quizzes by migration `domain/0018`, ADR-0054), `quiz_type` (id of the applied quiz type, empty for none; copied by duplication, [ADR-0062](adr/0062-quiz-type-port.md)), `public_origin` (`https://host:port` of its QR code and public link, empty: the admin's address; the title is unique per language among quizzes without `archived_at`, [ADR-0067](adr/0067-quiz-title-and-public-address.md)), `archived_at` | domain |
| `quiz_revision` | `id`, `quiz_id`, `revision_no`, `status`, `snapshot_json`, `plugins_json`, `max_score`, `checksum`, `published_at` | domain |
| `app_setting` | `key`, `value_json`, `quiz_id` nullable (global when empty); one value per key and scope; a question value lives in the question ([ADR-0042](adr/0042-settings-inherited-and-declared.md)) | domain |
| `question_bank` | `id`, `name`, `created_by`, `created_at` | domain |
| `bank_folder` | `id`, `bank_id`, `parent_id` (empty at the top), `name` (1 to 80 characters, no `/`, unique among siblings by `casefold()`), `created_at`; a tree of at most four levels inside one bank, deleted only when empty ([ADR-0041](adr/0041-draw-rows-and-flow-settings.md)) | domain |
| `bank_question` | `id`, `bank_id`, `folder_id` (empty for an unfiled question), `question_json` (the shape of a quiz question in a draft), `tags`, `created_at` | domain |
| `media_asset` | `id`, `kind`, `storage_key`, `mime_type`, `size`, `sha256`, `created_at`, `private` (a participant's photo, never on `/media/`) | media-local |
| `media_address_check` | `address`, `ok`, `checked_at`; the last check of an address some quiz loads an image from. An address itself lives in the question definition as `source` ([ADR-0043](adr/0043-external-images.md)) | media-local |
| `quiz_run` | `id`, `quiz_id`, `run_no`, `current_revision_id`, `status`, `opened_at`, `closed_at`, `starts_at`, `deadline_at`, `attempt_limit_sec`, `participant_rules_json` (participant rules copied when planned or opened), `access_code_hash`, `config_json`, `retention_json` (`profile` and `period` copied when planned or opened; a test run reads the quiz live; the profile becomes `none` when the data are deleted), `data_deleted_at` (set when the run's data are deleted; the run stays, `ARCHIVED`), `retention_held_at` (waits for an admin to confirm deletion), `retention_summary_json` (anonymous statistics and deleted row counts, stored before anything is deleted and read in place of the rows, with the trigger and admin of the purge and a mark while a late export removal is due; [ADR-0056](adr/0056-retention-job-summary-held-runs.md), [ADR-0061](adr/0061-heartbeat-and-restore-marker.md)), `stateless_submitted` (submitted attempts counted under profile `none`), `participant_seq` (the last participant `number` given in the run; it only grows, migration `0024` set it to the run's highest), `results_json` (scoreboard settings copied when planned or opened, the tie `seed`; empty reads as a hidden board), `board_main_id` (nullable, the main run whose public scoreboard this run joins; display only, [ADR-0065](adr/0065-scoreboard-by-percent-and-shared-boards.md)), `rewards_json` (`reward_thresholds` and `winner_contact` copied when planned or opened; a test run reads the quiz live) | domain |
| `run_revision` | `id`, `run_id`, `revision_id`, `active_from`, `active_to` (empty on the current row), `max_score`, `switch_mode` (`finish`/`switch`) | domain |
| `participant` | `id`, `run_id`, `anonymous_key_hash` (HMAC of the cookie key with the run id, unique per run), `display_name`, `name_key` (for comparing names), `email` (nullable), `email_key` (the address stripped and casefolded, nullable, indexed, `max_length` 762 because casefolding can triple an address, so the erasure search is one query; personal data like `email`, [ADR-0061](adr/0061-heartbeat-and-restore-marker.md)), `name_dropped` (a taken name dropped at automatic submission), `created_at`, `number` (the anonymous label's number in the run, taken from `quiz_run.participant_seq` in `participants.find_or_create`'s own transaction and never changed or given again, so erasing a participant shifts no label, [ADR-0051](adr/0051-scoreboard-participants-and-official-attempt.md); a start refused after that transaction has still used up its number; nullable, unique per run, migration `0024` numbered older rows by `created_at`, `id`); the row is deleted with the run's data or on an erasure request | domain, rules in participants |
| `attempt` | `id`, `run_id`, `revision_id`, `participant_id`, `started_at`, `submitted_at`, `status` (incl. `SWITCHED`, `PENDING_GRADING`, `ABANDONED`), `replaced_by`, `score`, `max_score`, `duration_ms`, `submission_key`, `selection_json` (questions given, and a seed for option order), `auto_score` (what the server gave; `score` adds what admins decide), `settings_json` (navigation with its page size, reveal and the data profile frozen at start; attempts from before C3 hold `store_answers`) | domain |
| `attempt_question` | `id`, `attempt_id`, `question_snapshot_id`, `sequence_no`, `option_order_json` (proof of the concrete selection) | domain |
| `attempt_answer` | `id`, `attempt_id`, `question_id`, `answer_json`, `auto_points`, `manual_max`, `manual_points`, `graded_by`, `graded_at`, `asset_id`, `removed`, `approved`; unique per attempt and question; only what the data profile keeps and what a person grades ([ADR-0046](adr/0046-stored-answers-and-who-sees-them.md)) | domain |
| `hidden_answer_value` | `id`, `run_id`, `question_id`, `value_key` (a hash of the value), `hidden_by`, `created_at`; what an admin took off a walkthrough | domain |
| (scoreboard) | no table: the settings live in `quiz_run.results_json` and the board is computed from `attempt` ([ADR-0051](adr/0051-scoreboard-participants-and-official-attempt.md)) | results |
| `reward_rule` | `id`, `quiz_id`, `run_id` (empty for a rule of the quiz's template), `position`, `kind` (`threshold`, `participation`, `manual`, `draw`), `threshold_unit` and `threshold_value` (`percent`, `points` or `correct`), `min_unit` and `min_value` (who may be drawn; empty means everyone), `winners`, `alternates`, `texts_json` (locale → `name`, `description`, `claim`), `winners_public`, `created_at`; a run's rules are copies made when it is planned or opened ([ADR-0053](adr/0053-rewards-tiers-alternates-and-draw-history.md)) | domain, rules in rewards |
| `reward_entitlement` | `id`, `run_id`, `rule_id`, `participant_id`, `attempt_id` (the official attempt when granted), `status` (`granted`, `handed_over`, `cancelled`), `source` (`auto`, `manual`, `draw`), `reason`, `created_at`, `changed_at`, `changed_by` (an admin id; empty for an automatic change); at most one not cancelled per rule and participant | domain, rules in rewards |
| `draw` | `id`, `run_id`, `rule_id`, `action` (`draw`, `redraw`, `move_up`, `substitute`), `parent_id` (the draw an action amends or a redraw supersedes), `admin_id`, `created_at`, `eligible_count`, `eligible_set_hash`, `algorithm`, `rules_version` (SHA-256 of the rule's structure), `reason` (required except for `draw`), `audit_json` (pseudonyms selected, count, requested); never updated | domain, rules in drawings |
| `draw_entry` | `id`, `draw_id`, `participant_id` (cleared when the participant is deleted), `pseudonym` (salted HMAC-SHA256 of the participant id), `position`, `role` (`winner`, `alternate`, `out` for a replaced winner) | domain, rules in drawings |
| `audit_event` | `id`, `actor_type`, `actor_id`, `action`, `entity_type`, `entity_id`, `created_at`, `details_json` | kernel |
| `import_job` | `id`, `admin_id`, `status`, `target_json`, `mapping_json`, `report_json`, `created_at`, `expires_at` | csv-io |
| `export_job` | `id`, `admin_id`, `kind` (`results`), `status` (`queued`, `running`, `done`, `failed`, `interrupted`), `choices_json` (quiz, runs or all runs, files, photos, bundle, locale, file name), `report_json` (`files`, `error`), `boot` (the process that queued or runs it), `created_at`, `expires_at` (24 h later) ([ADR-0055](adr/0055-results-export-background-job-and-csv-dialect.md)) | csv-io |
| `test_link` | `id`, `run_id`, `token`, `expires_at`, `created_by`, `created_at`, `shown_origin` (scheme, host and port the link is shown with; empty: the admin's address); the run has kind `test`, and its revision may have status `TEST_COPY` | domain |
| `retention_job` | `id`, `run_id` (plain string, no foreign key), `trigger` (`automatic`, `manual`, `erasure`), `admin_id` (empty when automatic), `policy`, `cutoff_at`, `executed_at`, `counts_json` (rows and files deleted, by kind), `fingerprint` (HMAC of an erased e-mail, never the address; [ADR-0056](adr/0056-retention-job-summary-held-runs.md)) | retention |
| `branding_configuration` | `quiz_id` (empty for the global row, at most one row each), `theme_id`, `texts_json` (name, motto, footer per locale; `contact_email` as one address under `cs`, shown publicly), `tokens_json` (main, accent), `assets_json` (`logo` and `hero_logo`, each `{"asset": "<id>", "source": "<address>" or null}`; a value written before 2026-11-10 is the asset id alone and reads as no source) | domain ([ADR-0054](adr/0054-branding-owned-by-domain-and-theme.md)) |

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
  `attempt.submission_key` (idempotence), `participant(run_id, number)`.
- Unique while not cancelled: `reward_entitlement(rule_id, participant_id)`.
- Indexes: `(run_id, submitted_at)`, `(run_id, participant_id)`, `(run_id, score)`, `(run_id, revision_id)`.
- If duplicate nicknames are forbidden, normalised `display_name` is checked within the run in an
  atomic transaction (not only in UI).
- An attempt without a participant has no stored number: the board numbers it after the highest
  participant `number` in the run, in the order attempts started, so its number can move when a new
  browser joins.
- "Result history" means history **for as long as the configured retention lasts**.

## Privacy distinction

`attempt` / `attempt_answer` / `participant` records are created only within the scope of the active
retention policy. If results are not stored, the final result may be computed stateless and sent to
the client; later export or retrospective statistics cannot be expected
([ADR-0012](adr/0012-configurable-retention-profiles-and-stateless-mode.md), [ADR-0050](adr/0050-data-profile-and-local-resume.md), [AC-09](acceptance-criteria.md)).
Under profile `none` an attempt row exists only from start to submission and is then deleted with the attempts it replaced; the run keeps a count, `stateless_submitted`.
