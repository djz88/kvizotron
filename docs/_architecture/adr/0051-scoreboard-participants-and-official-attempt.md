---
status: accepted
date: 2026-11-08
---

# ADR-0051: A visible scoreboard identifies browsers, one official attempt each, anonymised live names

## Context and Problem Statement

`FR-27`, `FR-29` and `FR-30` ask for a public scoreboard per run with an admin-chosen visibility, columns and order, one counted attempt per participant, and revision modes. [ADR-0049](0049-participants-and-access-code.md) creates a participant only when a run forbids repeating or asks for a name or e-mail, so a run that allows repeating knows nothing that joins two attempts of one browser. [ADR-0026](0026-scoreboard-tie-break-rule.md) fixed the ties and [ADR-0008](0008-scoreboard-revision-modes-default-separate.md) the revision modes. Open were who a row is, which of a person's attempts counts, how names show while a run is live, and where the anonymous label comes from.

## Decision Drivers

* One person is one row, also when the run allows playing again
* Nothing public before the admin turns it on; existing quizzes change nothing
* No e-mail, internal id or cookie value on a public page
* Organisers want a motivating live board without exposing names, and the official order at the end
* The board is a projection, not a source of truth

## Considered Options

* A visible board sets the participant cookie whatever the repeat rule; one official attempt per participant
* Every attempt is a row when repeating is allowed
* Rows joined by nickname

## Decision Outcome

Chosen option: "A visible board sets the participant cookie whatever the repeat rule; one official attempt per participant", because only the browser joins attempts without asking for anything, and a nickname is neither unique nor trusted.

Rules:

* A run whose scoreboard visibility is not `hidden` sets `kvz_p_<run>` and stores a participant at start, like a run that forbids repeating. A run with repeating allowed and the scoreboard hidden still sets no cookie. Turning the board on mid-run affects starts from then on; earlier attempts without a participant are each their own anonymous row.
* The scoreboard settings are declared by the module `results.local` (port `result_view`), inherited global → quiz and copied onto the run when it is planned or opened (`QuizRun.results_json`), with a random seed for the `random` tie policy. Visibility, names during the run, unnamed participants, columns, the second sort and the archived switch may change later, as they change only what is shown; the official attempt, the tie policy and the revision mode stay as opened.
* A row is the participant's official attempt among submitted, graded attempts: the best score or the first submitted. Of equal scores of one participant the earlier counts. Switched, abandoned, unsent and pending attempts never count; while any attempt of the run waits for grading the public board is hidden ([ADR-0033](0033-image-answer-question-type.md)). Test attempts never appear.
* Order: score, then the second sort (submission time, or duration only under the data profile `detailed`), then the tie policy of ADR-0026.
* With "anonymised" names, a live board shows every row with the anonymous label and a number that stays with the browser for the run; after the run ends, nicknames are shown. A participant without a nickname is shown with the label or left out; a left-out participant still sees their own place, and ranks keep the gap.
* The anonymous label is a field of the quiz per language (`Quiz.anonymous_label`) with `NN` for the number, default "Hráč NN" / "Player NN" / "Гравець NN". It follows the quiz live, like its title.
* Merging revisions is an admin action on a run whose revisions have equal maximum points, after seeing their differences; it is audited and can be undone. It is not a preset value.
* A visible board is refused together with the data profile `none` and with answers after each question ([ADR-0035](0035-immediate-solutions-only-without-competition.md)).
* The own row is marked from the viewer's cookie, never from the name. The public board is cached for 5 seconds; the page refreshes every 15 seconds and stops when the run has ended and nothing waits.

### Consequences

* Good, because playing again from the same browser never adds a second row
* Good, because a live board can motivate without showing who is who
* Bad, because a run that allows repeating gets a cookie as soon as its board is visible
* Bad, because another browser or a cleared cookie is still a new row
* Bad, because rows from before the board was turned on cannot be joined

### Confirmation

AC-06, AC-16, AC-18, AC-70, AC-81 to AC-85.

## More Information

Refines [ADR-0049](0049-participants-and-access-code.md). Ending the public view of an archived run when retention expires ([ADR-0031](0031-public-links-to-archived-results.md)) comes with the retention job in D3.

Refined by [ADR-0056](0056-retention-job-summary-held-runs.md): since D3 the public view of a run ends when its data are deleted.
