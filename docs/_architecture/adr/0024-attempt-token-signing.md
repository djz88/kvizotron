---
status: accepted
date: 2026-11-05
---

# ADR-0024: Attempt token signing mechanism

## Context and Problem Statement

[ADR-0009](0009-server-authoritative-scoring-signed-token-idempotent-submit.md) requires a signed
`attempt_token`: a ticket issued at attempt start that stops a participant from changing their start
time, time limit, assigned questions or revision. The signing algorithm is not specified.

The token is strictly necessary only in the no-retention mode, where nothing is stored in the
database. Security is proportionate to a quiz, not an election.

## Decision Drivers

* One code path for all retention modes
* Minimal code and configuration
* Proportionate security

## Considered Options

* Signed token in all modes, HMAC via itsdangerous, one key
* No token: database record plus a random per-attempt secret
* Signed token with a key list for rotation

## Decision Outcome

Chosen option: "Signed token in all modes, HMAC via itsdangerous, one key", because it keeps a single
code path and matches the spec, ADR-0009 and AC-08 with very little code.

Rules:

* One signing key, supplied through secrets. No `kid` and no rotation mechanism.
* The token is signed, not encrypted: it never contains solutions or personal data.
* Time limits are enforced by the server ([ADR-0010](0010-strict-server-side-deadline.md)).

### Consequences

* Good, because both retention modes share one mechanism
* Good, because it also works when only aggregate scores are stored
* Bad, because it adds one dependency
* Bad, because changing the key invalidates attempts in progress, so it is changed when no run is open
* Bad, because in no-retention mode a token can be resubmitted until it expires; this is harmless because that mode has no scoreboard or draw

### Confirmation

[AC-08](../acceptance-criteria.md) tamper tests.

## More Information

Resolves [OQ-03](../open-questions.md). Key handling: [../../deployment.md](../../deployment.md).
[ADR-0036](0036-django-web-framework-and-orm.md) replaces itsdangerous with `django.core.signing`, so no
extra dependency is needed; the rules above stay.
