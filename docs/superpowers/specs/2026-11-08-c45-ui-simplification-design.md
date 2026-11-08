# C4.5 UI simplification: admin and public: design

Status: draft 2026-11-08, for the user's approval; builder check done. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

Before branding (D1) gives the pages their final look, the pages themselves should be simpler. Each milestone added settings and sections where they fitted at the time. The admin now has 38 global settings in one flat list (about 5,900 px tall), 50 fields on a quiz's Settings tab (7,800 px), 25 on the run plan, and 8 sections on a run page. The common job, "make a quiz and run it tonight", is buried among rarely touched options **[user]** (asked for practicality and a split of basic from deeper operations). Participants, too, get either one long page or one question per click, with nothing in between **[user]**.

## Goals

1. **Admin: basic versus everything.** A switch "Basic / All" hides the deeper settings and sections, so the common work fits on short pages **[user]**.
2. **Admin: grouped settings.** Every settings page (global, quiz, run plan) shows the same named groups in the same order **[user]**.
3. **Admin: a run plan that shows what differs.** The plan shows the time fields and only the settings that differ from what the run would inherit; inherited ones are collapsed or behind the switch **[user]**.
4. **Admin: fewer quiz tabs.** Questions, Runs, Grading, Settings, and "More" with Test links and Revisions **[user]**.
5. **Public: pages of several questions** as a new way through a quiz **[user]**.
6. **Public: one question at a time as the default for new installations** **[user]**, without changing existing quizzes **[call]**.

## Non-goals

- Colours, logo, typography, editable texts: D1 **[docs]**.
- New settings beyond the page size, or removing any setting: every setting keeps its meaning and scopes **[call]**.
- The quiz list on the admin home page, the question editor, the grading page and the bank pages **[call]**.
- Per-admin permissions or roles **[call]**.

## Anti-goals

- A setting the admin changed that the "Basic" view hides: a value that differs from what it inherits is always shown **[call]**.
- An existing quiz that plays differently after the update **[call]**.
- A page that needs JavaScript to reach a setting, or a setting reachable only by a URL nobody links **[docs]** (pages work without JavaScript).
- A participant who loses answers when moving between pages **[docs]** (resume, ADR-0050).

## Behaviour

### Admin: the switch "Basic / All"

- One switch in the admin header, "Basic" or "All", remembered in the browser with a cookie, the same for every page. It works without JavaScript (a link or a small form) **[user]**, **[call]**. Default "Basic" **[call]**.
- Each setting in the catalogue is marked basic or advanced, in the catalogue or the module's manifest, beside its scopes **[call]**. The first cut **[call]**, to be corrected while reading:
  - **basic**: navigation mode, page size, time limit, reveal moment, repeat attempts, nickname, scoreboard visibility, data profile, colours, time zone (global only);
  - **advanced**: all the others.
