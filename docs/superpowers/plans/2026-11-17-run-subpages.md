# Run Subpages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the admin run page `/admin/runs/<run>` into tabs with their own addresses (Overview, Attempts, Scoreboard, Statistics, Rewards, Draw, Export, Settings).

**Architecture:** One small module `app/api/run_tabs.py` defines the tabs and which ones a run shows; one partial `admin/_run_header.html` draws the run header and the tab bar on every tab. `app/api/admin_runs.py` splits today's `_run_context` into a header context plus one context per tab, and every view that re-renders the run page today re-renders the tab its form is on. Rewards and Draw keep their views in `admin_rewards.py` and include the same partial.

**Tech Stack:** Django, Jinja2, HTMX, Pico CSS; pytest via `make test`.

**Spec:** `docs/superpowers/specs/2026-11-17-run-subpages-design.md`

## Global Constraints

- One page per thing an admin works with, its address after `/`; `#` only jumps inside one page; POST actions have verb names.
- Addresses: Overview `/admin/runs/<run>` (name `admin_run`), Attempts `…/attempts` (`admin_run_attempts`), Scoreboard `…/scoreboard` (GET, `admin_run_scoreboard`), Statistics `…/statistics` (`admin_run_statistics`), Rewards `…/rewards` (unchanged, `admin_run_rewards`), Draw `…/draw` (unchanged, `admin_run_draw`), Export `…/export` (`admin_run_export`), Settings `…/settings` (`admin_run_settings`). The scoreboard settings form posts to `…/scoreboard/settings` (`admin_run_scoreboard_settings`).
- Labels: cs Přehled, Pokusy, Žebříček, Statistiky, Odměny, Losování, Export, Nastavení; en Overview, Attempts, Scoreboard, Statistics, Rewards, Draw, Export, Settings. The bar's "more" is the quiz header's existing "More" / "Více".
- Always visible: Overview, Attempts, Scoreboard, Statistics. Under More: Rewards, Draw, Export, Settings; the More list is open and marked `aria-current="page"` when its tab is current (same markup as `_quiz_header.html` lines 33–45).
- Draw is listed only when the run has a draw rule. Settings is listed only when `not basic or has_code`. A tab opened by address with nothing to show says one line: cs "Tady v zobrazení Základní nic není. Přepněte na Vše." / en "Nothing here in the Basic view. Switch to All."
- Refusals keep today's status codes (409, 400, or 200 where today's view answers 200) and appear on the tab the form is on; `run_error` keeps its place in `_quiz_header.html`.
- No change to public addresses, QR, the public scoreboard, the projector, the plan pages, or to what any section does. UI word is "běh"/"run", never "kolo".
- Never touch Docker stacks `kvizotron-browser` or `kvizotron-tmp`; a walkthrough uses a throwaway project.
- Existing tests that read a moved section change their URL to the new tab; no assertion is removed or weakened.
- Every new text through `make messages` with cs and uk `msgstr` filled.

## Review Focus

1. Inline nickname edit (HTMX) on the Attempts tab: without JavaScript the pencil and Back links land on `/attempts`, not on the Overview — Task 2 test.
2. Sorting the attempts table keeps you on Attempts (`?sort=…&dir=…` relative to `/attempts`) — Task 1 test.
3. A refused scoreboard setting (archived quiz, 409) shows the alert and the form on the Scoreboard tab — Task 2 test.
4. In Basic view a run without an access code has no Settings tab, and `/settings` says the one line instead of an empty page — Task 3 test.
5. An old bookmark `/admin/runs/<run>#statistics` still opens (the Overview) with 200 — Task 1 test.

---

### Task 1: Tabs, header and the moved sections

**Files:**
- Create: `app/api/run_tabs.py`, `app/api/jinja2/admin/_run_header.html`, `app/api/jinja2/admin/run_attempts.html`, `run_scoreboard.html`, `run_statistics.html`, `run_export.html`, `run_settings.html` (all in `app/api/jinja2/admin/`)
- Modify: `app/api/jinja2/admin/run.html` (Overview only), `app/api/admin_runs.py` (`_run_context` split, new GET views, `_attempt_table` hrefs), `app/api/admin_urls.py:174-182`
- Test: `tests/api/test_run_tabs.py`; URL updates in existing tests that read moved sections

