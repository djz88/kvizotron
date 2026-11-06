# A4 Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin logs in, writes a single-choice quiz in cs/en/uk, publishes it, opens a run and gets a QR code; a participant opens the URL, picks a language, starts, submits and sees a score computed only by the server. Stage A closes: AC-01, AC-02 and AC-08 pass.

**Architecture:** `app/domain/` owns quizzes, revisions, runs and attempts and exposes services; `app/api/` holds thin views and page templates. Question types, scoring and the theme are plugins behind contracts, found through entry points like the A3 providers. Pages are server-rendered; HTMX swaps in the questions and the result, and the same forms work without JavaScript.

**Tech Stack:** Python 3.15, Django 6.1.3 (Jinja2 backend, built-in CSP middleware, `django.core.signing`), Pydantic, segno (QR), Django gettext with Babel for catalogues, HTMX 2.0.11 and Pico CSS 2.1.1 as vendored files, no build step.

**Spec:** `docs/_architecture/roadmap.md` (A4 row, FR → stage matrix), `docs/_architecture/acceptance-criteria.md` (AC-01, AC-02, AC-08), `docs/_architecture/modules/{domain,api-ui,contracts}.md`, `docs/_architecture/plugins/{question-types,scoring,theme-default}.md`, `docs/_architecture/architecture.md` §4–5, `docs/_architecture/data-model.md`, `docs/_architecture/security.md`, ADR-0006, ADR-0009, ADR-0018, ADR-0023, ADR-0024, ADR-0036, ADR-0037.

## Global Constraints

- All commands run in Docker. `d` below is the dev container wrapper `<scratchpad>/d`; `make smoke` runs on the host and starts its own containers. Never report a result as local.
- New pinned runtime dependency: `segno==1.6.6` (QR codes; pure Python, no dependencies). New pinned dev dependency: `babel==2.18.0` (extracts and compiles catalogues from Jinja2 and Python without system gettext). Vendored, unchanged, never from a CDN: `htmx.org@2.0.11` (0BSD), `@picocss/pico@2.1.1` (MIT), recorded in `THIRD_PARTY.md`.
- `public_payload()` and everything sent to a participant never contains the answer key. Score, solution and times from a client are never trusted.
- A published revision is never mutated. An attempt is evaluated against the revision pinned at its start.
- Entity IDs are UUIDv7 (`uuid.uuid7`). Secrets never are.
- Answers and personal data never reach logs or audit details. Passwords never appear anywhere.
- Every state-changing admin request is CSRF-protected and authorised on the backend. The public start and submit endpoints have no session, so they are `csrf_exempt` and rely on the signed token.
- Public UI in cs/en/uk, admin UI in cs/en. User-visible strings never hard-coded in one language.
- Views stay thin: rules live in `app/domain/` and modules. The kernel gets no quiz logic.
- Documentation in `docs/` is English; Czech is for `CLAUDE.md`, `README.md`, Makefile and Dockerfile comments.
- **Commit only after the command's exit code is checked to be 0.** Before each commit run `d make lint` and `d make test`; before the merge `d make quality` and `make smoke`.

## Decisions this plan makes

The spec leaves these open. All are the planner's calls, not user decisions.

- **UI texts (user decision):** Django gettext. Each app and plugin owns `locale/<lang>/LC_MESSAGES/django.{po,mo}`, which Django finds by itself. Both files are committed, so the Dockerfile does not change. `make messages` extracts and compiles with Babel. Source strings are English; `uk` is required only for public strings, because the admin UI is cs/en (FR-04).
- **Theme can replace any page (user decision):** theme modules load before `app.api` in `INSTALLED_APPS`, so a theme template with the same name wins. A theme therefore changes page structure too, not only the layout and CSS.
- **Frontend (user decision):** take what exists rather than write it: HTMX and Pico CSS, no build step. TypeScript is decided in B2, if the editors need custom scripts.
- **Play flow (user decision):** `POST /r/{run_id}/start` and `POST /a/{attempt_id}/submit` return HTML rather than the JSON proposed in `api-ui.md`, which is expressly not frozen. Token and submission key travel in hidden fields. `submission_key` comes from the server at start, so a double click or a retry sends the same key.
- **Contract change:** `render_admin(config, locales)` replaces `render_admin(config, locale)`; the UI language comes from the active Django translation, and `parse_admin(form, locales) -> config` is added, because an editor needs all selected languages on one form and AC-01 needs the plugin to read its own form. No release exists, so `CONTRACT_VERSION` stays `1.0`.
- **Form field naming:** a type's public inputs are named `<question id>:<field>`, where `id` is added by the domain to `public_config`. Values arrive as form strings, and a plugin converts them itself.
- **Module ids:** `question.choice_single` (type `choice.single`), `scoring.basic` (strategy `all_or_nothing`, 1 point by default), `theme.default`.
- **Option ids:** random `secrets.token_hex(4)`, so an id says nothing about the correct option. Editor shows 6 option rows; a row blank in all languages is dropped; at least 2 options.
- **Multilingual title:** `Quiz.title` is a JSON map locale → text. `data-model.md` changes accordingly.
- **Draft:** one `DRAFT` `QuizRevision` per quiz; `snapshot_json = {"questions": [...]}` is editable. Saving may be incomplete; publication validates each selected locale. Publishing sets the previous `PUBLISHED` to `SUPERSEDED`. Editing after publication copies the latest published questions into a new draft.
- **Published snapshot:** `{"title", "default_locale", "locales", "questions": [{"id", "type", "type_version", "scoring", "scoring_version", "settings": {"points": 1}, "definition"}]}`. Public pages read locales and title from the snapshot of the run's revision.
- **Slug:** locked after the first publication, because the URL and printed QR code must stay valid (FR-02).
- **Runs:** at most one `OPEN` run per quiz, enforced by a partial unique constraint. A run stays on the revision it was opened with; a newer revision needs a new run. Run-revision switching belongs to C1.
- **Stored data:** only the score on `Attempt` (the most data-minimal profile, FR-33). No `participant`, `attempt_question`, `attempt_answer`, `run_revision` tables yet: they arrive with their stages.
- **Token lifetime:** 24 hours from start. C1 replaces it with the deadline and attempt limit.
- **Missing answer:** a question left blank earns 0. An unknown question id in the payload is ignored. A malformed answer to a known question rejects the whole submission with 400 and changes nothing.
- **Errors:** a translated message per code, with statuses: `invalid_request` 400, `invalid_answer` 400, `invalid_token` 403, `not_found` 404, `run_closed` 409, `already_submitted` 409, `submission_key_used` 409, `attempt_expired` 410, `revision_unavailable` 503. Client-sent `score`, `started_at`, `revision_id` and manifest fields are ignored. `not_found` and `invalid_request` have the same treatment.
- **Lock retry:** `with_retry` around the submission transaction: 3 tries, backoff 50 ms and 100 ms, only on `OperationalError` containing `locked`.
- **Admin language:** `?lang=` stored in the session, otherwise `Accept-Language`, otherwise `cs`. **Public language:** `?lang=`, otherwise `Accept-Language`, each limited to the quiz's locales, otherwise its default.
- **Plugin validation messages** are the plugin's English `ValueError` text, shown after a localised "question N, language X" prefix. Localising them is B2 editor work.
- **Admin accounts in UI:** list and create only. Deactivation and password change wait for D4; `reset_admin_password` covers lockouts.
- **`createsuperuser` and `changepassword`:** `auth.local` overrides both to refuse and name `init_admin` / `reset_admin_password`. This resolves the A3 deferred minor. It needs `auth.local` ahead of `django.contrib.auth` in `INSTALLED_APPS`, because the first app wins a command name.

