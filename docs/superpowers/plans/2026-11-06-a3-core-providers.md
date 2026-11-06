# A3 Core Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The application runs on its own `persistence.sqlite` and `auth.local` providers, found through entry points, with a kernel-owned admin user model, Argon2id passwords, Django sessions and CLI commands for the first admin and password reset; a test-only auth provider proves AC-02.

**Architecture:** The project becomes an installable package so its `pyproject.toml` entry points register its own modules. Providers are read while settings load: the persistence provider fills `DATABASES`, the auth provider names `AUTHENTICATION_BACKENDS`. The user model lives in the kernel, so auth providers share one table.

**Tech Stack:** Python 3.15, Django 6.1.3 (`contrib.auth`, `contrib.sessions`, `contrib.contenttypes`), argon2-cffi, uv_build, pytest.

**Spec:** `docs/_architecture/providers/auth-local.md`, `docs/_architecture/providers/persistence-sqlite.md`, `docs/_architecture/security.md`, `docs/_architecture/data-model.md`, `docs/plugin-api.md`, ADR-0014, ADR-0023, ADR-0027, ADR-0036, ADR-0037, AC-02.

## Global Constraints

- New pinned runtime dependency: `argon2-cffi==25.1.0`. Build backend: `uv_build` with a `>=0.13,<0.14` bound.
- `PASSWORD_HASHERS` holds only `Argon2PasswordHasher`.
- Provider files read while settings load (`manifest.py`, `provider.py`) **MUST NOT** import Django at module level.
- Entity IDs are UUIDv7 (`uuid.uuid7`), including the admin user.
- Tests do not use the network. The test-only provider lives under `tests/fixtures/` and never enters the image (`.dockerignore`).
- Passwords never appear in logs, audit details, command arguments or output.
- `make test`, `make lint`, `make quality` need uv >= 0.13; if the local uv is older, run them in the `python:3.15-slim` container.
- **Commit only after the command's exit code is checked to be 0.** A pipe or a script that continues after a failure does not count; this caused commits with failing lint in A2.

## Decisions this plan makes

The spec leaves these open. All are the planner's calls, not user decisions.

- **Admin session lifetime:** 12 hours (`SESSION_COOKIE_AGE = 43200`), `SameSite=Lax`, `HttpOnly`. The spec requires expiration without a value.
- **Password rule:** at least 10 characters and not on Django's common-password list, enforced by the CLI. The spec is silent.
- **Password input:** interactive prompt, or `--password-stdin` for scripts. No password argument, because arguments are visible in the process list and shell history.
- **Model fields:** the user model extends `AbstractBaseUser` with `id`, `login`, `is_active`, `created_at`. Django names the hash column `password`, so `data-model.md` changes from `password_hash`. No e-mail, no permissions: all admins are equal (ADR-0014).
- **Manifest gains** `auth_backend` (dotted class path) and `persistence` (`module:Class`). A provider of `auth` or `persistence` **MUST** declare the matching field.
- **`/healthz`** calls `PersistenceProvider.healthcheck()`, which also reports a vanished database file. This resolves the A1 deferred minor.

## Out of scope, with the place it goes

- Login and logout pages, and authorisation of `/admin/`: A4, together with the first admin UI. FR-07 is complete only then.
- Login attempt limiting: D5 per the roadmap (ADR-0030).
- `database is locked` retry around submission: A4, where the submission transaction first exists. `IMMEDIATE` and the busy timeout are already set.
- Creating further admins: A4 admin UI. The model already allows many.

## Review Focus

- `init_admin` when an admin already exists: refused, and the existing account is untouched. Test in Task 3.
- Reset for an unknown login, or an empty or weak password: refused with a message, no traceback, no audit row, password unchanged. Test in Task 3.
- An existing admin session after a password reset: no longer authenticated. Test in Task 3.
- An inactive admin with the correct password: refused by every auth provider. Test in Task 2.
- The database file disappearing while the application runs: `/healthz` returns 503 and no empty file is created. Test in Task 1.

---

### Task 1: Installable package and `persistence.sqlite`

**Files:**
- Create: `app/providers/__init__.py`, `app/providers/persistence_sqlite/__init__.py`, `.../manifest.py`, `.../apps.py`, `.../provider.py`, `tests/contracts/persistence.py`, `tests/contracts/test_sqlite_persistence.py`
- Modify: `pyproject.toml`, `uv.lock`, `Dockerfile`, `app/contracts/__init__.py`, `app/kernel/manifest.py`, `app/kernel/discovery.py`, `app/settings.py`, `app/api/health.py`, `tests/kernel/test_discovery.py`, `tests/integration/test_startup_verification.py`, `tests/test_health.py`, `docs/plugin-api.md`, `docs/_architecture/providers/persistence-sqlite.md`