**Interfaces:**
- Produces: `run_tabs.Tab` (frozen dataclass: `key: str`, `url_name: str`, `label: str`, `more: bool`); `run_tabs.TABS: tuple[Tab, ...]` in the order of Global Constraints; `run_tabs.shown(run: QuizRun, *, basic: bool) -> list[Tab]`.
- Produces in `admin_runs.py`: `_header_context(request, run, tab: str) -> dict[str, Any]` (workspace "runs", `run`, `status_label`, `is_open`, `run_tabs`, `run_tab`); `_tab_page(request, run, tab: str, extra: dict[str, Any] | None = None, *, status: int = 200, name_field: NameField | None = None) -> HttpResponse` rendering `TAB_TEMPLATES[tab]` with `_header_context` plus that tab's context plus `extra`.
- Produces templates: `admin/_run_header.html` expects `run`, `status_label`, `run_tabs`, `run_tab`.

- [ ] **Step 1: Write the failing tests** in `tests/api/test_run_tabs.py` (build runs with `tests/domain/helpers.py`, client fixture `logged_in`):

```python
def test_every_tab_has_its_own_address(logged_in):
    """AC-184: each part of a run is a page of its own; the bar marks the current one."""
    run = open_run()
    for path, label in [("", "Overview"), ("/attempts", "Attempts"), ("/scoreboard", "Scoreboard"),
                        ("/statistics", "Statistics"), ("/export", "Export")]:
        html = text(logged_in.get(f"/admin/runs/{run.id}{path}?lang=en"))
        assert re.search(rf'aria-current="page">{label}<', html)

def test_sections_live_on_their_tab(logged_in):
    run = open_run()
    overview = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert 'name="deadline_at"' in overview and "Scores by tenths" not in overview
    assert "Scores by tenths" in text(logged_in.get(f"/admin/runs/{run.id}/statistics?lang=en"))  # with a submitted attempt
    assert 'action="/admin/runs/{}/scoreboard/settings"'.format(run.id) in text(logged_in.get(f"/admin/runs/{run.id}/scoreboard"))
    assert 'name="access_code"' in text(logged_in.get(f"/admin/runs/{run.id}/settings"))

def test_sorting_attempts_stays_on_the_tab(logged_in):
    run = run_with_two_attempts()
    html = text(logged_in.get(f"/admin/runs/{run.id}/attempts"))
    assert 'href="?sort=name&amp;dir=asc"' in html and "#attempts" not in html

def test_an_old_anchor_address_still_opens(logged_in):
    run = open_run()
    assert logged_in.get(f"/admin/runs/{run.id}#statistics").status_code == 200

def test_the_scoreboard_settings_post_moved(logged_in):
    run = open_run()
    response = logged_in.post(f"/admin/runs/{run.id}/scoreboard/settings", {...})  # today's valid payload
    assert response.status_code == 302
    assert logged_in.post(f"/admin/runs/{run.id}/scoreboard", {}).status_code == 405
```

- [ ] **Step 2: Run:** `uv run pytest tests/api/test_run_tabs.py -q` — Expected: FAIL (404 on the new addresses).
- [ ] **Step 3: Implement.** `run_tabs.py` per Interfaces (labels with `gettext_lazy`; `shown` drops Draw without a draw rule and Settings when `basic and not run.access_code_hash`). Split `_run_context` so each tab computes only its own data (statistics only on Statistics, `results.board` only on Scoreboard). Placement per the spec: Overview = QR, public address, status, submitted/unsent, revision and "Change the plan", start, deadline, limit, deletion notice and history link, deadline form, End/Archive/Restore; Attempts = participant rules list, the table, the walkthrough link; Scoreboard = shared-board notices, fixed rules, public/projector links, admin board, settings form; Statistics = today's statistics; Export = today's export link; Settings = access code, data rules, period form, "Delete data now". New GET views `run_attempts`, `run_scoreboard_page`, `run_statistics`, `run_export`, `run_settings`; POST `run_scoreboard` moves to `scoreboard/settings` (`require_POST` stays) and the GET `scoreboard` route maps to the page view. `_attempt_table` hrefs drop `#attempts`. The section panel stays on each tab for the Basic / All switch with that tab's jump list (`panel_before`).
- [ ] **Step 4: Update existing tests** that read a moved section to fetch its tab (`grep -rln "/admin/runs/" tests`), then run `uv run pytest tests/api -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): run tabs with their own addresses`.

