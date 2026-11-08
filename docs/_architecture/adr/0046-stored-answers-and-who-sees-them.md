---
status: accepted
date: 2026-11-07
---

# ADR-0046: Stored answers, who sees them, a private link and a public walkthrough

## Context and Problem Statement

A person's grading needs stored answers, and a participant needs a way to learn a score given after they left. Once answers are stored, organisers also want to settle unclear answers and to walk through a quiz publicly after a run. Answers are personal enough that an existing quiz must not start keeping them.

## Decision Drivers

* An existing quiz behaves the same with default settings
* The organiser chooses, per installation or per quiz
* Nothing reaches a public page during a run, and no answer names a participant
* No account, as participants have none until C2

## Considered Options

* One table of stored answers, two settings and a signed link
* Storing every answer always, and filtering what is shown
* E-mailing the final score

## Decision Outcome

Chosen option: "One table of stored answers, two settings and a signed link", because it stores only what was chosen, and needs no personal data.

* `store_answers` is `images` (default) or `all` (replaced by the data profile in [ADR-0050](0050-data-profile-and-local-resume.md); `all` became `answers`, `images` became `score`), frozen on the attempt at start. A row exists for a question that needs a person, and with `all` for each answered question. A replaced attempt has none.
* `answers_visibility` is `admins` (default), `participant` or `public`. Anything but `admins` needs `store_answers=all`. The quiz and global forms refuse the combination; a global change falling into it behaves as `admins`, with a warning, like a flow conflict in [ADR-0041](0041-draw-rows-and-flow-settings.md).
* `grading_view` chooses `by_question` or `by_attempt`. All three settings have global and quiz scope, as each applies to an attempt or a quiz as a whole.
* `/v/<token>` is a signed reference to one attempt, with no end date until retention arrives in D3. It shows the score, whether it is final, own answers and photo as settings allow, and correct answers only as the attempt's reveal settings allow. An invalid token gets status 200 and one message, and a refused photo 204, so a token never reaches the log. The same device remembers the link in `localStorage` per quiz.
* `/q/<slug>/r/<run>/answers` exists only after a normal run ended, with public answers or a question whose photos are public. With public photos alone it shows only those questions' prompts and approved photos. Each type summarises its answers through `summarize`, covered by the shared contract tests. Text is counted by the question's own comparison. An admin viewing the page can hide a value; the stored key is a hash, so free text never reaches the audit log.

### Consequences

* Good, because defaults change nothing, and the two public pages ask one module (`visibility`) what they may show
* Good, because a future type cannot skip the walkthrough
* Bad, because free text is shown until an admin hides it, which the settings page says
* Bad, because a private link has no end date until D3

### Confirmation

[AC-58](../acceptance-criteria.md), [AC-59](../acceptance-criteria.md), [AC-60](../acceptance-criteria.md).

## More Information

Photos have their own setting: [ADR-0047](0047-image-answer-photo-visibility.md). Results and export of answers remain in C4 and D2.
