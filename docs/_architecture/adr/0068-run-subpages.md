---
status: accepted
date: 2026-11-17
---

# ADR-0068: A run's parts are pages with their own addresses; `#` only jumps inside a page

## Context and Problem Statement

The admin page of a run, `/admin/runs/<run>`, grew into one long page whose parts (access code, data, rewards, scoreboard, statistics, attempts, export) were reached by `#` anchors, while rewards and the draw already had pages of their own (`…/rewards`, `…/draw`) and the address `…/scoreboard` was only the POST target of the scoreboard settings. A link "Statistics" therefore meant `…#statistics` in one place and a page in another, and a form posted from the bottom of the page came back to its top. Should a part of a run be reached after `/` (its own page) or after `#` (a place on one long page)? The rule below is about a run's tabs only.

## Decision Drivers

* One rule for every address an admin sees, the same as the quiz's tabs
* An admin sees which run they are in on every part of it
* A form, a refusal or an error comes back where the form is
* No public address, QR code or plan page changes

## Considered Options

* (a) Keep one long run page with `#` anchors, and move rewards and the draw back onto it
* (b) One page per part of a run, its address after `/`; `#` only jumps inside one page; a POST that is not the page's own form has a verb name or sits below the page as `…/<part>/settings`

## Decision Outcome

Chosen option: (b), agreed with the owner.

| Tab | Address | Holds |
|---|---|---|
| Overview (default) | `/admin/runs/<run>` | QR, public address, status, attempts submitted and not sent, revision and "Change the plan" of a scheduled run, start, deadline, time limit, deletion notice (and, with a draw but no e-mail collected, the notice "This run has a draw but does not collect e-mail") and history link, the deadline form and End / Archive / Restore |
| Attempts | `…/attempts` | participant rules, the table of attempts with its sorting and the name edit, the link to the answers of the run |
| Scoreboard | `…/scoreboard` (GET) | shared-board notices, the fixed rules, public and projector links, the admin board and the settings form, which posts to `…/scoreboard/settings` |
| Statistics | `…/statistics` | the run statistics |
| Rewards | `…/rewards` (unchanged) | the rewards of the run |
| Draw | `…/draw` (unchanged) | the prize draw; listed only when the run has a draw rule |
| Export | `…/export` | the export of the run's results |
| Settings | `…/settings` | access code, data rules, retention period, "Delete data now"; in the Basic view listed only when the run has an access code or its data can be deleted now |

Every tab shows the quiz header, then the run header and a tab bar (`app/api/run_tabs.py`, `admin/_run_header.html`); Overview, Attempts, Scoreboard and Statistics are always in the bar, the others under "More", as in the quiz header; the tab being shown is always listed, even one that would otherwise be hidden. Each tab computes only what it shows.

The rule is narrower than the whole administration: a page with a form may post to its own address (the quiz's Runs tab, the settings pages, the run plan, a participant's name), a POST that is not the page's own form has a verb name (`…/close`, `…/archive`) or sits below the page as `…/<part>/settings` (`…/scoreboard/settings`), and `/admin/runs/<run>/settings` is the Settings tab page (GET).

### Consequences

* Good, because every part of a run has an address that can be linked, bookmarked and reloaded.
* Good, because statistics and the scoreboard are no longer computed for every view of the run.
* Neutral, because an old bookmark such as `/admin/runs/<run>#statistics` opens the Overview: the server never receives the fragment, so nothing can redirect it. These are internal admin addresses.
* Neutral, because the shared board of several runs is still set on the quiz's Runs tab, which selects several runs at once ([ADR-0065](0065-scoreboard-by-percent-and-shared-boards.md)).
