# Editing and deleting admin accounts — design

Date: 2026-11-12. Status: draft for approval.

## Why

The Admins page (`/admin/users`) can create an account and change any account's e-mail. An admin who forgot a password, a login with a typo, a temporary account (`claude-debug`) or a person who left cannot be handled without `manage.py`.

## What (the user's choices)

On the Admins page, for each account:

1. **Rename the login**: a pencil on the login, the same inline editing as names elsewhere (AC-160). 1–150 characters, unique; quizzes and the audit refer to the id, so nothing else changes.
2. **Change the e-mail**: as today.
3. **Set a new password**: one password field and a button; the same strength rules as when creating (`validate_password`). Setting one's own password keeps one's own session.
4. **Block / unblock**: a blocked account (`is_active = False`) cannot log in; it stays in the list marked "Blocked".
5. **Delete**: a confirmation page as for other deletions, then the account is gone. Quizzes it created stay; their footer without its own contact no longer shows its e-mail. The audit keeps the id.

Safety, for every action that can lock someone out (block, delete):

- **Not the last active admin**: refused with a message.
- **Not one's own account**: refused, and the buttons are not shown on one's own row.
- **Logged out everywhere**: blocking, deleting and a new password end every session of that account (for one's own new password, every other session).

Audit: `admin.renamed`, `admin.password_set`, `admin.blocked`, `admin.unblocked`, `admin.deleted`, with the id only: no login, e-mail or password (project rule: no personal data in the audit).

## Not in scope

- Roles or permissions (all admins are equal, ADR-0014).
- A password reset by e-mail; changing one's password with the old one.
- Undo of a deletion.

## Calls made here

- The rules (last admin, own account, sessions) live in a domain service `app/domain/admins.py`; the page only calls it (`app/api/CLAUDE.md`: no rules in the API).
- Sessions are ended by deleting the account's rows in the session store; Django would also refuse an old session after a password change or block, but deleting them makes "logged out everywhere" immediate and visible in tests.
- A refused action is shown as a message at the top of the page with status 409 (last admin, own account) or 400 (invalid input), the typed login kept.