## Out of scope, with the place it goes

- Quiz duplicate and archive, revision history screen, FR-08 rest: B1.
- Other question types, strategy choice, ordering in editor, TypeScript decision: B2. Random order, reveal policy: B3. Preview and test mode: B5.
- Schedule, deadline, attempt limit, restart with copied config: C1. Participants, access code: C2. Retention, stateless mode, `/privacy` content: C3. Results and scoreboard: C4.
- Branding: D1. Plugin admin screen: D4. Login and submit rate limits: D5.

## Review Focus

- Double click on submit, or a retry after a lost response: the same result, one stored score. Test in Task 3 and Task 4.
- A hand-made answer (unknown option, missing or odd field name, invalid key, oversized body): 400, no traceback, attempt can still be submitted. Test in Task 3 and Task 4.
- Admin closes the run while a participant is answering: submission refused with `run_closed`, and the page tells them. Test in Task 3 (service), Task 4 (page) and Task 6 (browser).
- `?lang=de`, or `?lang=en` on a quiz without English: the page falls back to a supported language rather than failing or showing blanks. Test in Task 4.
- Login with `next=https://evil.example.net/`: after login the admin stays on this site. Test in Task 5.

---

### Task 1: Question type, scoring and theme plugins

**Files:**
- Create: `app/plugins/__init__.py`, `app/plugins/questions/__init__.py`, `app/plugins/questions/choice_single/{__init__,manifest,apps,plugin}.py`, `app/plugins/questions/choice_single/jinja2/choice_single/{public,admin}.html`, `app/plugins/scoring/{__init__,manifest,apps,strategies}.py`, `app/plugins/theme_default/{__init__,manifest,apps,plugin,views,urls}.py`, `app/plugins/theme_default/assets/theme.css`, `app/api/__init__.py` if missing, `app/plugins/theme_default/jinja2/theme_default/layout.html`, `app/plugins/*/locale/`, `app/api/jinja.py`, `tests/test_translations.py`, `tests/contracts/theme.py`, `tests/contracts/test_choice_single.py`, `tests/contracts/test_scoring_basic.py`, `tests/contracts/test_theme_default.py`
- Modify: `pyproject.toml`, `uv.lock`, `Makefile`, `CLAUDE.md`, `app/settings.py`, `app/contracts/__init__.py`, `tests/contracts/question_type.py`, `tests/contracts/demo_question_suite.py`, `tests/fixtures/demo_site/kvz_demo_question/question.py`, `tests/kernel/` tests that assert the exact set of active modules

**Interfaces:**
- Produces:
  - `QuestionTypePlugin`: `render_admin(config, locales: Sequence[str]) -> str`, `parse_admin(form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON` (raises `ValueError`).
  - `ThemePlugin` protocol, port `"theme"` in `PORTS`: `id`, `version`, `layout_template() -> str`, `stylesheet_urls() -> Sequence[str]`.
  - `choice.single` definition: `{"prompt": {locale: str}, "options": [{"id": str, "text": {locale: str}}], "correct": option_id}`; public payload `{"prompt": str, "options": [{"id", "text"}]}`; answer `{"option": option_id}` with a string value.
  - Strategy `all_or_nothing`: `settings = {"points": n}`, default 1; `correct_count` 0 or 1.
  - Layout blocks `title`, `content`; context `locale`, `theme`. Templates translate with `_()`.
  - `app.api.jinja.environment(**options) -> jinja2.Environment`: `jinja2.ext.i18n` with Django's gettext callables, and a `url` global.
  - `make messages`: extracts each app's strings and compiles its catalogues.

- [x] **Step 1: Create branch `stage-a/a4-vertical-slice` from `main`, add `segno==1.6.6`, the dev dependency `babel==2.18.0` and the entry points of the three modules to `pyproject.toml`, run `d uv lock`.**