**Interfaces:**
- Produces:
  - `pyproject.toml`: `[build-system]` with `uv_build`, `[tool.uv.build-backend] module-name = "app", module-root = ""`, `package = false` removed, `[project.entry-points."kvizotron.modules"] "persistence.sqlite" = "app.providers.persistence_sqlite.manifest:MANIFEST"`
  - `Manifest.persistence: str | None`, `Manifest.auth_backend: str | None`
  - `app.contracts.REQUIRED_CAPABILITIES = {"persistence"}`
  - `app.kernel.discovery.load_persistence(modules: list[Manifest]) -> PersistenceProvider`; raises `StartupError` for a bad path or a contract violation, naming the module
  - `app.providers.persistence_sqlite.provider.SqliteProvider`: `id`, `database_settings() -> dict` (reads `KVZ_DB_PATH`, raises `StartupError` naming it when missing), `healthcheck() -> bool`
  - `settings.KVZ_PERSISTENCE`; `DATABASES = {"default": KVZ_PERSISTENCE.database_settings()}`

- [x] **Step 1: Write failing tests.**

```python
# tests/kernel/test_discovery.py: the `site` fixture hides the project's own entry points
# (filter by ep.dist.name == "kvizotron") and patches REQUIRED_CAPABILITIES to empty, so existing
# assertions keep their meaning.
def test_installed_project_provides_required_modules():  # unfiltered: "persistence.sqlite" in ids
def test_provider_of_persistence_must_declare_class(site):      # match module id
def test_load_persistence_bad_path_names_module(site):          # StartupError
def test_load_persistence_contract_violation_names_module(site):

# tests/contracts/persistence.py, class PersistenceContract: subclasses set `provider`
def test_satisfies_protocol(self): ...
def test_settings_name_an_engine_and_database(self): ...
def test_healthcheck_true_on_a_working_database(self, db): ...
def test_transaction_rolls_back(self, transactional_db): ...    # exception inside atomic: no row

# tests/contracts/test_sqlite_persistence.py
class TestSqlite(PersistenceContract): ...
def test_file_database_uses_wal_and_immediate(tmp_path):        # subprocess: PRAGMA journal_mode == "wal"
def test_missing_db_path_names_variable():                      # StartupError match KVZ_DB_PATH

# tests/test_health.py
def test_healthz_uses_provider(client, monkeypatch):            # healthcheck False -> 503
def test_vanished_database_file_gives_503_and_is_not_recreated(tmp_path):
    # subprocess: migrate, delete the file, GET /healthz == 503, file still absent
```

- [x] **Step 2: Run `make test`.** Expected: FAIL at the new imports.

- [x] **Step 3: Implement packaging.** Update `pyproject.toml`, run `uv lock`. In `Dockerfile`: `uv sync --frozen --no-dev --no-install-project`, then `COPY manage.py` and `COPY app`, then `uv sync --frozen --no-dev`, so dependency layers stay cached.

- [x] **Step 4: Implement the provider and wiring.** Move the `OPTIONS` values from `app/settings.py` into `SqliteProvider.database_settings()` unchanged. `healthcheck()`: `False` when a file-based path does not exist, otherwise `select 1`; a `django.db.Error` gives `False` and logs the exception type only. Import Django inside the method. `health()` calls `settings.KVZ_PERSISTENCE.healthcheck()`.

- [x] **Step 5: Adjust `test_modules_cli_lists_toggles_and_refuses`:** its fake provider uses `provides=["retention"]`, because `persistence.sqlite` is now real. Assertions stay.

- [x] **Step 6: Run `make quality` and `make smoke`.** Expected: exit 0. Smoke proves the entry points work in the image.

- [x] **Step 7: Update docs** (`plugin-api.md`: manifest fields; `persistence-sqlite.md`: package path if needed). Commit.

### Task 2: Admin user model, `auth.local`, sessions, AC-02

**Files:**
- Create: `app/kernel/migrations/0002_adminuser.py` (generated), `app/providers/auth_local/__init__.py`, `.../manifest.py`, `.../apps.py`, `.../backends.py`, `tests/contracts/authentication.py`, `tests/contracts/test_local_auth.py`, `tests/contracts/test_auth_test_provider.py`, `tests/contracts/auth_test_suite.py`, `tests/fixtures/auth_test_site/kvz_auth_test/` (`__init__.py`, `manifest.py`, `apps.py`, `backends.py`), `tests/fixtures/auth_test_site/kvz_auth_test-1.0.0.dist-info/` (`METADATA`, `entry_points.txt`), `tests/integration/test_auth_switch.py`, `tests/kernel/test_admin_user.py`
- Modify: `pyproject.toml`, `uv.lock`, `app/contracts/__init__.py`, `app/kernel/models.py`, `app/kernel/discovery.py`, `app/settings.py`, `docs/_architecture/data-model.md`, `docs/_architecture/security.md`, `docs/_architecture/providers/auth-local.md`