### Task 2: Every form returns to its tab

**Files:**
- Modify: `app/api/admin_runs.py` (`board_split`, `_show_code`, `participant_name`, `_nick_field`, `run_deadline`, `_confirm_earlier`, `run_period`, `_confirm_period`, `run_scoreboard`, `run_close`, `run_code`), `app/api/admin_retention.py:200-245` (`delete_data`, `_run_page_with`, `_confirm_delete`)
- Test: `tests/api/test_run_tabs.py`

**Interfaces:**
- Consumes: `_tab_page(request, run, tab, extra, status=…, name_field=…)` from Task 1.

| View | Success redirect | Refusal re-renders | Confirm cancel |
|---|---|---|---|
| `run_deadline` | `admin_run` | overview | `admin_run` |
| `run_close` | `admin_run` | — | `admin_run` |
| `run_period` | `admin_run_settings` | settings | `admin_run_settings` |
| `run_code` (incl. `_show_code`, also from `run_plan`/`plan_edit`) | `admin_run_settings` | settings (new code shown there) | — |
| `delete_data` (`admin_retention`) | `admin_run_settings` | settings | `admin_run_settings` |
| `run_scoreboard` (POST settings) | `admin_run_scoreboard` | scoreboard | — |
| `board_split` | unchanged (`admin_run_open`) | scoreboard | — |
| `participant_name` | `…/attempts` | attempts (with the field) | — |

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_refused_scoreboard_setting_stays_on_its_tab(logged_in):
    run = open_run(); archive_quiz(run.quiz)
    response = logged_in.post(f"/admin/runs/{run.id}/scoreboard/settings?lang=en", payload(run))
    assert response.status_code == 409
    html = text(response)
    assert 'role="alert"' in html and re.search(r'aria-current="page">Scoreboard<', html)

def test_a_new_code_is_shown_on_settings(logged_in):
    run = open_run()
    html = text(logged_in.post(f"/admin/runs/{run.id}/code?lang=en", {"action": "generate"}))
    assert "It is shown only now" in html and re.search(r'aria-current="page">Settings<', html)

def test_the_name_edit_without_javascript_lands_on_attempts(logged_in):
    run, participant = run_with_named_attempt()
    edit = logged_in.get(f"/admin/runs/{run.id}/participants/{participant.id}/name?edit=1")
    assert edit["Location"] == f"/admin/runs/{run.id}/attempts?edit={participant.id}"
    back = logged_in.post(f"/admin/runs/{run.id}/participants/{participant.id}/name", {"name": "Nový"})
    assert back["Location"] == f"/admin/runs/{run.id}/attempts"

def test_confirm_pages_cancel_to_their_tab(logged_in):
    run = open_run(deadline_in_hours=2)
    html = text(logged_in.post(f"/admin/runs/{run.id}/deadline", {"deadline_at": earlier_value(run)}))
    assert f'href="/admin/runs/{run.id}"' in html  # cancel → overview
    # period confirm → f"/admin/runs/{run.id}/settings"; delete-data confirm → same
```

- [ ] **Step 2: Run** `uv run pytest tests/api/test_run_tabs.py -q` — Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the table above with `_tab_page`; `_nick_field` builds `edit_page=f"{attempts}?edit={id}"` and `back_page=attempts` with `attempts = reverse("admin_run_attempts", args=[run.id])`. Keep every status code as today.
- [ ] **Step 4: Run** `uv run pytest tests/api -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): run forms return to their tab`.

### Task 3: Rewards and Draw join the bar; tabs with nothing to show

**Files:**
- Modify: `app/api/admin_rewards.py` (`_run_page` ~l.298, the draw page ~l.600-620), `app/api/jinja2/admin/rewards.html`, `app/api/jinja2/admin/prize_draw.html`, `app/api/admin_runs.py` (empty-tab line), the tab templates
- Test: `tests/api/test_run_tabs.py`

**Interfaces:**
- Consumes: `admin/_run_header.html` and `run_tabs.shown` from Task 1. `admin_rewards` must not import private names of `admin_runs`; it builds the header context from `run_tabs` itself (the import direction `admin_rewards → run_tabs` is fine, `run_tabs` imports only domain).

- [ ] **Step 1: Write the failing tests:**

```python
def test_rewards_and_draw_carry_the_bar(logged_in):
    run = open_run_with_draw_rule()
    rewards = text(logged_in.get(f"/admin/runs/{run.id}/rewards?lang=en"))
    assert re.search(r'aria-current="page">Rewards<', rewards) and "Back to the run" not in rewards
    assert re.search(r'aria-current="page">Draw<', text(logged_in.get(f"/admin/runs/{run.id}/draw?lang=en")))

