# Run page split into subpages — design

Status: agreed with the owner in chat on 2026-11-17 (variant B of the URL question). Not implemented.

## Why

The admin run page `/admin/runs/<run>` is one long page (`app/api/jinja2/admin/run.html`, about 208
lines) whose parts are reached by `#` anchors: `#access-code`, `#data`, `#rewards`, `#scoreboard`,
`#statistics`, `#attempts`, `#export`. Meanwhile rewards and the draw already have pages of their own
(`…/rewards`, `…/draw`), and the address `…/scoreboard` is not the scoreboard but the POST target of
its settings form. The owner wants one rule: **one page per thing an admin works with, an address
after `/`; `#` only jumps inside one page; POST actions have verb names.** The quiz already works
this way (tabs in `_quiz_header.html`).

## Goals

- The run gets tabs, each tab a page with its own address:

| Tab (cs label) | Address | Holds |
|---|---|---|
| Overview (default) | `/admin/runs/<run>` | QR, public address, status chip, attempts submitted, not sent, revision and "Change the plan" for a scheduled run, start, deadline, time limit, deletion notice and link to the deletion history, and the run's actions (close, archive, restore, change deadline) |
| Attempts | `/admin/runs/<run>/attempts` | the attempts table with its sorting and the inline name edit |
| Scoreboard | `/admin/runs/<run>/scoreboard` | the admin view of the ranking, the scoreboard settings form (revision mode, visibility, columns), the shared board (ADR-0065: linked runs, split) and the projector link |
| Statistics | `/admin/runs/<run>/statistics` | the run statistics now under `#statistics` |
| Rewards | `/admin/runs/<run>/rewards` (address unchanged) | today's rewards page (`admin_rewards.run_rewards`) |
| Draw | `/admin/runs/<run>/draw` (address unchanged) | today's draw page (`admin_rewards.run_draw`); the tab shows only when the run has a rule with a draw |
| Export | `/admin/runs/<run>/export` | what is under `#export` today |
| Settings | `/admin/runs/<run>/settings` | access code, retention period, "Delete data now", the date of deletion |

- The Rewards and Draw pages keep their addresses and content but join the tab bar: their views
  and templates in `app/api/admin_rewards.py` get the run header and the tab bar like the others
  (the owner chose "two tabs, both with the same header and tab bar").
- Every tab shows the same run header above the tab bar (run number, status chip, deadline), so the
  admin always sees which run they are in. The quiz header with its tabs stays above it, as now
  (the quiz tab "Runs" stays current).
- The scoreboard settings form posts to `/admin/runs/<run>/scoreboard/settings` (today
  `…/scoreboard`, name `admin_run_scoreboard`); the GET address `…/scoreboard` becomes the tab.
  Other POST actions keep their verb addresses (`/close`, `/archive`, `/restore`, `/period`,
  `/deadline`, `/code`, `/board/split`, `/delete-data`, …).
- After a POST the admin lands on the tab the form was on (code → Settings, deadline → Overview,
  scoreboard settings → Scoreboard, attempt name → Attempts, …), with the same status codes as
  today for refusals (400 field error, 409 rule refusal; ADR-0067).
- The links "Statistics" and "Scoreboard" in `_quiz_header.html` and on the Runs tab (`runs.html`)
  point to the new subpages; every other place that builds `admin_run` + `#…` (for example
  `admin_runs.py` around the attempts sort and edit links) points to the subpage instead.
- The Basic / All switch keeps working on every tab (it lives in `_section_panel.html`).
- The rule goes into `docs/_architecture/modules/api-ui.md` and a new ADR (next free number,
  ADR-0068), with a new acceptance criterion (next free, AC-184) named by a test.

## Non-goals

- No change to public addresses, QR codes, the public scoreboard, the projector, or the run plan
  pages (`/admin/quizzes/<quiz>/runs/plan`, `/admin/runs/<run>/plan`).
- No redirect from old `#` addresses: the server never receives the fragment, so
  `/admin/runs/<run>#statistics` simply opens the Overview. These are internal admin addresses.
- No change to what any section does — only where it lives.

## Anti-goals (would make it a failure even if it works)

- A refusal or error that lands on a different tab than the form, so the admin does not see it.
- A tab that silently loses an action that exists today (every POST form on today's page must be
  reachable from exactly one tab).
- The tab bar overflowing a 390 px phone or the page overflowing at 1280 px (AC-118).
- Basic mode hiding a whole tab's only content without saying so.

## Constraints

- Django + Jinja2 + HTMX + Pico CSS as today; no new dependency.
- UI word for `QuizRun` is "běh" / "run", never "kolo" (CLAUDE.md).
- Every text in cs, en, uk via `make messages`; admin pages are cs/en.
- Tests see HTML, not the browser: the tab bar at 390 px and 1280 px is checked in a browser
  walkthrough on a throwaway stack (never `kvizotron-browser` or `kvizotron-tmp` data).

## Decided by the agent (owner may change)

- **Narrow screens and the tab bar:** the same pattern as the quiz header: the first four tabs
  (Overview, Attempts, Scoreboard, Statistics) always visible, the other four (Rewards, Draw,
  Export, Settings) under "Více ▾" / "More", open and marked current when one of them is the
  current tab.
- **Section panel:** each tab keeps the panel for the Basic / All switch; its jump list holds the
  sections of that tab only (or none).
- **Per-tab context:** each view computes only what its tab shows (statistics and the scoreboard
  are not computed on the Overview), splitting today's `_run_context`.
- **Where the rest goes:** the participant rules list ("Participants") and the link "See the
  answers of this run" go to Attempts; the fixed scoreboard rules (official attempt, tie break) to
  Scoreboard; the data rules (profile, period) to Settings.
- **Attempts sort and edit links** become `…/attempts?sort=…` and `…/attempts?edit=<participant>`.

- **Shared board:** sharing several runs stays on the quiz's Runs tab (`admin_board_share`,
  `admin_board_split` there keep redirecting to the runs list), because it selects several runs at
  once. The Scoreboard tab shows which runs are linked, as the run page does today (it has no split
  button today and gets none); a `board_split` refusal that today re-renders the run page
  re-renders the Scoreboard tab.
- **A one-time access code** set on the plan page (`run_plan`, `plan_edit`, `_show_code`) is shown on
  the Settings tab, where the code lives.
- **Basic mode:** a tab is listed only when it has something to show, by the same conditions that
  hide today's sections (in Basic the Settings tab only when the run has an access code); the
  Overview and Attempts are always there. A tab reached by its address with nothing to show says so
  in one line instead of an empty page. Test runs have no run page today (`QuizRun.objects`
  leaves them out), and that stays.
- **Refusals and confirm pages:** a view that today re-renders `admin/run.html` with 400 or 409
  (`participant_name`, `run_deadline`, `run_period`, `run_scoreboard`, `run_code`, `board_split`)
  re-renders the tab its form is on, with the same status. Confirm pages (`_confirm_earlier`,
  `_confirm_period`, the GET form of `run_close`) cancel back to the tab they came from.

## Left to the builder

- How `_run_context` is split (one helper per tab or a shared header helper plus per-tab parts).
- Template layout (one base template for the run header and tab bar, one template per tab).
- Exact redirect mapping per POST, as long as it follows the goal above.