**Interfaces:**
- Consumes: `Manifest.auth_backend` from Task 1.
- Produces:
  - `app.kernel.models.AdminUser(AbstractBaseUser)`: `id: UUIDField` default `uuid.uuid7`, `login` unique (`USERNAME_FIELD`), `is_active`, `created_at`; manager method `create_admin(login: str, password: str) -> AdminUser`
  - `settings`: `AUTH_USER_MODEL = "kernel.AdminUser"`, `AUTHENTICATION_BACKENDS` from the active auth provider, `INSTALLED_APPS` starts with `contenttypes`, `auth`, `sessions`, kernel; `MIDDLEWARE` adds `SessionMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware`
  - `app.contracts.REQUIRED_CAPABILITIES = {"auth", "persistence"}`
  - `app.providers.auth_local.backends.LocalBackend(ModelBackend)`
  - `tests.contracts.authentication.AuthenticationContract`: subclasses set `backend` and implement `account() -> tuple[str, str]`, which returns a usable login and secret

- [x] **Step 1: Write failing tests.**

```python
# tests/contracts/authentication.py; all with the db fixture
class AuthenticationContract:
    def test_satisfies_protocol(self):
    def test_correct_credentials_return_the_user(self):
    def test_wrong_secret_returns_none(self):
    def test_unknown_login_returns_none(self):
    def test_inactive_account_returns_none(self):      # correct secret, is_active False
    def test_get_user_returns_the_user(self):
    def test_get_user_unknown_id_returns_none(self):
    def test_get_user_inactive_returns_none(self):

# tests/contracts/test_auth_test_provider.py: nested pytest of auth_test_suite.py with
# auth_test_site on PYTHONPATH and KVZ_PROVIDER_AUTH=auth.test; assert "8 passed"

# tests/kernel/test_admin_user.py
def test_password_is_stored_with_argon2id(db):         # password.startswith("argon2$argon2id$")
def test_password_never_stored_in_clear(db):
def test_id_is_uuid7(db):                              # pk.version == 7
def test_login_is_unique(db):                          # IntegrityError
def test_several_admins_are_independent(db):
def test_no_email_field():                             # "email" not in model field names
def test_session_settings():                           # age 43200, SameSite Lax, HttpOnly True
def test_session_survives_until_password_changes(client, db):
    # force_login; get_user(client).is_authenticated; set_password + save; now anonymous

# tests/integration/test_auth_switch.py (AC-02)
def test_two_auth_providers_without_selection_abort():  # exit != 0, "KVZ_PROVIDER_AUTH" in stderr
def test_selected_provider_decides_after_restart():
    # same database. auth.test: fixed token works, local password refused.
    # Restart with auth.local: local password works, token refused
def test_test_provider_is_not_in_the_image_context():   # .dockerignore does not admit tests/
def test_missing_auth_backend_class_aborts_at_startup(): # auth_backend="nope.X": import app.wsgi fails naming the module
```

- [x] **Step 2: Run `make test`.** Expected: FAIL at the new imports.

- [x] **Step 3: Add `argon2-cffi`, implement `AdminUser`, generate the migration** with `manage.py makemigrations kernel`.

- [x] **Step 4: Implement `auth.local` and settings.** Add its entry point to `pyproject.toml`. Settings: `PASSWORD_HASHERS`, session and CSRF cookie flags (`SESSION_COOKIE_AGE = 43200`, `SESSION_COOKIE_SAMESITE = "Lax"`, `CSRF_COOKIE_SAMESITE = "Lax"`), `AUTH_PASSWORD_VALIDATORS` with `MinimumLengthValidator` (`min_length: 10`) and `CommonPasswordValidator`. Discovery rejects a provider of `auth` without `auth_backend`. `verify_startup()` calls `django.contrib.auth.get_backends()` and checks each against `AuthenticationProvider`, turning failures into `StartupError` naming the module.

- [x] **Step 5: Implement the test-only provider** under `tests/fixtures/auth_test_site/`: fixed token `test-only-token`, looks up the kernel user by login, refuses inactive accounts (ADR-0027).

- [x] **Step 6: Run `make quality` and `make smoke`.** Expected: exit 0.