- [x] **Step 2: Write the failing contract tests**

Extend `QuestionTypeContract` with `admin_form` (a form that `parse_admin` turns into a definition passing `validate_definition`) and `locales = ["cs"]`:

```python
def test_admin_form_produces_valid_definition(self):
    config = self.plugin.parse_admin(self.admin_form, self.locales)
    for locale in self.locales:
        self.plugin.validate_definition(config, locale)

def test_render_admin_returns_html(self):
    assert "<" in self.plugin.render_admin(self.definition, self.locales)
```

`tests/contracts/test_choice_single.py` subclasses the contract with `answer_key_values = ['"correct"']` and adds:

```python
def test_public_payload_does_not_depend_on_correct_option(): ...  # equal for correct=a and correct=b
def test_render_public_does_not_depend_on_correct_option(): ...
def test_render_public_escapes_markup(): ...  # prompt "<script>x" appears as "&lt;script&gt;x"
def test_render_admin_escapes_markup(): ...
def test_public_inputs_are_named_by_question_id(): ...  # name="q1:option" with public_config id q1
def test_rejects_answer_with_unknown_option(): ...
def test_definition_incomplete_in_locale_is_refused(): ...  # uk prompt or option text blank -> ValueError for "uk", none for "cs"
def test_definition_with_fewer_than_two_options_is_refused(): ...
def test_parse_keeps_existing_option_ids_and_drops_blank_rows(): ...
def test_parse_generates_random_ids_for_new_rows(): ...
def test_parse_refuses_correct_pointing_at_blank_row(): ...
```

`test_scoring_basic.py` subclasses `ScoringStrategyContract` and adds `test_supports_only_choice_single` and `test_points_setting_scales_score` (`{"points": 3}` → 3.0 of 3.0). `tests/contracts/theme.py` defines `ThemeContract` (protocol satisfied, `layout_template()` loads through `django.template.loader.get_template`); `test_theme_default.py` applies it and adds `test_stylesheets_are_served` (GET each of `stylesheet_urls()` → 200, `text/css`).

`tests/test_translations.py` walks every `locale/` under `app/`:

```python
def test_public_catalogues_have_no_empty_translation(): ...  # cs, en, uk for api public strings and plugins
def test_admin_catalogues_have_no_empty_translation(): ...  # cs, en
def test_compiled_catalogue_matches_source(): ...  # .mo read by babel equals its .po
def test_catalogue_contains_every_string_in_the_code(): ...  # extract to tmp_path; no msgid missing from .po
def test_plugin_label_follows_active_language(): ...  # choice.single admin form under translation.override("en") vs "cs"
```

Update the demo fixture: `parse_admin` reads `prompt` and integer `answer`, `render_admin` uses `django.utils.html.escape`, `render_public` input is named `<id>:value`, and `validate_submission` and `evaluate` accept an integer or a string of digits. Add `admin_form` to its suite.

- [x] **Step 3: Run to verify they fail**

Run: `d uv run pytest tests/contracts -q`
Expected: FAIL with import errors for the new plugins and missing `parse_admin`.

- [x] **Step 4: Implement the contracts and three plugins**

Set `USE_I18N = True`, `LANGUAGE_CODE = "cs"`, `LANGUAGES` for cs, en, uk, and `TEMPLATES[0]["OPTIONS"]["environment"] = "app.api.jinja.environment"`. Manifests import no Django. `AppConfig.ready()` registers ports, like the demo fixture. `question.choice_single` declares `requires: ["scoring_strategy"]`, `activation_scope: ["global", "quiz"]`. Theme serves `pico.min.css` and `theme.css` through `urls` under `/m/theme.default/` with `FileResponse` and `Cache-Control: public, max-age=3600`, so no static-file pipeline is needed. The layout is mobile-first, has a visible focus style, a skip link, `<html lang="{{ locale }}">`, the name **Kvízotron**, and the slogan **„Zapni mozek. Spusť Kvízotron.“** as a translated string. It uses Pico's classless markup, and no inline style or script, because of the CSP in Task 4. Pico itself is vendored in Task 4; until then `theme.css` alone is served.

- [x] **Step 5: Run to verify they pass**

Run: `d uv run pytest tests/contracts tests/kernel -q`
Expected: PASS. Fix assertions on an exact module set by adding the new modules, never by weakening them.

- [x] **Step 6: Commit**

```bash
d make lint && d make test && git add -A && git commit -m "feat: add single choice, basic scoring and default theme plugins"
```

---

### Task 2: Domain models and authoring services

**Files:**
- Create: `app/domain/__init__.py`, `app/domain/apps.py`, `app/domain/models.py`, `app/domain/migrations/0001_initial.py`, `app/domain/authoring.py`, `app/domain/usage.py`, `tests/domain/__init__.py`, `tests/domain/test_authoring.py`, `tests/domain/test_models.py`, `tests/domain/test_usage.py`, `tests/domain/helpers.py`
- Modify: `app/settings.py`

