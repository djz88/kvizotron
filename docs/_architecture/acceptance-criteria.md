# Acceptance Criteria v1.0

Selection of critical scenarios that **MUST** pass before release 1.0. "Stage" = earliest stage in
which the criterion can be verified ([roadmap.md](roadmap.md)).

| ID | Scenario | Criterion | Related | Stage |
|---|---|---|---|---|
| AC-01 | Plugin extension | Adding a sample new question type to the deployment without changing kernel code; editor, validation, rendering and evaluation register correctly. | ADR-0002, ADR-0021, FR-16 | A |
| AC-02 | Auth/persistence | A test-only alternative authentication provider passes the same contract test suite; switching happens on restart, never uncontrolled at runtime. Persistence contract tests run against the SQLite provider; a second persistence provider is LATER. | ADR-0036, ADR-0027 | A |
| AC-03 | Translations | A `cs+uk` quiz can be published only with complete translations; English is not required unless enabled for the quiz. | FR-03, ADR-0018 | B |
| AC-04 | Revisions | Participant starts an attempt on revision 1, admin publishes revision 2; the submission is evaluated against revision 1 and stays in history. | FR-09, FR-19, ADR-0006 | B |
| AC-05 | Run repeat | After close and restart a new `run_id` exists, the new run's public scoreboard is empty, the old run's results are viewable in admin (unless retention expired). | FR-12, ADR-0007 | C |
| AC-06 | Revision merge | With different max points a common scoreboard cannot be enabled; with equal max points the admin sees the differences between revisions and can knowingly enable it, which is audited. | FR-30, ADR-0008 | C |
| AC-07 | Deadline | Server rejects submission after deadline even with the browser kept open; without deadline submission works until manual close. With limit 10:00:00, a submission received at 10:00:00.9 is accepted and at 10:00:01.0 rejected. | FR-11, ADR-0010, ADR-0025 | C |
| AC-08 | Tampering | Modified `score`, `started_at`, `revision_id` or manifest in the client payload do not affect the result or cause rejection. | ADR-0009, ADR-0024 | A |
| AC-09 | No retention | After submission the participant sees the score, but no result or participant PII is created in the DB; scoreboard and draw are unavailable. | FR-31, ADR-0012 | C |
| AC-10 | Scoring & thresholds | Five equally weighted questions, 4 correct = 80 %; a 90 % threshold reward is not granted. | FR-25, FR-26 | C |
| AC-11 | Resume | An in-progress attempt can be restored locally in the same browser; start time and assigned questions cannot be changed. | FR-22, ADR-0020 | C |
| AC-12 | Draw | Test attempts are excluded; admin sees the eligible snapshot, audit and history of repeated draws; drawing is never automatic. | FR-13, FR-37, FR-38, ADR-0013 | C |
| AC-13 | Import | A multi-language CSV with errors imports as a draft, errors listed per row, media referenced by URL are not confused with local files. | FR-40, FR-41, ADR-0019 | B |
| AC-14 | Retention | The job deletes/anonymises data after the configured period and keeps permissible non-personal metadata; an older run does not disappear just because a new one was created. | FR-34, ADR-0012 | D |
| AC-15 | Operations | Simulation of 50 concurrent participants including simultaneous submissions with images causes no lost results, no duplicate write of the same attempt and no unhandled DB lock errors; restore from backup verified. | ADR-0005, ADR-0015 | D |
| AC-16 | Image answer | A question with 2 automatic and 0–8 manual points shows 2 of 10 after submission and the attempt is pending. The public scoreboard is hidden, the draw refused and thresholds not evaluated until grading finishes. A non-admin cannot open the image. A disguised file is rejected and EXIF is removed. A 15 MB phone photo is accepted and stored as at most 700 KB; after the per-run limit further images are refused. | FR-45, ADR-0033, ADR-0028 | C |
| AC-17 | Module requirements | Selecting a module shows its required settings; a conflicting setting blocks publication with an explanation; satisfying it allows publication. | FR-46, ADR-0034 | B |
| AC-18 | Immediate solutions | Enabling reveal after each question in a run with a visible scoreboard or rewards is blocked with an explanation; in a run without them the participant sees the solution after each question. | FR-23, ADR-0035 | B |
