# Technical Debt — Archive

Full details of resolved items from TECH_DEBT.md. Read only when investigating regressions.

## RESOLVED

### TD-010 Admin editor rough edges — ✅ RESOLVED (2026-11-06)
- Where: `app/api/admin_quizzes.py`, `app/domain/authoring.py`, `app/api/admin_forms.py`, `app/api/jinja2/`
- Effect: a double click on Save adds a question twice. Changing only "featured" reports unpublished changes and creates a draft. A slug race, or a double click on Create, answers 500 or a misleading "identifier in use". The percentage shows as `50.0 %`, and the admin sees the id `choice.single`.
- Solution in B2 with the full editor: per-form key or disabled button, draft only for snapshot fields, the `IntegrityError` pattern from `admin_users.py`, locale-aware numbers, a `label` on question types.

### TD-009 Request bodies are not limited at the proxy — ✅ RESOLVED (2026-11-06)
- Where: `deploy/Caddyfile`, `app/api/play.py`
- Effect: file parts of a multipart request do not count towards `DATA_UPLOAD_MAX_MEMORY_SIZE`, so an anonymous client can stream large uploads to temporary files. `multipart/form-data` with an invalid charset answers 500.
- Solution in D5: `request_body { max_size }` in Caddy, and start and submit accept only urlencoded forms.
- Resolved: Caddy `request_body { max_size 16MB }`; `RefuseMultipartMiddleware` answers 415 to every multipart POST, so also on the public login.

### TD-011 Escaping is tested per plugin, not in the shared contract — ✅ RESOLVED (2026-11-06)
- Where: `tests/contracts/question_type.py`, `tests/contracts/test_choice_single.py`
- Effect: `render_public` and `render_admin` output is marked safe, so a new question type that does not escape would pass the contract suite.
- Solution in B2, before the next types: move both escaping tests into `QuestionTypeContract`.
- Resolved: Tests moved into `QuestionTypeContract`; `HOSTILE` text in `render_public` and `render_admin`.

### TD-012 Small leftovers from the B1 review — ✅ RESOLVED (2026-11-06)
- Where: `app/api/admin_quizzes.py` (`_free_slug`, `_archived_message`, `quiz_restore`), `app/domain/authoring.py` (`discard_draft`, `publish`, `restore_quiz`), `app/domain/attempts.py` (`_switch`)
- Effect:
  - The suggested slug of a duplicate ends in the Czech `-kopie`, also for en and uk admins. It can be edited.
  - The `quiz.draft_discarded` audit row has no revision number, and the next draft reuses the discarded draft's number.
  - Restoring a quiz that is not archived changes nothing but writes a `quiz.restored` audit row.
  - `_archived_message` carries a pointless `# noqa: N802`.
  - `publish` reads the open round in two queries; a round opened or closed between them could get a decision that does not match. SQLite serialises writers, so the effect is tiny.
  - A switch on the current revision issues a new token and submission key, which keeps retries working, but no docstring says it is intended.
- Solution: a neutral suffix such as `-copy`, `revision_no` in the audit details, no audit row when `archived_at` is already empty, remove the `noqa`, read the round once, add the docstring.
- Resolved: All but the reused number of a discarded draft, which stays because avoiding it needs a new column; the audit row names the number.