- [x] **Step 7: Update docs.** `data-model.md`: `admin_user` fields and `password`. `security.md`: state session lifetime and the password rule. Commit.

### Task 3: First admin and password reset CLI

**Files:**
- Create: `app/providers/auth_local/passwords.py`, `app/providers/auth_local/management/__init__.py`, `.../management/commands/__init__.py`, `.../commands/init_admin.py`, `.../commands/reset_admin_password.py`, `tests/providers/__init__.py`, `tests/providers/test_auth_local_cli.py`
- Modify: `deploy/smoke.sh`, `docs/deployment.md`, `docs/_architecture/providers/auth-local.md`

**Interfaces:**
- Consumes: `AdminUser.objects.create_admin` from Task 2, `app.kernel.audit.record`.
- Produces: `manage.py init_admin <login> [--password-stdin]`; `manage.py reset_admin_password <login> [--password-stdin]`; `app.providers.auth_local.passwords.read_password(options, stdin, *, user=None) -> str` raising `CommandError` (interactive input asks twice; validates with `validate_password`).

- [x] **Step 1: Write failing tests** with `call_command`, passing `stdin=io.StringIO(...)`.

```python
def test_init_creates_first_admin_and_audits(db):       # login works; AuditEvent action "admin.created"
def test_init_refused_when_an_admin_exists(db):         # CommandError; count 1; old password still works; no new audit row
def test_init_rejects_weak_password(db):                # "short" -> CommandError; no user, no audit row
def test_init_rejects_empty_password(db):
def test_reset_changes_password_and_audits(db):         # new works, old fails; action "admin.password_reset"
def test_reset_revokes_existing_sessions(client, db):   # force_login, reset, get_user(client) anonymous
def test_reset_unknown_login_refused(db):               # CommandError; no audit row
def test_reset_rejects_weak_password_and_keeps_old(db):
def test_reset_reactivation_is_not_implied(db):         # inactive stays inactive
def test_password_absent_from_output_and_audit(db, capsys): # secret not in stdout, stderr or details_json
def test_commands_have_no_password_argument():          # parser has no "--password" option
def test_password_stdin_strips_only_the_newline(db):    # "secret with space \n" keeps the trailing space
```

- [x] **Step 2: Run `make test`.** Expected: FAIL, unknown command.

- [x] **Step 3: Implement `passwords.py` and both commands.** State and audit commit in one `transaction.atomic`. Audit uses `actor_type="cli"`, `entity_type="admin"`, `entity_id=str(user.pk)`, and no login in details. A password change alone revokes sessions (ADR-0036), so the session table is not touched.

- [x] **Step 4: Extend `deploy/smoke.sh`:** `modules list` shows `auth.local` and `persistence.sqlite`; `init_admin` via `--password-stdin` with a generated password exits 0; a second run exits non-zero.

- [x] **Step 5: Run `make quality` and `make smoke`.** Expected: exit 0.

- [x] **Step 6: Update docs.** Add both commands to `docs/deployment.md` using `docker compose run --rm -it`. Commit.

### Task 4: A2 leftovers and milestone close

**Files:**
- Create: `app/kernel/migrations/0003_*.py` (generated)
- Modify: `app/kernel/discovery.py`, `app/kernel/lifecycle.py`, `app/kernel/models.py`, `tests/kernel/test_lifecycle.py`, `tests/integration/test_startup_verification.py`, `docs/_architecture/roadmap.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `load_modules` and `verify_startup` from A2.
- Produces: `app.kernel.discovery.installed_module_ids() -> set[str]`; `PluginInstallation.Status.INACTIVE`.

- [x] **Step 1: Write failing tests.**

```python
def test_broken_module_urls_stop_startup():              # urls="nope_missing" with app otherwise fine: import app.wsgi exit != 0, module id in last stderr line
def test_unselected_provider_is_inactive_not_missing():  # two auth providers, one selected: other's row INACTIVE
def test_removed_module_is_missing():                    # package gone: MISSING
```

- [x] **Step 2: Run `make test`.** Expected: 3 FAIL.

- [x] **Step 3: Implement.** `verify_startup()` resolves `django.urls.get_resolver().url_patterns` and turns failures into `StartupError` naming the module, using the same culprit logic as `app/kernel/bootstrap.py`. `_sync_installations` marks installed but unselected providers `INACTIVE`. Generate the migration.

- [x] **Step 4: Run `make quality` and `make smoke`.** Expected: exit 0.

- [x] **Step 5: Close the milestone.** In `roadmap.md` set A3 to Done with the merge date and A4 to Next. Update `CLAUDE.md` status and remove the `package = false` warning. Tick this plan's checkboxes. Commit.
