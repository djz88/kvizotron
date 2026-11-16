# Editing and deleting admin accounts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the Admins page each account can be renamed, get a new e-mail or password, be blocked or unblocked, and be deleted, never locking out the last admin or oneself, and ending the account's sessions.

**Architecture:** A domain service `app/domain/admins.py` holds the rules and the audit; `app/api/admin_users.py` gets routes per action and the inline login name; `admin/users.html` shows one card per account.

**Tech Stack:** Django, Jinja2, HTMX, pytest, Babel.

**Spec:** `docs/superpowers/specs/2026-11-12-admin-accounts-design.md`

## Global Constraints

- Every POST has `{{ csrf_input }}`; the page is behind `admin_required`.
- Audit actions `admin.renamed`, `admin.password_set`, `admin.blocked`, `admin.unblocked`, `admin.deleted` with `entity_id` = account id and no details holding the login, e-mail or password.
- Block and delete refuse the last active admin and one's own account; block, delete and a new password end that account's sessions (one's own new password keeps the current session).
- Login 1–150 characters, unique; password through `password_validation.validate_password`.
- Admin strings cs and en; AC-169; README range `AC-01…AC-169`.

## Review Focus

- Two admins: A blocks B, B's open session is refused at the next request; A cannot block or delete A.
- One active admin and one blocked: the active one cannot be blocked or deleted ("last active admin").
- A new password for oneself keeps one's session; for another ends theirs.
- A rename to an existing login (also differing only in case if the login is case-insensitive at login) is refused, the field keeps the typed text.
- Deleting an account that created quizzes leaves the quizzes and their pages working.

---

### Task 1: Domain service

**Files:** Create `app/domain/admins.py`; Test `tests/domain/test_admins.py`.

**Interfaces — Produces:**
- `class AdminRefused(Exception)` with subclasses `LastAdmin`, `OwnAccount`, `LoginTaken`, `LoginInvalid`.
- `rename(admin, login: str, *, actor_id: str) -> None`
- `set_password(admin, password: str, *, actor_id: str, keep_session_key: str | None = None) -> None` (validates with `validate_password`, raises `django.core.exceptions.ValidationError`)
- `set_active(admin, active: bool, *, actor_id: str) -> None`
- `delete(admin, *, actor_id: str) -> None`
- `end_sessions(admin, *, keep_session_key: str | None = None) -> int`

- [ ] **Step 1: Failing tests:** rename saves and audits `admin.renamed` without the login; rename to a taken login → `LoginTaken`; empty or 151 characters → `LoginInvalid`; set_password changes the hash, audits without the password, ends the account's sessions but keeps `keep_session_key`; weak password → `ValidationError`, nothing saved; set_active False/True audits blocked/unblocked; block of self → `OwnAccount`; block of the last active admin → `LastAdmin` (a blocked second admin does not count); delete of self → `OwnAccount`; delete of the last active admin → `LastAdmin`; delete removes the account and its sessions, quizzes with its `created_by` stay; docstring of the delete test `AC-169:`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_admins.py -q` — Expected: FAIL
- [ ] **Step 3: Implement**; sessions: `Session.objects` rows whose decoded `_auth_user_id` is the account's id; all writes in `transaction.atomic()`.
- [ ] **Step 4: Run** `uv run pytest tests/domain -q` — Expected: PASS
- [ ] **Step 5: Commit** `feat(admins): rename, password, block and delete an admin account (domain)` with the spec and plan.

### Task 2: The Admins page

**Files:** Modify `app/api/admin_users.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/users.html`, `app/api/locale/cs/…`, `app/plugins/theme_default/assets/theme.css` if a class is new; Test `tests/api/test_admin_users.py`, `tests/api/test_request_limits.py` (an `admin_id` argument if missing).

**Interfaces — Consumes:** Task 1. **Produces:** routes `admins/<uuid:admin_id>/login` (`admin_user_login`, GET/POST, inline name pattern of `admin_banks.bank_name`), `admins/<uuid:admin_id>/password` (`admin_user_password`, POST), `admins/<uuid:admin_id>/active` (`admin_user_active`, POST, field `active` = `1`/`0`), `admins/<uuid:admin_id>/delete` (`admin_user_delete`, GET confirmation, POST delete).

- [ ] **Step 1: Failing tests:** the page shows per account the login with a pencil, the e-mail form, a password field, Block/Unblock and Delete, and a "Blocked" mark; one's own row has no Block and no Delete; rename via HTMX and without JS (`?edit=login-<id>`); a taken login → 400 with the message and the typed text; new password for another ends its session (a second client is redirected to login) and for oneself keeps the session; block → that admin's client is logged out and cannot log in; refusals of the last admin and of oneself → 409 with the message; delete asks for confirmation (GET) and deletes on POST; every form has a CSRF token.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_admin_users.py -q` — Expected: FAIL
- [ ] **Step 3: Implement**; refusals render the page with a `notice` at the top.
- [ ] **Step 4: Run** `uv run pytest tests/api tests/test_wiring.py -q` — Expected: PASS
- [ ] **Step 5: Translations** `make messages`, cs filled; `uv run pytest tests/test_translations.py -q` — Expected: PASS
- [ ] **Step 6: Commit** `feat(admins): edit, block and delete accounts on the Admins page`

### Task 3: Documentation and checks

- [ ] **Step 1:** AC-169 (all five actions, the two refusals, sessions ended, audit without personal data), related ADR-0014; README range; ADR-0014 addendum; `docs/_architecture/security.md` line on ending sessions; `app/domain/CLAUDE.md` line for `admins.py`; `app/api/CLAUDE.md` line for the Admins page.
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -q` then `make quality` — Expected: PASS, exit 0
- [ ] **Step 3: Browser check** on the throwaway instance: two admins in two contexts; rename by keyboard, new password, block (the other context is logged out), delete with confirmation; 1280 light cs and 390 dark.
- [ ] **Step 4: Commit** `docs: editing and deleting admin accounts (AC-169, ADR-0014)`
