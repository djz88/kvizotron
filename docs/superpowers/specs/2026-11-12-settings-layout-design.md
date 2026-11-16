# Settings pages: order, compact rows and search — design

Date: 2026-11-12. Status: draft for approval.

## Why

The settings pages (global `/admin/settings`, the quiz's "Address and behaviour", the run plan) are long and hard to scan:

- every setting is a label with a dropdown under it, also for a yes/no choice;
- the form is 40rem wide, so a two-word dropdown takes a whole row;
- inside a group the order is the order in which settings were added to the catalogue, so a setting and the one that depends on it are apart (`navigation_mode` … `page_size`, `reveal_moment` … `reveal_level`);
- "Scoreboard" has 15 settings, including three about rewards and one about revisions;
- there is no way to find a setting by name.

## What

1. **Two-column rows.** On a screen of at least 48rem, the label is on the left and the control on the right, with the help text in small type under the control. Each setting is one `.setting-row`. Long controls (time zone, colours, retention) take the whole row. A narrow screen keeps label above control. The settings form is up to 56rem wide.
2. **Short choices as radio buttons in a row.** A choice setting with at most 3 values (without the "Use global setting" one) is shown as radio buttons side by side instead of a dropdown. On the quiz page "Use global setting (now: …)" is the first radio. The submitted values do not change. Settings with 4 or more values stay dropdowns.
3. **Alphabetical inside each group, dependants under their parent** (the user: "flating = abecedně"). Settings of a group are sorted by their translated label in the admin's language, compared folded (`bank_folders.fold`, so `Č` sorts as `C`). A dependant is not sorted on its own: it follows its parent, indented, its siblings sorted alphabetically too:
   - questions per page → under navigation mode;
   - what to show → under when to show answers;
   - same nickname twice → under nickname;
   - names during the run, participant without a nickname, anonymous label (quiz page) → under public scoreboard;
   - main and accent colour → under colours (they keep this order).

   The group membership changes:
   - **Rewards (new group):** rewards of a new run · several thresholds · contact with winners (from Scoreboard);
   - "None of the answers" → **Playing** (it changes what the participant sees at a question);
   - "Runs with several revisions" → **Technical** (beside "new version during a run").

   Module settings follow the same rule, so no list of keys has to be kept up to date. Non-setting fields of the branding section keep their form order.
4. **Scoreboard columns as one block.** The four "Column: …" settings are one fieldset "Scoreboard columns" with short labels (Score, Percent, Time submitted, Duration). They remain four settings in the data and the forms.
5. **Search, looking like the bank's.** A search form above the groups, the same markup as the bank (`form.bank-search role=search`, `input type=search name=q`, button "Search"). It is a GET `?q=` and works without JavaScript.
   - It matches the label, the help text and the labels of the values, in the admin's language, ignoring case and Czech diacritics (`bank_folders.fold`), so `zebricek` finds "Žebříček".
   - With a query, the Basic/All filter does not apply: an advanced setting is found in Basic as well.
   - A setting that does not match is rendered with the `hidden` attribute, not left out. Its value is still submitted, so saving from the search view keeps every value and every quiz override. Leaving it out would save it empty and clear a quiz's override.
   - A group without a match is hidden, and so is its link in the section panel. With no match the page says "No setting matches." and offers "Clear the search".
   - Pages: global settings and the quiz's settings. The run plan keeps its collapsible groups without search.

## Not in scope

- Changing what a setting does, its values, defaults or scope.
- Search on the run plan, the branding fields or the quiz's title and languages.
- Live filtering while typing (JavaScript).

## Calls made here

- The search hides non-matching rows instead of leaving them out, so that saving cannot clear overrides (see 5).
- Radios only for at most 3 values, so that the same setting looks the same on the global and the quiz page.
- The columns stay four settings with three values each on the quiz page; checkboxes cannot say "use global".
- "Runs with several revisions" goes to Technical beside "new version during a run"; "None of the answers" goes to Playing.
- Alphabetical order differs between cs and en; that is accepted, the parent/dependant pairs stay together in both. The columns block sorts by its legend "Scoreboard columns".
- The parent/dependant pairs are a map in the API layer (`admin_view.CHILD_OF`), not in the catalogue: it is about the page.
- The new group `rewards` changes `SETTING_GROUPS` in `app/contracts` and the manifests of `rewards` and `results`; ADR-0052 gets an addendum.
