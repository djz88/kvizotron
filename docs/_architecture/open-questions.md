# Open Questions

Items not decided in the spec (§13 "open for implementation detail, does not block architecture")
plus gaps found while decomposing it. Each must be documented and tested before v1.0.
Recommendations are proposals only; status changes via the linked ADR. Rows marked **Decided** are
resolved and kept for traceability.

| ID | Question | Recommendation | Linked ADR | Decide by | Owner |
|---|---|---|---|---|---|
| OQ-01 | Which Python version? | **Decided:** Python 3.15; verify dependencies before Stage A | [ADR-0022](adr/0022-python-version.md) | Stage A start | TBD |
| OQ-02 | Entity ID format? | **Decided:** UUIDv7; IDs are not secrets | [ADR-0023](adr/0023-id-format.md) | Stage A | TBD |
| OQ-03 | How is `attempt_token` signed? | **Decided:** HMAC via `django.core.signing`, one key, no rotation | [ADR-0024](adr/0024-attempt-token-signing.md) | Stage A | TBD |
| OQ-04 | Deadline boundary-second semantics (FR-11)? | **Decided:** whole boundary second accepted, server receive time, UI submits ~5 s early | [ADR-0025](adr/0025-deadline-boundary-second-semantics.md) | Stage C | TBD |
| OQ-05 | Tie-break for equal best scores (FR-27)? | **Decided:** admin chooses per run: shared place, earlier submission or random order | [ADR-0026](adr/0026-scoreboard-tie-break-rule.md) | Stage C | TBD |
| OQ-06 | Which demo alternative provider proves AC-02? | **Decided:** test-only auth provider; second persistence provider LATER | [ADR-0027](adr/0027-demo-alternative-persistence-provider.md) | Stage A | TBD |
| OQ-07 | Upload limits? | **Decided:** 15 MB upload per file; stored WebP, 1600 px, at most 700 KB; participant images 2 GB per run; admin SVG basic check | [ADR-0028](adr/0028-upload-limits.md) | Stage B | TBD |
| OQ-08 | Default retention period? | **Decided:** 90 days after close, pre-filled, quick select 30/90/180 days, 1/3 years | [ADR-0029](adr/0029-default-retention.md) | Stage C | TBD |
| OQ-09 | Rate-limit thresholds (login, access code, submit)? | **Decided:** login 5, failed code 10, submit 120 per minute, in the application | [ADR-0030](adr/0030-rate-limit-thresholds.md) | Stage D | TBD |
| OQ-10 | Public links to archived run results? | **Decided:** off by default, per-run switch | [ADR-0031](adr/0031-public-links-to-archived-results.md) | Stage C | TBD |
| OQ-11 | Import and export formats? | **Decided:** human overview CSV + full CSV for export and import; JSON export later as a module | [ADR-0032](adr/0032-csv-schema.md) | Stage B | TBD |
| OQ-12 | Who enforces "no going back" (FR-17) and "reveal after each question" (FR-23)? | **Decided:** the page enforces no going back; immediate solutions only without scoreboard and rewards | [ADR-0035](adr/0035-immediate-solutions-only-without-competition.md) | Stage B | TBD |
| OQ-13 | When can a run merge scoreboards of several revisions? | **Decided:** equal max points; admin sees the differences and decides | [ADR-0008](adr/0008-scoreboard-revision-modes-default-separate.md) | Stage C | TBD |
| OQ-14 | How are numeric answers entered and compared? | **Decided:** numeric input field; server accepts `,` and `.`; optional tolerance, absolute or in percent | [plugins/question-types.md](plugins/question-types.md#numeric-answers) | Stage B | TBD |
