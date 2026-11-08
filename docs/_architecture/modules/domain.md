# Module: Domain

Package: `app/domain/` — quiz, revision, run, attempt models, invariants and services, including storage
of attempts and results. Persistence uses the Django ORM ([ADR-0036](../adr/0036-django-web-framework-and-orm.md),
[PersistenceProvider](../providers/persistence-sqlite.md)).

Terms: older documents say "round" for a run (`QuizRun`). The UI says "běh" in Czech and "run" in English.

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
| `SEPARATE_BY_REVISION` (`separate`) | Separate scoreboards per revision, newest first, the official attempt chosen in each. **Default.** |
| `MERGE_COMPATIBLE` (`merged`) | Common scoreboard allowed only with equal max points. The admin sees the differences between revisions, is warned that equal max points do not guarantee equal difficulty, and decides. Not a preset: an audited action on the run page that can be undone (`results_json["merged"]`). |
| `LATEST_ONLY` (`latest`) | Only attempts on the run's current revision. |

Who is a row, the official attempt, anonymised live names and the anonymous label: [ADR-0051](../adr/0051-scoreboard-participants-and-official-attempt.md). Statistics: `app/domain/run_stats.py`, over every submitted attempt of a normal run.

## Rewards and draws

Decision: [ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md). Rules belong to a run, or to the quiz's template without a run; a run's rule structure is fixed once it opens, its texts are not. A test run has none.

```
 entitlement:  granted ──hand over──▶ handed_over
                  │                        │
                  └──cancel (reason)──▶ cancelled ◀── cancel (admin, reason)
```

- Sources: `auto` (threshold or participation from the official attempt; recomputation may cancel a granted one with "no longer reached"), `manual` (granted by the admin), `draw` (a drawn winner). Only an admin cancels `manual`, `draw`, participation and handed-over entitlements; a rule an admin cancelled is never granted back automatically.
- Draw actions: `draw` starts a chain, `move_up` and `substitute` amend it, `redraw` supersedes it and starts a new one. Each action is a new `draw` row; the current winners and alternates are replayed from the chain. Only on a closed or archived run.

## Restart

Restart creates a new `QuizRun`. The configuration of the previous run may optionally be copied —
**never** its attempts or results. Older runs, revisions and history are not deleted *as a
consequence of the restart*. Previously configured retention and explicit administrative deletion of
personal data still apply. See [ADR-0007](../adr/0007-restart-creates-new-run-keeps-history.md).

## Functional requirements

### Quiz and revision lifecycle

- `FR-52` Every quiz has a short description per selected language, up to 300 characters. It is handled like the title: on the quiz row until publication, in the snapshot and the change overview. A missing description blocks publication. Revisions published before this field have none.
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

- `FR-47` When a new revision is published during an open round, the setting
  `revision_switch_policy` decides what happens ([ADR-0038](../adr/0038-revision-switch-policy-and-settings.md)):
  `ask` (the default: the admin chooses at publication), `notify_switch` (the round moves to the new
  revision; participants in progress see a notice and "Switch" replaces the button that moves forward) or
  `let_finish` (the round moves; participants in progress finish on the old revision). At publication the
  admin may also choose `stay`: the round stays on its revision and the new one applies from the next round.
  Switching creates a new attempt with the original start time; answers to questions whose type and
  definition did not change stay, changed questions are empty and marked, and the old attempt can no
  longer be submitted.
- `FR-48` Before publishing, the admin sees the changes against the latest published revision, including
  correct answers, points and scoring, and what will happen to an open round. A quiz that changed after
  the page was shown is not published.
- `FR-49` An older revision can be used as a new draft, which publishes under a new number and leaves the old
  revision untouched. A draft can be discarded, which restores the title and languages of the latest published
  revision. A quiz that was never published has nothing to return to, so its draft cannot be discarded.

An archived quiz has no public pages and is read-only in the admin until it is restored. It can be duplicated.
A quiz with an open round cannot be archived. Archiving moves the `PUBLISHED` revision to `ARCHIVED`, and restoring
moves the highest `ARCHIVED` revision back; revisions have no archive action of their own.

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

Status changes that time makes due are applied on the first request after them, and archiving hides an ended run in admin and from the public walkthrough ([ADR-0048](../adr/0048-run-timing.md)).

## Invariants

- A published revision is never mutated. At publication the pool of bank questions it draws from is
  copied into the revision, so later bank edits do not change it. A later bank edit shows as unpublished changes.
- A setting is inherited global → quiz → question ([ADR-0042](../adr/0042-settings-inherited-and-declared.md)).
- An attempt freezes at start which questions it got and how it behaves ([ADR-0041](../adr/0041-draw-rows-and-flow-settings.md)). Switching keeps what still fits and draws the rest.
- An attempt is evaluated against the revision and question selection frozen at its start (FR-19,
  [AC-04](../acceptance-criteria.md)). Switching creates a new attempt; it never changes an existing one's revision.
- A new run never inherits attempts, results, entitlements or draws. It may copy reward rules from the quiz's template or the previous run when it is planned or opened (`reward_source`).
- A run's participant rules and access code are its own: the rules are copied from the quiz when it is planned or opened and fixed once it opens, the code is never inherited ([ADR-0049](../adr/0049-participants-and-access-code.md)).
- A run's data profile and retention period are copied from the quiz when it is planned or opened. The profile is fixed once the run opens, the period stays editable. Under `none` a submitted attempt is deleted and counted ([ADR-0050](../adr/0050-data-profile-and-local-resume.md)); the period is a value that D3 will act on.
- Attempt statuses: `IN_PROGRESS`, `SUBMITTED`, `PENDING_GRADING`, `SWITCHED` (replaced by a new revision) and `ABANDONED` (replaced by a new start under "counts only when submitted"). An `ABANDONED` attempt can never be submitted, switched or checked, and holds no name.
- Test attempts live in runs of kind `test`, which `QuizRun.objects` and `quiz.runs` hide ([ADR-0044](../adr/0044-preview-and-test-links.md)). A query on `Attempt` across runs must filter on the run's kind itself.
