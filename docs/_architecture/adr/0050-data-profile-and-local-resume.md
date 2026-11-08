---
status: accepted
date: 2026-11-08
---

# ADR-0050: One data profile per run, a retention period without a job, local resume on by default

## Context and Problem Statement

`FR-31`, `FR-33` and `FR-34` ask an organiser to keep only the data an event needs, down to nothing, and to record how long a run's data are kept. `FR-22` asks for a short-lived copy of unsubmitted answers in the browser. [ADR-0012](0012-configurable-retention-profiles-and-stateless-mode.md) chose profiles and a stateless mode, [ADR-0020](0020-browser-local-resume-untrusted.md) an untrusted local resume that an admin allows, and [ADR-0046](0046-stored-answers-and-who-sees-them.md) a separate `store_answers` setting that covers only answers. Open was how those fit together, what "nothing" means for a row that exists while an attempt is played, and whether resume stays opt-in.

## Decision Drivers

* An organiser keeps what the event needs and nothing else; "nothing" leaves no row, name, e-mail, answer or duration after a submission
* No setting combination the server would silently ignore
* The browser copy is never trusted for score, identity, start time or which questions were given
* An existing quiz changes what it stores only through the default duration
* The deleting job belongs to D3 and must not be half-built here

## Considered Options

* One profile setting replacing `store_answers`, a period copied onto the run, resume on by default
* A profile next to `store_answers`
* Stateless mode as a separate switch

## Decision Outcome

Chosen option: "One profile setting replacing `store_answers`, a period copied onto the run, resume on by default", because one value says what an attempt leaves behind and the form can refuse what it rules out.

Rules:

* `data_profile` has four values: `none`, `score` (default), `answers`, `detailed`. It replaces `store_answers`. It is declared in the domain catalogue next to the other quiz-wide settings, inherited global → quiz, copied onto the run when it is planned or opened (`retention_json`), editable on the plan form and fixed once the run opens, the path of the participant rules in [ADR-0049](0049-participants-and-access-code.md). It has no question level, as it concerns the whole attempt ([ADR-0042](0042-settings-inherited-and-declared.md)).
* `none` keeps nothing per attempt, only a count of submitted attempts on the run (`stateless_submitted`). `score` keeps the score, the submission time and the answers a person must grade, photos included. `answers` adds every answered question. `detailed` adds the attempt's duration; under the other values no duration is stored.
* The upgrade turns `store_answers=all` into `answers` and `images` into `score`, at every level where it was set, and copies the converted value of its quiz onto every existing run. Attempts already stored keep what they have; their frozen settings still read `store_answers`.
* A stateless attempt lives until its submission. Start creates the row, with the assigned questions and no participant. Submission computes the score, deletes the row and the chain of attempts it replaced, increments the count in the same transaction and shows the score on the page. No tombstone is kept: a token with a valid signature and no row gets `attempt_gone` (410) with a plain page, without a score. An attempt never submitted stays an anonymous row without answers until D3.
* The form refuses `none` together with repeating forbidden, a name or e-mail asked, `answers_visibility` other than `admins`, a photo question in the revision, or public photos, and names the setting in conflict. A running `none` run keeps its revision when a new one has a photo question, with a notice. Under `none` no private result link is offered.
* A test run follows the live profile of its quiz, except that live `none` with a photo question counts as `score` (a test must be able to hold a photo). A test run does not increment the count.
* `retention_period` is 30, 90 or 180 days, 1 year, 3 years or permanent, counted from the run's close, default 90 days ([ADR-0029](0029-default-retention.md)). It is inherited like the profile and copied onto the run, but stays editable on a running or ended run, because it changes no data collected. It is a value only: no job reads it until the `retention` provider arrives in D3. The privacy page shows the global default, says a quiz may set another, and says deletion comes in a later version.
* `local_resume` (`on`, `off`, default `on`) is declared by the module `quiz_flow` and inherited global → quiz. A change applies to attempts started afterwards. This reverses the opt-in of [ADR-0020](0020-browser-local-resume-untrusted.md): the copy holds no name, e-mail or photo, ends with the attempt and never outlives 24 hours, so on is the safer default for a participant who loses a page, and the quiz page tells people that answers are kept on this device.
* While an attempt is open the page keeps its token, answers (not photos, name or e-mail), step and expiry in `localStorage` under a key for the run. The expiry is the attempt's end, else 24 hours from the start. The copy is deleted on submission, on a refusal saying the attempt is over (`X-Kvz-Drop-Copy`) and on expiry (every page load sweeps the expired copies of all runs).
* `POST /r/<run>/resume` takes the token in the body, never in the address. The token is proof that the attempt was started, so resuming needs no access-code cookie, as a running attempt already resumes after the code changed (ADR-0049). The server checks run, status, abandonment, time and that the run accepts submissions, then renders the attempt's own questions in their own order. Stored answers that no longer fit are dropped by the page, and everything is re-validated at submission. With the name asked before the start, a resumed page asks for it at the end, since it was not kept.

### Consequences

* Good, because one value tells an organiser and a participant what an attempt leaves behind
* Good, because `none` leaves no personal or answer row, and the form refuses what it would break
* Good, because a reload or a lost connection no longer loses the answers entered
* Bad, because a participant cannot see a stateless score again if the response never arrived
* Bad, because answers stay in the browser for up to 24 hours, readable by another person on a shared device
* Bad, because the period is only a record until D3, and an unsubmitted anonymous row stays until then
* Bad, because rankings by time need `detailed`

### Confirmation

AC-09, AC-11, AC-77 to AC-80.

## More Information

Refines [ADR-0012](0012-configurable-retention-profiles-and-stateless-mode.md) and [ADR-0020](0020-browser-local-resume-untrusted.md), and replaces the setting `store_answers` of [ADR-0046](0046-stored-answers-and-who-sees-them.md). Deleting and anonymising by period, targeted deletion and backup retention stay in D3. The scoreboard, draws, statistics and export that depend on the profile arrive in C4, C5 and D2.