- "Basic" hides advanced settings except those whose value differs from what they inherit (on a quiz: an override; on a run: a value other than the quiz's) **[call]**. A line under each group says how many are hidden, "3 more in All" **[call]**.
- On a run page, "Basic" shows the overview, scoreboard, statistics and attempts. The access code, the data section, merging revisions and the period are under "All" **[call]**. The access code shows in "Basic" when one is set **[call]**.

### Admin: groups

The same groups in this order, on the global settings page, a quiz's Settings tab and the run plan, each a heading with an anchor and a short list of links to them at the top of the page **[user]**, **[call]**:

| Group | Settings |
|---|---|
| Playing | navigation mode, page size, shuffle questions, shuffle options, time limit, resume in this browser, unfinished attempt |
| Answers and result | reveal moment, reveal level, sources, "None of the answers", who sees stored answers, who sees a photo |
| Participants | repeat attempts, nickname, e-mail, when to ask, same nickname twice |
| Scoreboard | the twelve scoreboard settings and the anonymous label |
| Data | data profile, retention period |
| Look and listing | colours, announce planned quiz |
| Technical | revision switch policy, external images, internal image addresses, grading view, time zone |

- Group and level are two optional fields of a setting's definition: in the domain catalogue for the settings the domain owns, and in `SettingDeclaration` for a module's setting. The catalogue already holds labels and help, so presentation metadata fits there; nothing in the domain decides by them **[call]**. A setting without a group goes to Technical, without a level is advanced **[call]**.
- The quiz's title, description and languages stay a separate first section, as they are published with a revision **[docs]**.

### Admin: run plan

- Visible: start, deadline, time limit, and a sentence "The run takes the quiz's settings" with a link to them **[call]**.
- Below it the groups as above, each collapsed (`<details>`) unless it holds a value that differs from the quiz's. A changed value opens its group on the next render **[user]**, **[call]**.
- Refusals (a scoreboard with profile `none`, after each with a visible board) still show at the field, and its group opens **[docs]**.

### Admin: tabs

- Tabs: Questions, Runs, Grading, Settings, More ▾ (Test links, Revisions) **[user]**.
- Grading shows its count when something waits. It is visible always, so the address does not move **[call]**.
- "More" is a `<details>` menu like the existing ones; the active page inside it marks "More" as current **[call]**.

### Public: pages of questions

- A fourth navigation mode "Pages of questions" with a page size, 2 to 20, default 5 **[user]**, **[call]**. The page size is set globally and on a quiz, not on a question, as it applies to the whole attempt **[user]**. It sits beside the navigation mode, owned by the domain like it **[call]**, and its help says it applies only to pages **[call]**.
- A page shows its questions, the progress "Questions 6–10 of 20", Back and Next; the last page has Submit **[call]**. Back is allowed, like "one by one, with going back" **[call]**.
- Answers on a page are kept when moving, the same way the step mode keeps them, and in the local copy (ADR-0050) **[docs]**.
- The time limit, automatic submission, banks, shuffling and required names work as in the step mode **[call]**.
- Answers after each question cannot go with pages, the same refusal as with all at once, also when the quiz inherits "after each" from the global value; a later global change falls back to the end of the attempt silently, as `Flow.conflict` does today **[call]**.

### Public: default navigation

- The catalogue default becomes "one by one, with going back" **[user]**.
- On an existing installation nothing changes, not even for quizzes created after the update: a migration stores "all at once" as the global value when none is stored **[user]**. An installation counts as existing when its database already has an admin or a quiz at migration time; a fresh one has neither and starts with the new default **[call]**. An admin who wants the new default changes the global value by hand **[user]**.

### Public: background

- The page background covers the whole page, not only the first screen (now it ends at the window height on a long quiz) **[call]**, found while preparing this design.

## Constraints

- Settings keep their keys, values and scopes; ADR-0042 applies. The page size is a new setting, so **REQUIRED** `kvizotron-add-setting` **[docs]**.
- A module adds a setting to a group through its manifest, without the domain listing it (ADR-0037) **[docs]**, **[call]**.
- Every text in cs, en, uk for public pages, cs and en for admin **[docs]**. Phone width, light and dark, keyboard; no build step **[docs]**.
- An ADR (0052) records the basic/advanced levels, the groups, and the new default with its migration **[call]**.
- New AC from AC-86 **[docs]**.

## Risks

- **Hidden settings surprise an admin**: an advanced setting that a global value changes affects quizzes without being seen in "Basic". The "N more in All" line names that something is hidden **[call]**.
- **The first cut of basic settings is wrong**: it is one list in metadata, cheap to change after use **[call]**.
- **Pages mode and resume**: the local copy must know the page; the step mode's handling is the model **[call]**.

## Left to the builder

- Where the level and the group live (catalogue fields or manifest keys) and how the cookie is named.
- The markup of the switch and of the group links.
- The page mode's URL and HTMX swaps, following the step mode.
- The exact migration.

## Verification

- `make quality` and `make smoke` **[docs]**.
- Tests through real addresses: each settings page lists the groups in order; "Basic" hides an advanced setting and shows it when overridden; the switch works without JavaScript and is remembered; the plan opens only groups with differences and a refused field's group; tabs with "More" and the current mark; pages mode with 12 questions and size 5 gives pages 1–5, 6–10, 11–12, keeps answers going back, submits with a timer; after each refused with pages; the migration keeps "all at once" for an existing installation and a new one starts with step mode.
- A browser walkthrough on new quizzes in `kvizotron-browser` without deleting its data **[user]**: global and quiz settings in both views, plan form, run page, tabs; a participant through pages on a phone in dark mode and Ukrainian; the long-page background.
