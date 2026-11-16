---
status: accepted
date: 2026-11-04
---

# ADR-0014: Local admin accounts with Argon2id and equal permissions

## Context and Problem Statement

Admins need authentication without external identity infrastructure.

## Decision Drivers

* Self-hosted
* Secure password storage (OWASP)
* Simplicity

## Considered Options

* Local accounts, Argon2id, all admins equal
* Role-based access control
* SSO/OIDC

## Decision Outcome

Chosen option: "Local accounts, Argon2id, all admins equal", because it is the simplest secure option for small teams.

### Consequences

* Good, because no external dependency
* Good, because auth is a provider — SSO can be added LATER
* Bad, because no fine-grained permissions in v1.0

### Confirmation

Contract tests for `AuthenticationProvider`.

## More Information

FR-07; [../providers/auth-local.md](../providers/auth-local.md). "Authorised admin" in FR-42 means any logged-in admin; every export of personal data is audited. Implemented on Django auth ([ADR-0036](0036-django-web-framework-and-orm.md)).

### Addendum 2026-11-12: changing and deleting accounts

Because all admins are equal, any admin can rename another account, set its e-mail or password, block it or delete it (AC-169). Two rules keep the installation usable: nobody blocks or deletes their own account, and the last active admin cannot be blocked or deleted. Blocking, deleting and a new password delete that account's stored sessions, so it is logged out everywhere at once; one's own new password keeps the current session. The rules live in `app/domain/admins.py`; the audit carries only the account id.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
