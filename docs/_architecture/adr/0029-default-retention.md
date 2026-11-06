---
status: accepted
date: 2026-11-05
---

# ADR-0029: Default retention period

## Context and Problem Statement

FR-34 gives example retention periods but no default. The default decides how long personal data
(nicknames, e-mails, answers, images) stay stored when nobody changes it.

## Decision Drivers

* Data minimisation
* Enough time to hand out rewards and finish grading
* Quick to change in the admin UI

## Considered Options

* 90 days pre-filled
* 30 days pre-filled
* No default, the admin must choose

## Decision Outcome

Chosen option: "90 days pre-filled", because it covers rewards and grading while personal data do not
accumulate.

Rules:

* The period runs from closing the run.
* The run form shows the pre-filled value with quick-select buttons: 30 days, 90 days, 180 days,
  1 year, 3 years.
* Other values allowed by FR-34, including permanent retention, remain available as a separate choice.

### Consequences

* Good, because personal data are removed without any admin action
* Good, because a different period takes one click
* Bad, because 90 days is longer than a one-off event needs
* Bad, because results disappear after 90 days unless the admin chooses longer

### Confirmation

[AC-14](../acceptance-criteria.md).

## More Information

Resolves [OQ-08](../open-questions.md). Policy: [../../privacy.md](../../privacy.md).
