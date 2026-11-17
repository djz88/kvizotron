---
status: accepted
date: 2026-11-08
---

# ADR-0052: Settings in named groups with a basic level, pages of questions, one question at a time by default

## Context and Problem Statement

By C4 the admin had 38 global settings in one list, 50 fields on a quiz's Settings tab and 25 on a run plan. The settings were added where each milestone needed them ([ADR-0042](0042-settings-inherited-and-declared.md) fixed how they inherit, not how they are shown). The common work, making a quiz and running it, was buried among rarely touched options. Participants could play all questions at once or one at a time, with nothing in between.

## Decision Drivers

* An admin finds the common settings without scrolling through the rare ones.
* A setting an admin changed is never hidden from them.
* A module adds a setting to the pages without the domain listing it ([ADR-0037](0037-providers-and-plugins.md)).
* Pages work without JavaScript.
* An existing quiz plays the same after an update.

## Considered Options

* Groups and a basic level as setting metadata, with a "Basic / All" switch.
* Advanced settings collapsed in each group.
* Advanced settings on a separate page.

## Decision Outcome

Chosen option: groups and a level as metadata with a switch, because one list in metadata orders every settings page the same way and is cheap to correct.

* Each setting has a `group` (`playing`, `answers`, `participants`, `scoreboard`, `rewards`, `data`, `look`, `technical`, in this order; `rewards` since the addendum below) and a `level` (`basic` or `advanced`), in the domain catalogue or in the module's `SettingDeclaration`. Without them a setting is `technical` and `advanced`. Nothing decides by them except the admin pages.
* A switch "Basic / All" in the admin bar, remembered in the cookie `kvz_admin_view`, hides advanced settings and the deeper sections of a run page. A value that differs from what it inherits is shown in both views. Since D1 the switch sits in the section panel of the settings pages, the run plan and the run page, not in the admin bar; see [ADR-0054](0054-branding-owned-by-domain-and-theme.md).
* The run plan shows its time fields and collapses each group unless it holds a value that differs from the quiz's or a refused one.
* A fourth navigation mode, pages of questions, with a page size of 2 to 20 (default 5) set globally or on a quiz. It cannot go with answers after each question, like all at once.
* The default navigation becomes one question at a time with going back. Migration 0015 stores "all at once" as the global value on a database that already has an admin or a quiz, so an existing installation, including its new quizzes, plays as before.

### Consequences

* Good, because the common settings fit on a short page, and every settings page has the same order.
* Bad, because a global advanced value affects quizzes without showing in "Basic"; a line under each group says how many settings are hidden.

## More Information

Design: `docs/superpowers/specs/2026-11-08-c45-ui-simplification-design.md`.

### Addendum 2026-11-12: order, rows and search

* A group `rewards` between `scoreboard` and `data` holds the three reward settings; `none_option` moved to `playing` and `revision_mode` to `technical`. Since 2026-11-17 `revision_mode` sits in `scoreboard`: after ADR-0065 it only decides how the scoreboard ranks attempts of several revisions, so that is where an admin looks for it.
* The groups on a page are alphabetical by their label in the admin's language (the order of `SETTING_GROUPS` only lists them); a page's own sections stay where they are (Time first; Name, logo and texts, and Copy and archive last), and they are drawn like the groups.
* Inside a group the order is no longer the catalogue's: settings are alphabetical by their translated label, so it differs between languages, and a dependant (`admin_view.CHILD_OF`) follows the setting it depends on, indented. The order is the admin pages' business, so it lives in the API layer, not in the catalogue or the manifests.
* A choice with at most three values (not counting "use global") is drawn as radio buttons; the four scoreboard columns are one block. The submitted values are unchanged.
* The global and quiz settings can be searched (`?q=`). A search shows every setting regardless of Basic or All and draws those that do not match `hidden`, never leaves them out: leaving them out would save them empty and clear a quiz's overrides. [AC-168](../acceptance-criteria.md).
