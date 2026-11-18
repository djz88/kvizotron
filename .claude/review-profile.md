# Review profile

## Profile: `kvizotron`

### Where things are

| What | Where |
|---|---|
| Architecture and decisions | `docs/_architecture/`, `docs/_architecture/adr/` |
| Contracts between modules | `app/contracts/`, `docs/_architecture/modules/contracts.md`, `docs/plugin-api.md` |
| Documentation | `docs/_architecture/README.md` (the `FR-xx` map), `docs/_architecture/acceptance-criteria.md` |
| Tests | `tests/`, shared suites in `tests/contracts/` |
| Shared code / kernel | `app/kernel/` |
| Environment configuration | `deploy/compose.yaml`, `deploy/.env.example` |

### What is already verified by machine

The output of the `kvizotron-check-applied` skill arrives as input if the caller passes it. Do not check again what `tests/test_wiring.py` and `tests/test_docs.py` guard: that a module, template, URL, script or ID exists and is wired in. Judge whether it is correct, not whether it exists.

### Modules and their boundaries

| Module | Owns | Must not |
|---|---|---|
| `app/contracts` | protocols and schemas | import Django |
| `app/kernel` | bootstrap, registry, events, lifecycle | contain product features |
| `app/domain` | quizzes, runs, attempts, scores | import `app/api` or modules |
| `app/api` | URLs, admin and play templates | compute scores |
| `app/plugins` | question types, scoring, flows, theme | import anything except `app.contracts` and `app.kernel`; assemble HTML by hand |
| `app/providers` | login, database, media, CSV | import `app/domain`, `app/api`, `app/plugins` |

### Binding decisions

- ADR-0006: a published revision is immutable → `docs/_architecture/adr/0006-separate-quiz-revision-run-attempt-immutable-revisions.md`
- ADR-0007: a restart creates a new run and does not carry over results → `docs/_architecture/adr/0007-restart-creates-new-run-keeps-history.md`
- ADR-0009: the server computes the score, the client is not trusted → `docs/_architecture/adr/0009-server-authoritative-scoring-signed-token-idempotent-submit.md`
- ADR-0025: time is decided by receipt on the server, whole seconds, `<=` → `docs/_architecture/adr/0025-deadline-boundary-second-semantics.md`
- ADR-0042: settings are inherited global → quiz → question, a narrower scope has a written reason → `docs/_architecture/adr/0042-settings-inherited-and-declared.md`
- ADR-0048: a run's state changes only at the first request after the deadline → `docs/_architecture/adr/0048-run-timing.md`

### Critical paths

- `app/api/play.py`, `app/domain/attempts.py`: what is accepted from a participant and how the score is computed
- `app/domain/tokens.py`: signed attempt and result tokens
- `app/domain/run_schedule.py`, `app/api/run_clock.py`: opening and closing a run
- `app/domain/visibility.py`: who sees answers and photos
- `app/api/admin_auth.py`, `app/providers/auth_local/`: admin login
- `app/providers/media_local/`: uploaded files and downloads from URLs
- `deploy/compose.yaml`, `deploy/Caddyfile`: deployment

### What counts as a BLOCKER in this project

- The answer key in the output of `public_payload()`, `render_public` or on a page before submission.
- A score, solution or time taken from the client.
- A change to a published revision, or a new run that carries over results.
- A participant's answer, personal data or a secret in a log; an e-mail in public output.
- A submission accepted after `min(deadline_at, started_at + limit)`.
- A test or preview that counts toward results.
- New behaviour without a test, or a weakened test.

### Testing expectations

- Every change of behaviour has a test, a bug fix starts with a test that shows it.
- Every module passes the suite in `tests/contracts/`; the only exception is in `tests/test_wiring.py` with a debt entry.
- Scenarios that must stay covered: `docs/_architecture/acceptance-criteria.md`.

### Conventions that are not visible from the code

- Security is proportionate to a quiz: for input from a trusted admin a basic check is enough, no antivirus or sanitizers are proposed.
- `QuizRun` is a run in texts, never a round. Documentation, `CLAUDE.md` and agent files are in English; Czech stays in `README.cs.md` and in user-facing texts.
- `.mo` files are in git on purpose.
- Deferred minor items belong in `docs/_architecture/TECH_DEBT.md`, not in out-of-scope fixes.