def test_draw_is_listed_only_with_a_draw_rule(logged_in):
    run = open_run()
    assert f"/admin/runs/{run.id}/draw" not in text(logged_in.get(f"/admin/runs/{run.id}"))

def test_basic_view_without_a_code_has_no_settings_tab(logged_in):
    run = open_run()  # no access code, Basic is the default view
    assert f"/admin/runs/{run.id}/settings" not in text(logged_in.get(f"/admin/runs/{run.id}"))
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert "Nothing here in the Basic view. Switch to All." in html

def test_the_more_list_opens_on_its_tab(logged_in):
    run = open_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}/export?lang=en"))
    assert re.search(r'<details class="tab-more" open>\s*<summary aria-current="page">More<', html)
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement:** both reward pages include `_run_header.html` with `run_tab` "rewards" / "draw" and drop their "Back to the run" links; the empty line on Settings in Basic without a code.
- [ ] **Step 4: Run** `uv run pytest tests/api -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(admin): rewards and draw as run tabs`.

### Task 4: Links, rule and documents

**Files:**
- Modify: `app/api/jinja2/admin/_quiz_header.html:27-28`, `app/api/jinja2/admin/runs.html:11-12,75`, any other `admin_run` + `#…` builder (`grep -rn "admin_run', args=\[.*\]) }}#\|admin_run\", args" app`), `docs/_architecture/modules/api-ui.md`, `docs/_architecture/acceptance-criteria.md`, `docs/_architecture/adr/README.md`, `CLAUDE.md` / `app/api/CLAUDE.md` where they name the run page sections, locale catalogues
- Create: `docs/_architecture/adr/0068-run-subpages.md` (MADR 4, status accepted, context = the URL question, decision = the spec's rule and tab table, consequences = old `#` bookmarks open the Overview)
- Test: `tests/api/test_run_tabs.py`, `tests/test_docs.py` (must stay green)

- [ ] **Step 1: Write the failing test:**

```python
def test_quick_links_go_to_the_tabs(logged_in):
    run = open_run()
    for page in (f"/admin/quizzes/{run.quiz_id}/runs", f"/admin/quizzes/{run.quiz_id}/edit"):
        html = text(logged_in.get(page))
        assert f"/admin/runs/{run.id}/statistics" in html and f"/admin/runs/{run.id}/scoreboard" in html
        assert f"/admin/runs/{run.id}#" not in html
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** the links; add AC-184 ("A run's parts are pages: Overview, Attempts, Scoreboard, Statistics, Rewards, Draw, Export, Settings, each with its own address and the run header with the tab bar; a form returns to its tab; `#` only jumps inside a page", ADR-0068, stage D) — the test docstrings in Task 1 already name it; write the rule into `api-ui.md`; `make messages` and fill cs and uk `msgstr`.
- [ ] **Step 4: Run** `make lint && make test` — Expected: PASS.
- [ ] **Step 5: Commit** `docs: ADR-0068 run subpages, AC-184`.

### Task 5: Browser walkthrough

- [ ] **Step 1:** Use the skill `kvizotron-browser-walkthrough` on a throwaway project (for example `kvizotron-tabs` on ports 28180/28543, `docker compose -p kvizotron-tabs …`), never `kvizotron-browser` or `kvizotron-tmp`. Walk 1280 px light cs and 390 px dark uk: every tab, the More list, a refused scoreboard setting, a new access code, the inline name edit, sorting. `errs` empty; no horizontal scroll (AC-118).
- [ ] **Step 2:** Remove the throwaway project with `docker compose -p kvizotron-tabs down -v` after checking its label.
- [ ] **Step 3:** Fix any finding test-first; `make quality` — Expected: PASS.
