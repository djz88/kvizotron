---
status: accepted
date: 2026-11-10
---

# ADR-0058: Four request-limit buckets, a start limit, and what a refusal looks like

## Context and Problem Statement

[ADR-0030](0030-rate-limit-thresholds.md) fixed the values of three limits (login, wrong access code, submission) and left open how each is counted and what a refused request sees. Until D5 only the access-code limit existed. [TD-029](../TECH_DEBT.md) had also found that a start request without a cookie creates a participant and an attempt each time, so one client could fill the database. Uploads and test links were left to D5 ([ADR-0044](0044-preview-and-test-links.md), [ADR-0047](0047-image-answer-photo-visibility.md)). Which public routes need a limit, and which do not, had never been checked.

## Decision Drivers

* About 50 people behind one address start and submit together and must never be refused at the default values
* One address must not lock an administrator out for everyone else
* A limit exists to bound guessing and writes, so each limit counts what it protects
* Single process with threads, no extra service ([ADR-0030](0030-rate-limit-thresholds.md), [ADR-0036](0036-django-web-framework-and-orm.md))
* A route added later must not silently be left without a limit

## Considered Options

* Four named buckets over a sliding minute in one module, each counting what it protects
* The same, with login counted by name only
* Limits in Caddy
* A limit on every request of an address

## Decision Outcome

Chosen: four named buckets in `app/api/rate_limit.py`, a sliding window of 60 seconds, one lock and one dictionary in process memory, with the values and counting below. They replace `code_limit.py`.

| Bucket | Counts | Key | Default | Variable |
|---|---|---|---|---|
| `login` | failed administration logins | login name (trimmed, lower case) and address | 5 per minute | `KVZ_LOGIN_ATTEMPTS_PER_MINUTE` |
| `code` | wrong access codes | address | 10 per minute | `KVZ_CODE_ATTEMPTS_PER_MINUTE` |
| `submit` | every submit request, once per attempt | address | 120 per minute | `KVZ_SUBMITS_PER_MINUTE` |
| `start` | every start request | address | 300 per minute | `KVZ_STARTS_PER_MINUTE` |

The bucket `login_address` (failed logins of all names from one address, 30 per minute, `KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE`) is not in this table; it was added later by [ADR-0060](0060-login-reservation-and-address-ceiling.md).

* `login` and `code` count failures only, so a correct login or code is never refused for the typos of somebody else. The login key holds the address, so one address cannot lock an account for the others. A correct login from an address whose bucket for that name is full is refused too, with that same 429 message, because the check comes before the password is looked at; the refusal ends when the window does.
* `submit` and `start` count every request, because their point is to bound writes and rows. `submit` is one POST per attempt (`/a/<id>/submit`), not one per question, so 120 per minute covers 50 people finishing in the same minute many times over. `start` closes [TD-029](../TECH_DEBT_archive.md): a client without a cookie can create at most `KVZ_STARTS_PER_MINUTE` participants and attempts per minute from one address. 300 is a choice, not a measurement; `make load` proves 50 starts from one address.
* The check is the first thing the view does, before a lookup, a row or a cookie. A refused request is not counted again.
* A refusal answers status 429 with `Retry-After: 60`. A public page shows a translated message in cs, en or uk (a fragment for HTMX, a page otherwise); the administration login shows the login form again with a "too many attempts, try again in a minute" message, in cs or en. Which locale a refusal uses was a known limit, closed by [ADR-0060](0060-login-reservation-and-address-ceiling.md) ([TD-084](../TECH_DEBT_archive.md)).
* Every public route that accepts a POST is listed in `tests/api/test_request_limits.py` with its bucket or a written reason why it has none, and the test fails for a route that is missing from the list and for an entry whose route no longer exists. The reasons are summarised in [security.md](../security.md#limits-of-public-routes). The routes that need a bucket have one; the others write no row or file without a signed token, or only read.
* Counters live in process memory and reset on a restart. The application runs as one process on purpose; a second worker would count on its own. Idle keys are swept once 1000 are tracked.
* The client address is the first `X-Forwarded-For` value, else `REMOTE_ADDR`. The header is trusted only because the application is reachable through Caddy alone (the compose topology), and Caddy replaces any value a client sends with the real address. Behind another proxy in front of Caddy all clients would share that proxy's address.

### Known limit

Login is limited per name and address, so one address can try five wrong passwords a minute for every name in turn. A ceiling per address across names was not added here; it would need its own value and a decision about a shared office address. [ADR-0060](0060-login-reservation-and-address-ceiling.md) added it ([TD-081](../TECH_DEBT_archive.md)). Passwords are Argon2id with a length rule ([ADR-0014](0014-local-admin-auth-argon2id-equal-roles.md)).

### Proxy keep-alive

Found by the load test: gunicorn closes an idle keep-alive connection after 2 seconds, and a POST that Caddy sent on a connection closed at that moment was reset and answered 502. Caddy now closes its idle upstream connections after 1 second (`transport http { keepalive 1s }` in `deploy/Caddyfile`), so it never reuses one that gunicorn is about to close. Considered and rejected: raising gunicorn's `--keep-alive` above Caddy's idle limit, which leaves the same race at a larger number and ties two files together, and having Caddy retry the POST, which could write twice. Other resets by gunicorn still surface as 502 ([TD-087](../TECH_DEBT.md)); a test compares the two values ([TD-088](../TECH_DEBT.md)).

### Consequences

* Good: 50 people behind one address start and submit at the default values, tested with the real limiter and in `make load`.
* Good: a new public route that takes a POST cannot be added without a decision about its limit.
* Good: no extra service and no change to the proxy beyond the keep-alive.
* Bad: a restart resets the counters, and a second process would count separately.
* Bad: at 300 starts per minute one address can still create 300 rows a minute.
* Bad: one address can spray many names (closed by [ADR-0060](0060-login-reservation-and-address-ceiling.md)).

### Confirmation

`tests/api/test_rate_limit.py`, `test_login_limit.py`, `test_play_limits.py` and `test_request_limits.py` ([AC-129](../acceptance-criteria.md) to [AC-131](../acceptance-criteria.md)), `tests/test_deploy_headers.py` ([AC-133](../acceptance-criteria.md)); `make load` for 50 clients behind one address ([AC-139](../acceptance-criteria.md)).

## More Information

Refines [ADR-0030](0030-rate-limit-thresholds.md). Refined by [ADR-0060](0060-login-reservation-and-address-ceiling.md): since the follow-up to D5 the login slot is reserved before the password is checked, a fifth bucket `login_address` limits one address across names (closing [TD-081](../TECH_DEBT_archive.md)), and a refusal is in the language of the form ([TD-084](../TECH_DEBT_archive.md)). Variables: [configuration.md](../../configuration.md).
