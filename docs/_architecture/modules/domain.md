# Module: Domain

Package: `app/domain/` — quiz, revision, run, attempt models, invariants and services, including storage
of attempts and results. Persistence uses the Django ORM ([ADR-0036](../adr/0036-django-web-framework-and-orm.md),
[PersistenceProvider](../providers/persistence-sqlite.md)).

Key decision: [ADR-0006](../adr/0006-separate-quiz-revision-run-attempt-immutable-revisions.md).

## Core concepts — MUST NOT be conflated

1. **Quiz (definition)** — long-lived identity: title, slug, default locale, list of supported locales. Reusable.
2. **QuizRevision (content revision)** — immutable published snapshot of questions, correct answers,
   scoring rules, translations and versions of required plugins. A new revision is created when
   published content changes.
3. **QuizRun / Edition (competition run)** — a concrete run of a quiz with schedule, participation
   rules, data collection, scoreboard and rewards. "Run again / restart the competition" = new
   `run_id`, by default a **new empty ranking and new result set**; old runs stay in history.
4. **Attempt** — one filling-in instance in a given run and revision, including the actually
   selected and shuffled questions and timestamps.
5. **Participant** — identity for one concrete run (anonymous cookie identifier, public
   name/nickname, optionally e-mail); not a verified natural person.
6. **Scoreboard** — projection of eligible results of a run according to its settings; it has no
   independent truth about the score.

## Relations

```
 Quiz 1 ──── N QuizRevision
  │                 ▲
  │ 1               │ N..1 (each attempt pinned to ONE revision at start)
  N                 │
 QuizRun 1 ──── N Attempt
  │  1
  └──── N Participant          QuizRun N ──── N QuizRevision  (via run_revision, over time)
```

- `Quiz 1→N QuizRevision`, `Quiz 1→N QuizRun`, `QuizRun 1→N Attempt`, `QuizRun 1→N Participant`,
  `Attempt N→1 QuizRevision`.
- A run may use several revisions during its lifetime; each attempt uses a single immutable revision
  assigned when it starts.

## Scoreboard modes on revision change (per run, chosen by admin)

See [ADR-0008](../adr/0008-scoreboard-revision-modes-default-separate.md).

| Mode | Behaviour |
|---|---|
| `SEPARATE_BY_REVISION` | Separate scoreboards per revision. **Default.** |
| `MERGE_COMPATIBLE` | Common scoreboard allowed only with equal max points. The admin sees the differences between revisions, is warned that equal max points do not guarantee equal difficulty, and decides. |
| `LATEST_ONLY` | Public view shows only the latest revision; older results remain available to the admin. |

## Restart

Restart creates a new `QuizRun`. The configuration of the previous run may optionally be copied —
**never** its attempts or results. Older runs, revisions and history are not deleted *as a
consequence of the restart*. Previously configured retention and explicit administrative deletion of
personal data still apply. See [ADR-0007](../adr/0007-restart-creates-new-run-keeps-history.md).

## Functional requirements

### Quiz and revision lifecycle

- `FR-08` Admin creates/edits/duplicates/archives quizzes and sees the list of drafts, published
  revisions and historical runs.
- `FR-09` Draft and revision states: `DRAFT → PUBLISHED → SUPERSEDED/ARCHIVED`. A published revision
  is immutable. Editing creates a new draft and a new published revision.

```
            publish                 newer revision published
  DRAFT ─────────────▶ PUBLISHED ─────────────────────────▶ SUPERSEDED
                          │
                          └──────── archive ──────────────▶ ARCHIVED
  (edit of PUBLISHED = new DRAFT → new PUBLISHED revision; old one never mutated)
```

### Run lifecycle

- `FR-10` Admin publishes a quiz and schedules a run with `starts_at` and `deadline_at` (both
  optional) and an optional time limit counted from attempt start. All times are stored in UTC and
  entered/displayed in the configured time zone.
- `FR-11` A submission after the deadline is not accepted, even if the attempt started before the
  deadline. Server time applies, with condition
  `server_now <= min(deadline_at, started_at + attempt_limit)` and an unambiguously specified
  behaviour for the boundary second: compared in whole seconds, using server receive time
  ([ADR-0025](../adr/0025-deadline-boundary-second-semantics.md)). A run without a deadline is valid until manually closed.
  See [ADR-0010](../adr/0010-strict-server-side-deadline.md).
- `FR-12` Admin can close a run, archive it and **restart it as a new run**. The new run has new
  statistics, results, rewards, draws and scoreboard; previous data remain according to retention.
- `FR-13` Preview without writing results, and a separate test mode with its own test attempts.
  **Admin chooses** which variant to use. Test attempts never count towards the public scoreboard,
  rewards or real participation statistics. See [ADR-0017](../adr/0017-preview-vs-isolated-test-mode.md).

```
            starts_at reached / open        close (manual or deadline)
 SCHEDULED ─────────────────────────▶ OPEN ─────────────────────────▶ CLOSED ──▶ ARCHIVED
                                                                        │
                                              restart ─▶ new QuizRun (SCHEDULED/OPEN), empty results
```

> Run state names (`SCHEDULED/OPEN/CLOSED/ARCHIVED`) are a documentation proposal; the spec defines
> only the behaviour (scheduled, open, closed, archived, restart).

## Invariants

- A published revision is never mutated. At publication the pool of bank questions it draws from is
  copied into the revision, so later bank edits do not change it.
- An attempt is evaluated against the revision and question selection frozen at its start (FR-19,
  [AC-04](../acceptance-criteria.md)).
- A new run never inherits attempts, results, entitlements or draws.
- Test attempts are flagged (`test_mode`) and excluded from every public projection.
