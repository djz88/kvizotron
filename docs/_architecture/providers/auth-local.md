# Provider: auth-local

| | |
|---|---|
| Contract | `AuthenticationProvider` |
| Package | `app/providers/auth_local/` |
| Stage | A ([roadmap](../roadmap.md)) |
| Decision | [ADR-0014](../adr/0014-local-admin-auth-argon2id-equal-roles.md) |

## Requirements

- `FR-07` Multiple local admin accounts with identical permissions; username/password, login and logout.

## Behaviour

- Password hashing, cookie flags, session expiration and login limiting: see
  [../security.md](../security.md).
- Built on Django auth with a kernel-owned user model; the provider supplies the authentication backend.
- Sessions are Django database sessions. A password change invalidates that account's sessions
  ([ADR-0036](../adr/0036-django-web-framework-and-orm.md)).
- First admin is created once by `init_admin`; `reset_admin_password` sets a new password
  for a locked-out admin, revokes that account's sessions and writes to the audit log
  ([../../deployment.md](../../deployment.md)).
- Exactly one auth provider active per process; switching requires a controlled restart.

## Data owned

No own tables. It uses `admin_user` and `django_session` ([../data-model.md](../data-model.md)).

## Extension points (LATER)

SSO/OIDC as another `AuthenticationProvider` without kernel change.