**Interfaces:**
- Consumes: registry ports `question_type`, `scoring_strategy` from Task 1.
- Produces:
  - Models `Quiz(id, slug, title: dict, default_locale, supported_locales: list, featured, created_at)`, `QuizRevision(id, quiz, revision_no, status, snapshot_json, plugins_json, max_score: Decimal, checksum, published_at)`, `QuizRun(id, quiz, run_no, current_revision, status, opened_at, closed_at)`, `Attempt(id, run, revision, status, started_at, submitted_at, score, max_score, correct_count, duration_ms, submission_key)`.
  - `QuizRevision.Status`: `DRAFT, PUBLISHED, SUPERSEDED, ARCHIVED`. `QuizRun.Status`: `OPEN, CLOSED, ARCHIVED`. `Attempt.Status`: `IN_PROGRESS, SUBMITTED`.
  - `authoring.get_draft(quiz) -> QuizRevision`, `save_question(quiz, question_id: str | None, type_id: str, config: JSON) -> str`, `delete_question(quiz, question_id) -> None`, `validate_for_publication(quiz) -> list[Problem]`, `publish(quiz, *, admin_id) -> QuizRevision` (raises `PublicationError(problems)`), `open_run(quiz, *, admin_id) -> QuizRun` (raises `RunAlreadyOpen`, `NothingPublished`), `close_run(run, *, admin_id) -> None`.
  - `Problem(question_no: int | None, locale: str | None, code: str, detail: str)`.
  - `usage.question_type_usage(module_id) -> list[str]`, `usage.missing_plugin_problems() -> list[str]`, registered from `DomainConfig.ready()`.

- [x] **Step 1: Write the failing tests**

```python
# test_models.py
def test_slug_and_revision_number_are_unique(): ...
def test_published_revision_cannot_be_saved(): ...  # save() raises ImmutableRevision, row unchanged
def test_draft_revision_can_be_saved(): ...
def test_second_open_run_for_a_quiz_is_refused_by_the_database(): ...  # IntegrityError
def test_ids_are_uuid7(): ...  # .version == 7 for quiz, revision, run, attempt
def test_revision_with_attempts_cannot_be_deleted(): ...  # ProtectedError

# test_authoring.py
def test_publish_builds_snapshot_with_plugin_versions_and_checksum(): ...
def test_published_snapshot_contains_title_and_locales_at_publication_time(): ...  # later Quiz edit leaves snapshot unchanged
def test_publish_without_questions_is_refused(): ...  # code "no_questions"
def test_publish_with_missing_title_in_required_locale_is_refused(): ...  # code "title_missing"
def test_publish_with_incomplete_translation_is_refused_and_names_question_and_locale(): ...
def test_cs_uk_quiz_publishes_without_english(): ...
def test_publish_supersedes_previous_revision(): ...
def test_editing_after_publication_creates_new_draft_and_leaves_published_untouched(): ...
def test_max_score_is_sum_of_question_max_scores(): ...
def test_publish_is_audited_and_emits_quiz_published(): ...  # no answer key in audit details
def test_open_run_needs_published_revision(): ...
def test_open_run_uses_latest_published_and_numbers_runs(): ...
def test_second_open_run_raises_run_already_open(): ...
def test_closed_quiz_can_open_new_run_without_old_attempts(): ...
def test_close_run_is_audited_and_emits_run_closed(): ...

# test_usage.py
def test_question_plugin_used_by_open_run_cannot_be_disabled(): ...  # lifecycle.set_enabled raises ModuleInUse
def test_question_plugin_can_be_disabled_after_run_closes(): ...
def test_startup_problem_when_open_run_needs_uninstalled_type(): ...
```

`tests/domain/helpers.py` provides `make_quiz(locales=("cs",))`, `add_question(quiz, correct=...)`, `published_quiz(...)`, `open_quiz_run(...)`, shared by later tasks.

- [x] **Step 2: Run to verify they fail**

Run: `d uv run pytest tests/domain -q`
Expected: FAIL with `ModuleNotFoundError: app.domain`.

- [x] **Step 3: Implement models and services**

Add `"app.domain.apps.DomainConfig"` to `INSTALLED_APPS` directly: the domain is core, not a module. `QuizRevision.save()` compares with the stored row and raises `ImmutableRevision` unless that row is `DRAFT`; `publish` writes through the draft while it is still `DRAFT`, and moves the previous revision's status with `.filter().update()`. Checksum: sha256 of `json.dumps(snapshot, sort_keys=True, separators=(",", ":"))`. Partial unique constraint on `quiz` where `status="OPEN"`, unique `(quiz, run_no)`, `(quiz, revision_no)`, `submission_key`, index `(run, submitted_at)`. All foreign keys to revision and run are `PROTECT`. Generate the migration with `d uv run python manage.py makemigrations domain` (with `KVZ_SECRET_KEY`, `KVZ_DOMAIN` and `KVZ_DB_PATH` set to test values).

- [x] **Step 4: Run to verify they pass**

Run: `d uv run pytest tests/domain tests/integration -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
d make lint && d make test && git add -A && git commit -m "feat: add quiz, revision, run and attempt with authoring services"
```

---

### Task 3: Attempts: token and scoring services

**Files:**
- Create: `app/domain/tokens.py`, `app/domain/attempts.py`, `tests/domain/test_tokens.py`, `tests/domain/test_attempts.py`

**Interfaces:**
- Consumes: `tests/domain/helpers.py`, models and statuses from Task 2.
- Produces:
  - `tokens.issue(claims: AttemptClaims) -> str`, `tokens.verify(token: str) -> AttemptClaims` (raises `InvalidToken`); `AttemptClaims(run_id, revision_id, attempt_id, started_at, expires_at, manifest_hash)`; salt `kvizotron.attempt`.
  - `attempts.manifest_hash(snapshot: JSON) -> str`, `attempts.start(run: QuizRun) -> StartedAttempt(attempt, token, submission_key)`, `attempts.submit(attempt_id: UUID, token: str, answers: dict[str, dict[str, str]], submission_key: str) -> AttemptResult(earned_points, max_points, percentage, correct_count)`, `attempts.AttemptError(code)`, `attempts.with_retry(fn, tries=3, base_delay=0.05)`.

- [x] **Step 1: Write the failing tests**

