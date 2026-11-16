---
status: accepted
date: 2026-11-07
---

# ADR-0044: Preview stores nothing, and a test link is a hidden run fixed to one version

## Context and Problem Statement

`FR-13` asks for a preview without writing results and a separate test mode ([ADR-0017](0017-preview-vs-isolated-test-mode.md)). Organisers want to see a draft as a participant would, and let a colleague without an account try a chosen version. ADR-0017 expected a `test_mode` flag on each attempt, which every later query would have to filter.

## Decision Drivers

* A test attempt must never reach results, statistics, rewards or a quiz's state, including in code written later
* A pair of play paths would drift apart
* A test must keep being scorable, while a draft keeps changing

## Considered Options

* A flag on each attempt
* A run of kind `test`, hidden by the default manager
* A separate attempt table

## Decision Outcome

Chosen option: "A run of kind `test`, hidden by the default manager", because the existing start, submit, check and scoring code applies unchanged, and a query must ask on purpose to see a test run.

* `QuizRun.objects` and `quiz.runs` return normal runs, and `QuizRun.all_kinds` returns all. A test run has no number.
* A link (`test_link`) is fixed to the version chosen when it is created: a published or older revision, or an immutable copy of the draft in status `TEST_COPY`, which `QuizRevision.objects` hides. Only a draft passing the publication check can be copied.
* A link ends by cancelling (its run closes), by an end time (checked at start, submit and check) or by archiving the quiz.
* The link's address answers the same way, with status 200, whether it is invalid, cancelled or ended. A 404 would write the path, and with it the token, to the log.
* Preview builds an unsaved `Attempt` from a signed token. Nothing is stored, including when the draft is incomplete: what cannot be shown says so in its place.

### Consequences

* Good, because results built in Stage C cannot meet a test run by accident
* Good, because preview and test links use the participants' pages
* Bad, because a query on `Attempt` across runs must filter on the run's kind itself
* Bad, because the token is kept readable, so that the admin can copy the link again; a leak shows questions and lets people play in a run that counts for nothing

### Confirmation

[AC-45](../acceptance-criteria.md) to [AC-48](../acceptance-criteria.md).

## More Information

Refines [ADR-0017](0017-preview-vs-isolated-test-mode.md). Playing a link needs no limit of its own: a test link only reads and starts an attempt through the limited `start` route ([ADR-0058](0058-rate-limit-buckets.md)).

### Addendum 2026-11-12: the shown address of a link

The address of a test link was built from the address the admin uses. An admin who reaches the server one way and sends testers another (a forwarded port, a public name) can now set, per link, the scheme, host and port the link is shown and copied with (`test_link.shown_origin`, empty means the admin's own address). Only the display changes: the app serves the link on whatever address reaches it, and the admin is responsible for the new address leading to this server. The value is checked to be an origin only (http or https, host name, IPv4 or bracketed IPv6, port 1–65535) and the audit `test_link.address_changed` holds neither the address nor the token. [AC-167](../acceptance-criteria.md).
