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

| Milestone | Content |
|---|---|
| B1 Revisions | Immutable revisions, `DRAFT → PUBLISHED → SUPERSEDED/ARCHIVED`, translation validation |
| B2 Question types | Seven remaining types, image answer type, scoring strategies (incl. partial), full editor, module requirements on settings |
| B3 Banks & flow | Question bank, random selection, navigation modes, answer-reveal policy |
| B4 Media | Local upload + HTTPS URLs, MIME checks, alt texts |
| B5 Testing & import | Preview / test mode, CSV import |

- **Exit criteria:** all acceptance criteria with Stage = B in [acceptance-criteria.md](acceptance-criteria.md).
- **Risks:** per-type JS editors grow complex — keep each in its plugin.

## Stage C — Competitions and history

**Goal:** a complete competition cycle.

| Milestone | Content |
|---|---|
| C1 Runs | Separate runs/restart, schedule, deadline, attempt time limit |
| C2 Participants | Cookie identity, attempt/duplicate rules, access code, name/e-mail collection |
| C3 Data policies | Retention profiles, stateless mode, local resume |
| C4 Results | Results, scoreboard incl. revision modes, analytics, manual grading of image answers |
| C5 Rewards & draw | Threshold rewards, entitlements, manual draw, audit |

- **Exit criteria:** all acceptance criteria with Stage = C in [acceptance-criteria.md](acceptance-criteria.md).
- **Risks:** SQLite single writer under simultaneous submit — early load spike test.

## Stage D — Administration and release 1.0

**Goal:** an operable release 1.0.

| Milestone | Content |
|---|---|
| D1 Branding | Branding and theme contract, global + per-quiz override |
| D2 Export | CSV export with formula-injection protection; Google Sheets contract only |
| D3 Retention | Retention and automatic jobs, archives, targeted deletion |
| D4 Plugin admin | Plugin enable/config UI, dependency checks |
| D5 Hardening & release | Security hardening, rate limits, configuration docs, load test 50 participants, backup & restore, acceptance tests |

- **Exit criteria:** all acceptance criteria with Stage = D, plus every AC-01 – AC-18 green ([acceptance-criteria.md](acceptance-criteria.md)).
- **Risks:** retention vs backups — verify backups cannot restore deleted PII indefinitely.

## FR → stage matrix

| Stage | Requirements |
|---|---|
| A | FR-01, FR-02, FR-03, FR-04, FR-07, FR-15 (single choice), FR-24 (basic) |
| B | FR-05 (base), FR-08, FR-09, FR-13, FR-15, FR-16, FR-17, FR-18, FR-19, FR-20, FR-21, FR-23, FR-24, FR-40, FR-41, FR-45 (type), FR-46 |
| C | FR-06, FR-10, FR-11, FR-12, FR-22, FR-25, FR-26, FR-27, FR-28, FR-29, FR-30, FR-31, FR-32, FR-33, FR-36, FR-37, FR-38, FR-39, FR-43, FR-45 (grading) |
| D | FR-05 (complete), FR-14, FR-34, FR-35, FR-42, FR-44 |

> Assignment of individual FRs to stages is derived from the spec's stage descriptions (§10); where
> the spec was silent (e.g. FR-35 privacy notice, FR-06 access code) the stage is a proposal.

## After v1.0 (LATER)

Google Sheets/Workspace connector, video question, more themes, SSO/OIDC, e-mail automation,
voucher codes, JSON export — each as a module, without kernel change.