```python
# test_tokens.py
def test_round_trip(): ...
def test_changed_token_is_refused(): ...  # each claim changed by re-encoding the payload part -> InvalidToken
def test_token_signed_with_other_salt_is_refused(): ...
def test_token_contains_no_solution(): ...  # base64-decoded token has no option id of the correct answer

# test_attempts.py
def test_start_on_closed_run_is_refused(): ...  # AttemptError("run_closed")
def test_submission_key_is_random_and_not_uuid7(): ...
def test_correct_answer_scores_full_points(): ...  # earned 1, max 1, percentage 100, correct_count 1
def test_wrong_answer_scores_zero(): ...
def test_blank_answer_scores_zero(): ...
def test_percentage_is_exact_before_rounding(): ...  # 4 of 5 questions -> exactly 80; 1 of 3 stays a Fraction
def test_attempt_stays_on_revision_after_new_publication(): ...  # new revision has other correct option; score follows the old one
def test_repeated_submit_with_same_key_returns_same_result(): ...  # second has different answers; same score; one write
def test_repeated_submit_with_other_key_is_already_submitted(): ...
def test_key_used_by_other_attempt_is_refused(): ...  # "submission_key_used"
def test_malformed_answer_is_refused_and_attempt_can_still_submit(): ...  # "invalid_answer": unknown option, missing field
def test_unknown_question_id_is_ignored(): ...
def test_token_of_other_attempt_is_refused(): ...  # "invalid_token"
def test_correctly_signed_token_with_other_revision_or_manifest_is_refused(): ...  # AC-08
def test_submit_after_run_closed_is_refused(): ...  # "run_closed"
def test_repeat_after_run_closed_still_returns_stored_result(): ...
def test_expired_token_is_refused(): ...  # patch timezone.now in app.domain.attempts; "attempt_expired"
def test_disabled_type_still_scores_stored_revision(): ...  # registry include_disabled path; disable by direct row update
def test_uninstalled_type_gives_revision_unavailable(): ...
def test_submit_emits_attempt_submitted_without_answers(): ...
def test_with_retry_retries_locked_then_succeeds(): ...
def test_with_retry_does_not_retry_other_errors(): ...
def test_with_retry_gives_up_after_three_tries(): ...
```

- [x] **Step 2: Run to verify they fail**

Run: `d uv run pytest tests/domain/test_tokens.py tests/domain/test_attempts.py -q`
Expected: FAIL with import errors.

- [x] **Step 3: Implement**

Order inside `submit`, because it decides correct replay behaviour:

1. Verify the token; its `attempt_id` must equal the given id.
2. Load the attempt; `run_id`, `revision_id` and `manifest_hash(revision.snapshot_json)` must equal the claims.
3. If `SUBMITTED`: same key returns the stored result, another key is `already_submitted`.
4. Now past `expires_at`, compared in whole seconds: `attempt_expired`. Run not `OPEN`: `run_closed`.
5. For each snapshot question with an answer: `validate_submission`, then `evaluate`, both through `registry.get(..., include_disabled=True)`, outside the transaction. `UnknownPort` is `revision_unavailable`.
6. In `with_retry`: `atomic()` with `Attempt.objects.filter(pk=..., status=IN_PROGRESS).update(...)`. Zero rows means a concurrent submit: go to step 3. `IntegrityError` on the key is `submission_key_used`. `events.emit("attempt.submitted", {...})` carries ids and the score only.

Scoring uses `Decimal(str(value))` and `Fraction` for the percentage; rounding happens only on display. `submission_key` comes from `secrets.token_urlsafe(16)`.

- [x] **Step 4: Run to verify they pass**

Run: `d uv run pytest tests/domain -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
d make lint && d make test && git add -A && git commit -m "feat: add attempt services with signed token and server scoring"
```

---

### Task 4: Public pages, play flow with HTMX, languages, CSP

**Files:**
- Create: `app/api/apps.py`, `app/api/i18n.py`, `app/api/locale/`, `app/api/rendering.py`, `app/api/public.py`, `app/api/play.py`, `app/api/jinja2/public/{landing,quiz,play,_questions,_result,_error,unavailable}.html`, `app/api/assets/htmx.min.js`, `app/api/assets/play.js`, `THIRD_PARTY.md`, `tests/api/__init__.py`, `tests/api/test_i18n.py`, `tests/api/test_public_pages.py`, `tests/api/test_play.py`, `tests/api/test_security_headers.py`, `tests/api/test_theme_guard.py`
- Modify: `app/settings.py`, `app/urls.py`

**Interfaces:**
- Consumes: `theme` port from Task 1; `QuizRun`, snapshot shape from Task 2; `attempts.*` from Task 3.
- Produces:
  - `i18n.PUBLIC_LOCALES = ("cs", "en", "uk")`, `i18n.ADMIN_LOCALES = ("cs", "en")`, `i18n.negotiate(request, allowed: Sequence[str], default: str) -> str`, `i18n.LocaleMiddleware` (activates the negotiated language for each request and calls `translation.deactivate()` after it; `/admin/` paths use `ADMIN_LOCALES`).
  - `rendering.page(request, template: str, context: dict, locale: str, status: int = 200) -> HttpResponse`: activates `locale` and adds `theme`, `locale`, `scripts`.
  - `rendering.question_html(question: JSON, locale: str) -> Markup`.
  - Routes `GET /`, `GET /q/<slug>`, `GET /q/<slug>/r/<uuid>`, `POST /r/<uuid>/start`, `POST /a/<uuid>/submit`, `GET /assets/<name>` (only the two named files).
  - Form fields of submit: `attempt_token`, `submission_key`, `lang`, and `<question id>:<field>`.
  - Status per error code: as in the decisions list. An `HX-Request` gets the partial; any other request gets the whole page, so play works without JavaScript.

