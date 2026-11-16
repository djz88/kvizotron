# The shown address of one test link — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pencil at the address of a test link lets the admin change the scheme, host and port that link is shown with; it is saved with the link and changes nothing else.

**Architecture:** `RunTestLink.shown_origin` (migration `0022`), validated and saved by `run_links.set_origin`. The page builds the address from `shown_origin` or, when empty, from the request. The inline name component gains an optional fixed `suffix` and `pencil_label`.

**Tech Stack:** Django, Jinja2, HTMX, pytest, Babel.

**Spec:** `docs/superpowers/specs/2026-11-12-test-link-address-design.md`

## Global Constraints

- Only the shown address of that one link changes: token, end, run, other links, the public quiz address and QR stay.
- Origin: `http://` or `https://`, host name, IPv4 or `[IPv6]`, optional port 1–65535; no path, query, fragment or user info; no scheme means `https://`; trailing `/` dropped; at most 200 characters; empty resets.
- CSRF on the POST, no inline script or style, audit `test_link.address_changed` without the value or the token; archived quiz: no pencil, save refused.
- New strings through `gettext`, cs filled; README AC range `AC-01…AC-167`.

## Review Focus

- A value with a path, `?`, `#`, `user@`, a port 0 or 65536, `javascript:` or spaces is refused and nothing is saved.
- Without JavaScript the pencil opens the field on the page (`?edit=address-<link id>`) and a refusal is the whole page with status 400.
- With two links on the page, editing one does not change the other's address or field ids.
- The `href` and the text of the address use the saved origin after a reload.

---

### Task 1: Domain

**Files:**
- Modify: `app/domain/models.py`, `app/domain/run_links.py`
- Create: `app/domain/migrations/0022_test_link_shown_origin.py`
- Test: `tests/domain/test_run_links.py` (create it if absent; otherwise add)

**Interfaces:**
- Produces: `RunTestLink.shown_origin = models.CharField(max_length=200, blank=True, default="")`; `run_links.OriginInvalid(ValueError)`; `run_links.clean_origin(value: str) -> str` (normalised origin, `""` for empty); `run_links.set_origin(link: RunTestLink, value: str, *, admin_id: str) -> None` (calls `authoring.ensure_editable(link.run.quiz)`, saves `clean_origin(value)`, audits `test_link.address_changed` with no details).

- [ ] **Step 1: Write the failing tests**
  - `test_clean_origin_accepts_host_ip_and_port` (parametrised): `"192.168.1.10:8443" → "https://192.168.1.10:8443"`, `"http://kviz.example.cz/" → "http://kviz.example.cz"`, `"https://[::1]:8443" → "https://[::1]:8443"`, `" HTTPS://Kviz.Example.cz " → "https://kviz.example.cz"`, `"" → ""`
  - `test_clean_origin_refuses_anything_else` (parametrised, `OriginInvalid`): `"https://a.cz/t/x"`, `"https://a.cz?x=1"`, `"https://a.cz#x"`, `"https://user@a.cz"`, `"https://a.cz:0"`, `"https://a.cz:65536"`, `"javascript:alert(1)"`, `"ftp://a.cz"`, `"a b.cz"`, `"https://" + "a" * 200`
  - `test_set_origin_saves_only_that_link_and_audits_without_the_value` (docstring `AC-167:`): two links; `set_origin(first, "10.0.0.5:8080")` → first has `https://10.0.0.5:8080`, second `""`, token and `expires_at` unchanged; one `AuditEvent` `test_link.address_changed` whose details hold neither the origin nor the token
  - `test_set_origin_is_refused_for_an_archived_quiz`: `authoring.QuizArchived`
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_run_links.py -q` — Expected: FAIL
- [ ] **Step 3: Implement** the field, migration (`makemigrations domain --name test_link_shown_origin`) and functions; parse with `urllib.parse.urlsplit` after adding `https://` when no `://`; host check with `ipaddress` or the label rule `[a-z0-9-]{1,63}` joined by dots; lower-case scheme and host.
- [ ] **Step 4: Run** `uv run pytest tests/domain -q` — Expected: PASS
- [ ] **Step 5: Commit** `git add app/domain tests/domain docs/superpowers && git commit -m "feat(test-links): a shown address saved with one test link (domain)"`

---

### Task 2: The pencil on the test links page

