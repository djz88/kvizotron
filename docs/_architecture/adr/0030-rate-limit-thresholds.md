---
status: accepted
date: 2026-11-05
---

# ADR-0030: Rate-limit thresholds

## Context and Problem Statement

The spec requires limits on login, access-code attempts and submissions, without values. Limits must
slow down guessing and abuse, but must not block an event where about 50 people on one shared Wi-Fi
(one public IP) submit at the same time.

## Decision Drivers

* Abuse prevention
* Events behind a shared IP must work
* No additional infrastructure

## Considered Options

* Simple limits in the application, in process memory
* Limits on login and access code only
* Limits in the reverse proxy (Caddy)

## Decision Outcome

Chosen option: "Simple limits in the application, in process memory", because it needs no extra service
and can count only failed access-code attempts.

| Action | Default limit | Counted per |
|---|---|---|
| Login | 5 per minute | account + IP |
| Failed access code | 10 per minute | IP |
| Submission | 120 per minute | IP |

Values are configurable.

### Consequences

* Good, because 50 participants behind one IP can submit together at the defaults, with each participant sending once; repeats of the automatic submission after a failure can add sends ([ADR-0060](0060-login-reservation-and-address-ceiling.md), [TD-091](../TECH_DEBT.md))
* Good, because no extra service or custom proxy build is needed
* Bad, because a restart resets the counters
* Bad, because it works only with a single application process
* Bad, because the limit alone does not protect the disk; that is handled by image compression and the per-run limit ([ADR-0028](0028-upload-limits.md))

### Confirmation

Load test with 50 submissions from one IP ([AC-15](../acceptance-criteria.md)). The client IP must be
taken correctly from the reverse proxy.

## More Information

Resolves [OQ-09](../open-questions.md). Refined by [ADR-0058](0058-rate-limit-buckets.md): the failed-only login keyed by name and address, a start limit and what a refusal looks like, and again by [ADR-0060](0060-login-reservation-and-address-ceiling.md): a login slot reserved before the password is checked and a ceiling per address.
