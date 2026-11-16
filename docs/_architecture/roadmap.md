# Roadmap to v1.0

All stages lead to version 1.0. No dates are set; stages are sequential, work inside a stage may run
in parallel. Each stage ends when its exit criteria pass. Requirement → stage mapping: [FR → stage matrix](#fr--stage-matrix).

```
 Stage A ───────▶ Stage B ───────────▶ Stage C ────────────▶ Stage D ──────▶ v1.0
 kernel +         editor, revisions,    competitions &        administration,
 vertical slice   banks                 history               hardening, release
```

## Stage A — Kernel and vertical slice

**Goal:** a working end-to-end quiz and a demonstration plugin test.

| Milestone | Content | Status |
|---|---|---|
| A1 Repo & delivery | Repo, working `make` targets, CI calling `make quality` (lint, tests, gitleaks), Docker Compose, Caddy | Done 2026-11-05; CI not yet run on GitHub ([TD-008](TECH_DEBT.md)) |
| A2 Kernel | Module discovery, manifests, contracts, dependency resolver, registry, events | Done 2026-11-06 |
| A3 Core providers | `local-auth`, `sqlite` persistence + migrations, first admin CLI | Done 2026-11-06 |
| A4 Vertical slice | Basic admin UI, single-choice quiz, cs/en/uk runtime, QR, start/submit, server-side scoring, signed token | Done 2026-11-06 |

- **Exit criteria:** all acceptance criteria with Stage = A in [acceptance-criteria.md](acceptance-criteria.md).
- **Risks:** contract design churn — mitigate with contract tests from day one.

## Stage B — Editor, revisions and banks

**Goal:** producible content and safe changes without rewriting history.

| Milestone | Content | Status |
|---|---|---|
| B1 Revisions | Immutable revisions, `DRAFT → PUBLISHED → SUPERSEDED/ARCHIVED`, translation validation; settings with quiz override, a new revision during an open round, change overview, return to an older revision, discard, duplicate and archive a quiz | Done 2026-11-06 |
| B1.5 UI foundation | Navigation, quiz header with a state-driven main button, tabs, a fixed place for each setting, quiz description, five colour palettes (FR-53), public menu and information pages | Done 2026-11-06 |
| B2 Question types | Types Výběr (one, several or no correct answers, yes/no) and Přiřazení (pairs, ordering), images in questions and answers (FR-21 admin upload), scoring strategies including partial, points and sources per question (FR-54), unsaved changes warning, [TD-010](TECH_DEBT.md) | Done 2026-11-06 |
| B3 Banks & flow | Question bank, random selection, navigation modes with a progress indicator, answer-reveal policy, translated explanation of the correct answer | Done 2026-11-07 |
| B4 Media | External HTTPS image addresses as a copy or from their source (local upload came with B2); settings inherited global → quiz → question and declared by every module | Done 2026-11-07 |
| B5 Testing & import | Preview, test links, CSV import and export of questions | Done 2026-11-07 |
| B6 Remaining question types | Numeric answer, text fill-in, image upload by a participant (FR-45), grading of photos, stored answers and who sees them, a private result link, a public walkthrough, module requirements on settings (FR-46, AC-16 in part, AC-17, AC-53 to AC-61) | Done 2026-11-07 |

- **Exit criteria:** all acceptance criteria with Stage = B in [acceptance-criteria.md](acceptance-criteria.md).
- **Risks:** per-type JS editors grow complex — keep each in its plugin.

## Stage C — Competitions and history

**Goal:** a complete competition cycle.

| Milestone | Content |
|---|---|
| C1 Runs | Separate runs/restart, schedule, deadline, attempt time limit, archive of a run, configured time zone (AC-05, AC-07, AC-62 to AC-69). Done 2026-11-07 |
| C2 Participants | Cookie identity, attempt/duplicate rules, access code, name/e-mail collection (AC-70 to AC-76). Done 2026-11-07 |
| C3 Data policies | Data profile, stateless mode, retention period as a run value, local resume (AC-09, AC-11, AC-77 to AC-80). Done 2026-11-08 |
| C4 Results | Public scoreboard with visibility, anonymised live names, one official attempt per browser, ties, revision modes and merging, projector view, statistics and comparison of runs, sortable attempts table (AC-06, AC-16, AC-18, AC-81 to AC-85). Done 2026-11-08 |
| C4.5 UI simplification | "Basic / All" switch and seven setting groups on every settings page, a run plan that shows what differs, quiz tabs with More, a shorter run page, pages of questions, one question at a time by default for new installations, the logo in the bar and on About (AC-86 to AC-89). Done 2026-11-08 |
| C5 Rewards & draw | Threshold, participation, manual and draw rewards copied onto a run from the quiz template or the previous run, tiers and winner contact as settings, entitlements from the official attempt with claim instructions on the result, a manual draw with ranked alternates, move-up, substitute and redraw in an append-only history, published winners on the scoreboard (AC-90 to AC-93). Done 2026-11-08 |

- **Exit criteria:** all acceptance criteria with Stage = C in [acceptance-criteria.md](acceptance-criteria.md).
- **Risks:** SQLite single writer under simultaneous submit — early load spike test.
- **Comes in C:** revealing answers after a run closes, with a lasting result page ([ADR-0041](adr/0041-draw-rows-and-flow-settings.md)); refusing reveal after each question in a run with a visible scoreboard or rewards (AC-18).
- **To decide in C:** sources disabled automatically in competitions, like solutions in [ADR-0035](adr/0035-immediate-solutions-only-without-competition.md).

## Stage D — Administration and release 1.0

**Goal:** an operable release 1.0.

| Milestone | Content |
|---|---|
| D1 Branding | Branding and theme contract, global + per-quiz override per field: name, motto, logo, custom colours derived to WCAG AA and footer, with the line "Runs on Kvízotron" on public pages; the theme takes over the palette list from the domain catalogue; finishes FR-05. Addendum: one footer line with licence, local badges, version, year and a public contact e-mail that falls back to the quiz creator's account e-mail (admins gain an optional e-mail, quizzes remember their creator), and a section panel on the settings pages that holds the Basic / All switch. Editable menu texts and information pages were dropped from D1 (AC-94 to AC-100). Done 2026-11-09 |
| D2 Export | CSV export of results, participants and statistics, with formula-injection protection (questions came with B5): attempts, participants, question statistics, answers, reward entitlements and draw history of one run, all runs or selected runs, as separate files or one ZIP with optional photos, prepared by a background job in the app process and downloadable for 24 hours; Google Sheets contract only (AC-101 to AC-109). Done 2026-11-09 |
| D3 Retention | Provider `retention.local` for the trail of deletions and the domain's deletion in stages: a `jobs` service with one pass per hour, an anonymous summary that statistics and the comparison of runs read, profile `none` and the archive for a deleted run, runs already past their period held until an admin confirms them, "Delete data now", an erasure request across runs by e-mail or nickname, a Deletion history with an e-mail fingerprint, and the date of deletion on the run pages (AC-110 to AC-119). Done 2026-11-09 |
| D4 Plugin admin | A Modules page with every module, its state and version, switching plugins with plain refusals, four plugins the application needs locked, a planned run blocking a disable, each module's settings with links and where a value differs from the global one, and pages that answer with a plugin disabled or missing; no `plugin_configuration` table until a module needs one (AC-120 to AC-127). Done 2026-11-09 |
| D5 Hardening & release | Request limits per client address in four buckets (five since the follow-up, ADR-0060) with every public route audited, HSTS and a tested set of response headers, a daily verified backup of the database and media from the `jobs` service and a manual restore that keeps what it replaces (and, since the second follow-up, refuses beside a live `app` or `jobs` and marks an interrupted restore, ADR-0061), a load test of 50 participants with photos (a test in `make test` and `make load`), one configuration reference, and AC-03 to AC-18 named by tests (AC-129 to AC-147). Done 2026-11-10 |

- **Exit criteria:** all acceptance criteria with Stage = D, plus every AC-01 – AC-18 green ([acceptance-criteria.md](acceptance-criteria.md)).
- **Risks:** retention vs backups — verify backups cannot restore deleted PII indefinitely.

## FR → stage matrix

| Stage | Requirements |
|---|---|
| A | FR-01, FR-02, FR-03, FR-04, FR-07, FR-15 (single choice), FR-24 (basic) |
| B | FR-05 (base), FR-08, FR-09, FR-47, FR-48, FR-49, FR-50, FR-51, FR-52, FR-53, FR-13, FR-15, FR-16, FR-17, FR-18, FR-19, FR-20, FR-21, FR-23, FR-24, FR-40, FR-41, FR-45 (type), FR-46, FR-54 |
| C | FR-06, FR-10, FR-11, FR-12, FR-22, FR-25, FR-26, FR-27, FR-28, FR-29, FR-30, FR-31, FR-32, FR-33, FR-36, FR-37, FR-38, FR-39, FR-43, FR-45 (grading) |
| D | FR-05 (complete), FR-14, FR-34, FR-35, FR-42, FR-44 |

> Assignment of individual FRs to stages is derived from the spec's stage descriptions (§10); where
> the spec was silent (e.g. FR-35 privacy notice, FR-06 access code) the stage is a proposal.

## After v1.0 (LATER)

Google Sheets/Workspace connector, video question, more themes, SSO/OIDC, e-mail automation,
voucher codes, JSON export — each as a module, without kernel change.
