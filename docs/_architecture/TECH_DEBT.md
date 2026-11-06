# Technical Debt

Central list of known gaps and deviations from the architecture. This is for what is knowingly
postponed; resolved items are moved to TECH_DEBT_archive.md after some time.

## Format

- Open item: `### TD-NNN Title — OPEN`, followed by a description, a `file:line` reference and a proposed solution.
- Resolved item: `### TD-NNN Title — ✅ RESOLVED (YYYY-MM-DD)`, moved under `## RESOLVED`.
- `## OPEN` is the last section before `## RESOLVED`; new sections go above it.

## OPEN

### TD-008 CI has not run on GitHub — OPEN
- Where: `.github/workflows/quality.yml`; the repository has no remote yet
- Effect: the workflow passes actionlint and its commands pass in a clean Python 3.15 container, but it has never run on a GitHub runner.
- Solution: push to GitHub and confirm that both jobs pass.

### TD-009 Request bodies are not limited at the proxy — OPEN
- Where: `deploy/Caddyfile`, `app/api/play.py`
- Effect: file parts of a multipart request do not count towards `DATA_UPLOAD_MAX_MEMORY_SIZE`, so an anonymous client can stream large uploads to temporary files. `multipart/form-data` with an invalid charset answers 500.
- Solution in D5: `request_body { max_size }` in Caddy, and start and submit accept only urlencoded forms.

### TD-010 Admin editor rough edges — OPEN
- Where: `app/api/admin_quizzes.py`, `app/domain/authoring.py`, `app/api/admin_forms.py`, `app/api/jinja2/`
- Effect: a double click on Save adds a question twice. Changing only "featured" reports unpublished changes and creates a draft. A slug race, or a double click on Create, answers 500 or a misleading "identifier in use". The percentage shows as `50.0 %`, and the admin sees the id `choice.single`.
- Solution in B2 with the full editor: per-form key or disabled button, draft only for snapshot fields, the `IntegrityError` pattern from `admin_users.py`, locale-aware numbers, a `label` on question types.

### TD-011 Escaping is tested per plugin, not in the shared contract — OPEN
- Where: `tests/contracts/question_type.py`, `tests/contracts/test_choice_single.py`
- Effect: `render_public` and `render_admin` output is marked safe, so a new question type that does not escape would pass the contract suite.
- Solution in B2, before the next types: move both escaping tests into `QuestionTypeContract`.

## RESOLVED

### TD-001 Project purpose missing in README — ✅ RESOLVED (2026-11-05)
### TD-002 Installation steps missing in README — ✅ RESOLVED (2026-11-05)
### TD-003 Commands and API missing in README — ✅ RESOLVED (2026-11-05)
### TD-004 Development commands missing in README — ✅ RESOLVED (2026-11-05)
### TD-005 Security contact missing — ✅ RESOLVED (2026-11-05)
### TD-006 Makefile targets are placeholders — ✅ RESOLVED (2026-11-05)
### TD-007 CI is missing — ✅ RESOLVED (2026-11-05)