- [x] **Step 1: Vendor the assets**

Download `htmx.org@2.0.11/dist/htmx.min.js` into `app/api/assets/` and `@picocss/pico@2.1.1/css/pico.min.css` with its `LICENSE.md` into `app/plugins/theme_default/assets/`, from the npm registry tarballs, verifying each tarball's `dist.integrity`. Record name, version, licence, source and sha256 in `THIRD_PARTY.md`. Keep the files unchanged. Add `theme.css` only for what Pico does not supply.

- [x] **Step 2: Write the failing tests**

```python
# test_i18n.py
def test_negotiate_prefers_query_then_accept_language_then_default(): ...
def test_negotiate_ignores_unsupported_values(): ...  # ?lang=de, quality values, malformed header
def test_language_does_not_leak_to_next_request(): ...  # ?lang=uk, then a request with no preference gets cs
def test_django_validation_messages_follow_language(): ...  # a required-field error differs between cs and en

# test_public_pages.py
def test_landing_lists_quizzes_with_open_run_only(): ...
def test_landing_shows_featured_first(): ...
def test_landing_without_quizzes_says_so(): ...
def test_quiz_page_shows_title_in_selected_language_and_start_form(): ...  # ?lang=uk: uk title, html lang="uk", no question yet
def test_quiz_page_offers_only_published_locales(): ...
def test_quiz_page_falls_back_for_unsupported_lang(): ...  # ?lang=de and ?lang=en on cs+uk quiz -> default, 200
def test_unknown_slug_is_themed_404(): ...
def test_quiz_without_open_run_says_not_running(): ...  # 404 page with translated text
def test_specific_run_page_of_open_run_works(): ...
def test_run_of_other_quiz_is_404(): ...
def test_closed_run_page_is_view_only(): ...  # no start form
def test_page_uses_revision_title_not_later_quiz_edit(): ...

# test_play.py
def test_start_returns_questions_in_language_with_token_and_key(): ...  # hidden attempt_token and submission_key
def test_start_html_has_no_answer_key(): ...  # identical apart from token and key for revisions differing only in correct
def test_start_html_escapes_admin_markup(): ...
def test_start_on_closed_run_is_409_with_translated_message(): ...
def test_start_on_unknown_run_is_404(): ...
def test_htmx_start_returns_partial_and_plain_start_returns_whole_page(): ...  # HX-Request header; <html only without it
def test_submit_shows_score_in_language(): ...  # form POST, 200, "1 / 1", 100 %
def test_tampered_score_started_at_revision_and_manifest_fields_do_not_change_result(): ...  # AC-08
def test_changed_token_is_403_and_attempt_stays_open(): ...  # AC-08
def test_double_submit_shows_same_score_once_stored(): ...
def test_invalid_key_is_400(): ...  # missing, shorter than 8, longer than 64, other characters than [A-Za-z0-9_-]
def test_malformed_answer_is_400_and_attempt_can_still_submit(): ...  # unknown option, field name without colon ignored
def test_oversized_body_is_400(): ...  # with settings DATA_UPLOAD_MAX_MEMORY_SIZE low; no traceback
def test_error_for_htmx_retargets_message_area(): ...  # HX-Retarget "#play-message", answers stay on screen
def test_submit_after_close_is_409_with_translated_message(): ...
def test_expired_attempt_is_410_with_translated_message(): ...
def test_get_is_405(): ...

# test_security_headers.py
def test_csp_blocks_inline_and_foreign_sources(): ...  # default-src 'self', object-src 'none', base-uri 'self', frame-ancestors 'none', form-action 'self'; no unsafe-inline, no unsafe-eval
def test_pages_have_no_inline_script_or_style(): ...  # no <script> without src, no style= on landing, quiz and play pages
def test_htmx_config_disables_eval_and_injected_styles(): ...  # meta htmx-config: allowEval false, includeIndicatorStyles false
def test_assets_are_served_with_right_type(): ...  # htmx.min.js and play.js as JavaScript
def test_other_asset_names_are_404(): ...  # ../settings.py, unknown

# test_theme_guard.py
def test_last_theme_cannot_be_disabled(): ...  # lifecycle.set_enabled raises ModuleInUse
def test_theme_template_overrides_page_of_same_name(tmp_path): ...  # fresh process, fixture theme ships public/landing.html; GET / uses it
```

- [x] **Step 3: Run to verify they fail**

Run: `d uv run pytest tests/api -q`
Expected: FAIL with import errors or 404.

- [x] **Step 4: Implement**

Add `"app.api.apps.ApiConfig"` and `i18n.LocaleMiddleware` (after the session middleware), and load theme modules before `app.api` in `INSTALLED_APPS`. CSP through Django's `django.middleware.csp.ContentSecurityPolicyMiddleware` and `SECURE_CSP`.

Forms use `hx-post`, `hx-target="#play"`, `hx-disabled-elt="find button"` and a normal `action`/`method`, so they also work without JavaScript. The meta `htmx-config` sets `allowEval: false`, `includeIndicatorStyles: false` and `responseHandling` that swaps 2xx and 4xx. Errors carry `HX-Retarget: #play-message`, so answers stay on screen; `#play-message` is an `aria-live="polite"` region.

`play.js` has one job, which HTMX lacks: on `htmx:sendError` and `htmx:responseError` it puts the translated text from `data-network-error` into `#play-message` through `textContent`. It gets no unit test because the project has no JS runner; Task 6 verifies it in a real browser.

Parse answers in `play.py` by splitting field names on the first `:`, and validate the key with `^[A-Za-z0-9_-]{8,64}$`. `RequestDataTooBig` maps to `invalid_request`. Register the "last theme" check with `lifecycle.register_usage_check` in `ApiConfig.ready()`. Questions come from the run's revision with `include_disabled=True`. Run `make messages` in the container and fill in cs, en and uk.