**Files:**
- Modify: `app/api/inline_name.py`, `app/api/jinja2/admin/_inline_name.html`, `app/api/admin_links.py`, `app/api/admin_urls.py`, `app/api/jinja2/admin/test_links.html`, `app/api/locale/cs/…`
- Test: `tests/api/test_test_links.py`, `tests/api/test_inline_name.py`

**Interfaces:**
- Consumes: `run_links.set_origin`, `OriginInvalid`, `RunTestLink.shown_origin` (Task 1).
- Produces: `NameField.suffix: str = ""` (shown after the value, inside the link when `link` is set, and after the input when editing) and `NameField.pencil_label: str = ""` (pencil `aria-label` and `title`; default keeps "Edit name: …"/"Edit name"). Route `tests/<uuid:link_id>/address` named `admin_test_link_address`, GET and POST, same shape as `admin_banks.bank_name`; the field is `address` with key = link id; no-JS edit page `admin_quiz_tests?edit=address-<link id>`. `_row` gives `address` = `(link.shown_origin or request origin) + reverse("test_link", args=[token])` and `address_field` (the `NameField`, `link=address`, `suffix=path`, `value=origin`, label "Address of the link", pencil label "Edit the address", note "Only how this link is shown and copied."), none for an archived quiz.

- [ ] **Step 1: Write the failing tests**
  - in `tests/api/test_test_links.py`: `test_the_address_of_a_link_has_a_pencil_and_saves` (docstring `AC-167:`): POST `{"address": "10.0.0.5:8080"}` to `/admin/tests/<id>/address` with `HX-Request` → 200, the partial holds `https://10.0.0.5:8080/t/<token>`; the page then shows that address as `href` and text, and another link of the quiz keeps `http://testserver/t/…`
  - `test_a_bad_address_keeps_the_field_with_its_message`: HTMX POST `"https://a.cz/x"` → 400 with the message and the typed value; without HTMX → 400 full page with the field open
  - `test_an_empty_address_goes_back_to_the_admins_address`
  - `test_without_javascript_the_pencil_opens_the_field_on_the_page`: GET `/admin/quizzes/<quiz>/tests?edit=address-<id>` shows `name="address"`; GET `/admin/tests/<id>/address?edit=1` without HTMX redirects there
  - `test_an_archived_quiz_shows_no_pencil_and_refuses_the_save`
  - in `tests/api/test_inline_name.py`: `test_a_suffix_and_a_pencil_label_are_drawn` (render a `NameField` with `suffix="/t/x"`, `pencil_label="Edit the address"`, `link="https://a/t/x"`: the link text is `https://a/t/x`, the pencil `title` is "Edit the address"; editing shows the suffix after the input)
- [ ] **Step 2: Run** `uv run pytest tests/api/test_test_links.py tests/api/test_inline_name.py -q` — Expected: FAIL
- [ ] **Step 3: Implement**; check `tests/api/test_request_limits.py` covers the new route through `link_id`.
- [ ] **Step 4: Run** `uv run pytest tests/api tests/test_wiring.py -q` — Expected: PASS
- [ ] **Step 5: Translations** `make messages`, cs for the new api strings; `uv run pytest tests/test_translations.py -q` — Expected: PASS
- [ ] **Step 6: Commit** `git add app/api tests/api && git commit -m "feat(test-links): a pencil at the address of a test link"` with only the api `.po`/`.mo`.

---

### Task 3: Documentation and checks

- [ ] **Step 1:** AC-167 "The address of one test link can be changed where it is shown" (pencil, origin only, saved with the link, nothing else changes, validation, audit without the value, archived quiz); related FR of test links, ADR-0044; stage D. README range `AC-01…AC-167`. ADR-0044 addendum. `data-model.md`: `shown_origin` in the `test_link` row. `app/domain/CLAUDE.md`: one line at `run_links.py`.
- [ ] **Step 2: Run** `uv run pytest tests/test_docs.py -q` then `make quality` — Expected: PASS, exit 0
- [ ] **Step 3: Browser check** on the throwaway instance: pencil, edit and save with HTMX and by keyboard, reload keeps it, refusal message, 1280 light and 390 dark.
- [ ] **Step 4: Commit** `git add docs app/domain/CLAUDE.md && git commit -m "docs: the shown address of a test link (AC-167, ADR-0044)"`