- [x] **Step 5: Run to verify they pass**

Run: `d uv run pytest tests/api tests/contracts tests/test_translations.py -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
d make lint && d make test && git add -A && git commit -m "feat: add public quiz pages and play flow with HTMX in cs, en and uk"
```

---

### Task 5: Admin UI: login, quiz editor, publication, runs, QR

**Files:**
- Create: `app/api/admin_auth.py`, `app/api/admin_quizzes.py`, `app/api/admin_runs.py`, `app/api/admin_users.py`, `app/api/forms.py`, `app/api/jinja2/admin/{login,quiz_list,quiz_form,quiz_edit,question_form,run,users}.html`, `app/providers/auth_local/management/commands/{createsuperuser,changepassword}.py`, `tests/api/test_admin_auth.py`, `tests/api/test_admin_quizzes.py`, `tests/api/test_admin_runs.py`, `tests/api/test_admin_users.py`, `tests/providers/test_auth_local_guarded_commands.py`
- Modify: `app/urls.py`, `app/api/locale/`, `app/settings.py`, `tests/integration/test_auth_switch.py`

**Interfaces:**
- Consumes: `authoring.*` from Task 2, `rendering.page`, `i18n.*` from Task 4, `theme.stylesheet_urls`, `QuestionTypePlugin.render_admin/parse_admin` from Task 1.
- Produces:
  - `admin_auth.admin_required` view decorator: an anonymous request is redirected to `/admin/login?next=<path>`, and the response is `never_cache`.
  - Routes: `/admin/`, `/admin/login`, `POST /admin/logout`, `/admin/quizzes`, `/admin/quizzes/new`, `/admin/quizzes/<uuid>/edit`, `/admin/quizzes/<uuid>/questions/new?type=<id>`, `/admin/quizzes/<uuid>/questions/<str>/edit`, `POST .../questions/<str>/delete`, `POST /admin/quizzes/<uuid>/publish`, `POST /admin/quizzes/<uuid>/runs`, `GET /admin/quizzes/<uuid>/qr.svg`, `GET /admin/runs/<uuid>`, `POST /admin/runs/<uuid>/close`, `/admin/users`.

- [x] **Step 1: Write the failing tests**

```python
# test_admin_auth.py
def test_every_admin_route_redirects_anonymous_to_login(): ...  # parametrised over all routes, GET and POST
def test_login_with_correct_password_opens_quiz_list(): ...
def test_login_with_wrong_password_shows_same_message_as_unknown_login(): ...
def test_inactive_admin_cannot_log_in(): ...
def test_login_next_stays_on_site(): ...  # next=https://evil.example.net/ and //evil.example.net -> /admin/quizzes
def test_login_next_local_path_is_followed(): ...
def test_login_post_without_csrf_token_is_403(): ...  # Client(enforce_csrf_checks=True)
def test_logout_is_post_only_and_ends_session(): ...
def test_admin_language_is_chosen_and_kept_in_session(): ...  # ?lang=en; ?lang=uk is ignored, admin has cs/en only
def test_session_cookie_expires_in_12_hours(): ...

# test_admin_quizzes.py
def test_create_quiz_with_invalid_slug_or_duplicate_shows_error(): ...
def test_default_locale_must_be_selected(): ...
def test_no_locale_selected_is_refused(): ...
def test_add_edit_delete_question_through_plugin_form(): ...
def test_new_question_with_unknown_or_disabled_type_is_404(): ...
def test_invalid_question_form_keeps_input_and_shows_error(): ...
def test_publish_failure_lists_question_and_language(): ...
def test_publish_success_shows_published_state(): ...
def test_edit_after_publication_leaves_published_revision_unchanged(): ...
def test_slug_cannot_change_after_first_publication(): ...
def test_quiz_title_is_escaped_in_list(): ...
def test_editor_offers_only_enabled_question_types(): ...
def test_featured_flag_is_saved(): ...
def test_state_change_without_csrf_token_is_403(): ...  # publish, open run, close run, delete question

# test_admin_runs.py
def test_open_run_without_publication_shows_error(): ...
def test_open_second_run_shows_error(): ...
def test_run_page_shows_public_url_qr_and_submitted_count(): ...
def test_close_run_stops_public_start(): ...
def test_qr_encodes_absolute_public_url(): ...  # equals segno.make("http://testserver/q/<slug>", error="m").save to svg bytes
def test_qr_content_type_is_svg(): ...

# test_admin_users.py
def test_create_second_admin_who_can_log_in(): ...
def test_weak_password_is_refused(): ...  # shorter than 10, common password
def test_duplicate_login_is_refused(): ...
def test_creating_admin_is_audited_without_password(): ...
def test_password_is_never_echoed_back(): ...

# test_auth_local_guarded_commands.py
def test_createsuperuser_refuses_and_names_init_admin(): ...  # exit non-zero, no user row, no traceback
def test_changepassword_refuses_and_names_reset_admin_password(): ...
```

Extend `tests/integration/test_auth_switch.py`: with the test-only auth provider active, `/admin/login` accepts a login the test provider allows and refuses one it rejects, with no change to `app/api/` (AC-02).

- [x] **Step 2: Run to verify they fail**

Run: `d uv run pytest tests/api/test_admin_auth.py tests/api/test_admin_quizzes.py tests/api/test_admin_runs.py tests/api/test_admin_users.py tests/providers/test_auth_local_guarded_commands.py -q`
Expected: FAIL with 404 or import errors.

- [x] **Step 3: Implement**

Django `forms.Form` validate quiz and user input; the question form goes through `parse_admin`. Slug uses `validate_slug`, at most 80 characters. `url_has_allowed_host_and_scheme` guards `next`. Password checks use `validate_password`. `authoring` problem and error codes map to translated strings in `app/api/admin_quizzes.py`. Admin creation is audited as `admin.created` with the new admin's id. Settings order: active `auth` providers come before `django.contrib.auth` in `INSTALLED_APPS`; the rest stay after the kernel. The QR view uses `segno.make(request.build_absolute_uri(f"/q/{slug}"), error="m")`, `.save(buffer, kind="svg", scale=4, border=2)`. Admin strings use the gettext context `admin` (`pgettext`), so the `uk` catalogue test can skip them.

- [x] **Step 4: Run to verify they pass**

Run: `d uv run pytest tests/api tests/providers tests/integration -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
d make lint && d make test && git add -A && git commit -m "feat: add admin login, quiz editor, publication, runs and QR"
```

---

### Task 6: AC-01 end to end, deployment check, browser check, documentation

**Files:**
- Create: `tests/integration/test_ac01_question_plugin.py`, `tests/integration/test_vertical_slice.py`
- Modify: `deploy/smoke.sh`, `docs/_architecture/roadmap.md`, `docs/_architecture/modules/{api-ui,contracts}.md`, `docs/_architecture/plugins/{question-types,scoring,theme-default}.md`, `docs/_architecture/data-model.md`, `docs/plugin-api.md`, `docs/deployment.md`, `CLAUDE.md`, `README.md`, `docs/superpowers/plans/2026-11-06-a4-vertical-slice.md`

**Interfaces:**
- Consumes: every route above; `tests/support/run.py` (`run_manage`, `run_python`, `DEMO_SITE`).

- [x] **Step 1: Write the end-to-end tests**

```python
# test_ac01_question_plugin.py, fresh process with DEMO_SITE on the path
def test_demo_question_type_works_through_editor_rendering_and_scoring(tmp_path): ...
# logged-in client: create quiz, GET new question form with type=demo.number shows the plugin's fields,
# POST it, publish, open run, POST start contains the plugin's input,
# POST submit with "<qid>:value" = correct -> full points, wrong -> 0 on second attempt

def test_startup_stops_when_open_run_needs_uninstalled_type(tmp_path): ...
# second process without DEMO_SITE: verify_startup raises StartupError naming demo.number

# test_vertical_slice.py
def test_admin_to_participant_in_three_languages(client): ...
# create cs+en+uk quiz through admin views, publish, open run, QR 200, participant in each language
# starts and submits, each gets the same score; after close new start is 409 and old results stay
```

- [x] **Step 2: Run them**

Run: `d uv run pytest tests/integration/test_ac01_question_plugin.py tests/integration/test_vertical_slice.py -q`
Expected: PASS without new production code. A failure is a real gap: fix it with a test that shows it, per `CLAUDE.md`.

- [x] **Step 3: Extend `deploy/smoke.sh`, then run it**

After the existing checks, through Caddy over HTTPS with `curl -k`:

- `GET /admin/quizzes` is a redirect to `/admin/login`.
- Login with the generated password via a cookie jar and the CSRF form field works.
- A quiz is created by `manage.py shell` in the container, which prints the slug, the run id and a correct option id.
- `GET /q/<slug>` is 200. `POST /r/<run>/start` returns hidden fields, read with `sed`, and does not contain the word `correct`.
- `POST /a/<attempt>/submit` with the correct option shows `1 / 1`; a second submit with the same key gives the same body.
- `pico.min.css` and `htmx.min.js` load with status 200.
- The response has a `Content-Security-Policy` header.

Run: `make smoke`
Expected: all `PASS`, last line `SMOKE OK`.

- [x] **Step 4: Browser check in the real deployment**

Start the compose stack (`deploy/compose.yaml`, own project name, generated secret, ports 18080 and 18443), create an admin, and drive it through the Playwright browser tools: log in, create a quiz in cs and uk, add two questions, publish, open a run, view the QR, play in uk, submit, see the score. Then start a second attempt, close the run in the admin and submit: the page shows the translated closed message. Check at phone width (390 px), tab through a question by keyboard, and confirm the console has no CSP errors. Stop the network mid-play (browser offline mode) and submit: the page shows the translated network message, and a retry after reconnecting gives the score. Repeat the play once with JavaScript disabled. Take the stack down with `docker compose -p <name> down -v` for this project only. Any defect goes back through a failing test. If browser tools cannot reach the stack, report this step as not done.

- [x] **Step 5: Update documentation**

- `roadmap.md`: A4 Done with date, Stage A complete, Stage B next.
- `api-ui.md`: final routes, HTML start and submit, the name form convention.
- `architecture.md`: §4 flow returns HTML; HTMX and Pico in the stack table. ADR-0036 stays valid: the JSON surface is now empty rather than small, noted in `api-ui.md`.
- `contracts.md`, `plugin-api.md`: `render_admin`, `parse_admin`, `ThemePlugin`, `<question id>:<field>` input names.
- `data-model.md`: `Quiz.title` as a locale map, tables that exist since A4.
- `question-types.md`: `choice.single` definition and option-id rule.
- `deployment.md`, `README.md` (Czech): how to try it in Docker: `make smoke`, then compose up, `init_admin`, `/admin/login`.
- `CLAUDE.md`: `make messages` in the command list, state line, A1–A4 done and playable, next B1.
- This plan: tick the steps.

- [x] **Step 6: Commit**

```bash
d make quality && make smoke && git add -A && git commit -m "test: verify the vertical slice end to end and document stage A"
```

Expected: both commands exit 0 before the commit runs. Finish with the final whole-branch review and `superpowers:finishing-a-development-branch`; merging waits for the user's word.
