# C4 Results: scoreboard, revision modes, statistics: design

Status: approved by the user 2026-11-08. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

A competition ends with a ranking. Today a participant sees only their own score, and the admin sees a flat attempts table. Organisers want a scoreboard they can show on a projector during the event as motivation, and the official order once it ends (`FR-29`, `FR-30`). They also want to see how a quiz went: how many played, how the scores spread, which questions were hard (`FR-43`).

## Goals

1. **Public scoreboard per run**, with visibility, columns and ordering chosen by the admin (`FR-29`) **[docs]**.
2. **One official attempt per participant**, best or first valid (`FR-27`) **[user]**, **[docs]**.
3. **Revision modes** for runs that switched revision: separate, merged when compatible, latest only (`FR-30`, ADR-0008, AC-06) **[docs]**.
4. **Anonymous participants** shown the way the admin chooses, with a label the admin can rename **[user]**.
5. **Projector mode** that refreshes itself **[user]**.
6. **Statistics** for a run and a comparison of a quiz's runs (`FR-43`) **[user]**.
7. **Sorting the admin attempts table**, deferred from C2 **[docs]**.

## Non-goals

- Rewards, thresholds and the draw: C5 **[docs]**.
- Export of results and statistics: D2 **[docs]**.
- Deleting results when retention ends: D3 **[docs]**.
- A scoreboard across several runs or quizzes **[call]**.
- Charts from a JavaScript library: bars are plain CSS **[user]**.

## Anti-goals

- An e-mail or an internal id on any public page **[docs]**.
- A public scoreboard before the admin turns it on; existing quizzes change nothing **[user]**.
- A public scoreboard while a photo still waits for grading **[docs]**.
- Test attempts in any public projection or in the real statistics **[docs]**.
- A rank that changes between two loads without a new submission or grading (ties are deterministic, ADR-0026) **[docs]**.
- One person appearing several times because they played again from the same browser **[user]**.

## Behaviour

### Settings

All are settings inherited global → quiz, copied onto the run when it is planned or opened, and editable on the plan form, the same path as the participant rules in C2 **[user]**, **[call]**. They have no question level: they concern the whole run (ADR-0042).

| Setting | Values | Default |
|---|---|---|
| Scoreboard visibility | hidden, live, after the run ends | hidden **[user]** |
| Names during the run | shown, anonymised | shown **[call]** |
| Participant without a nickname | anonymous, not listed | anonymous **[user]** |
| Anonymous label | text per quiz language with `NN` for the number | "Hráč NN" / "Player NN" / "Гравець NN" **[user]** |
| Official attempt | best valid, first valid | best valid **[user]** |
| Columns | score, percent, submission time, duration (each on or off) | score and percent on **[user]**, **[call]** |
| Second sort | submission time, duration | submission time **[user]**, **[call]** |
| Ties | shared place, earlier submission, random | shared place **[docs]** |
| Revision mode | separate, merged, latest only | separate **[docs]** |
| Public results of an archived run | off, on | off **[docs]** |

- Visibility, names during the run and the second sort can change on a running run, since they change only what is shown **[call]**. The official attempt, ties and revision mode stay fixed once the run opens, as they decide the order **[call]**, except that merging is a separate admin action (below) **[docs]**.
- "Merged" cannot be preset: it exists only as the admin's decision on a run with equal maximum points, after seeing the differences, and it is audited (AC-06) **[docs]**.
- The anonymous label is a quiz field per language, not a catalogue setting, since it is free text in several languages **[call]**. It follows the quiz live, like the title, so an edit shows on a running scoreboard **[call]**. Without `NN` the number is appended **[call]**.
- Duration exists only under the data profile `detailed`; the column and the second sort by duration are offered only then **[docs]**.
- A public scoreboard is refused together with the data profile `none` **[docs]**. It is also refused together with answers after each question (AC-18) **[docs]**.

### Who is a row

- A run whose scoreboard is not hidden needs a participant, like a run that forbids repeating: it sets the cookie `kvz_p_<run>` and stores a participant row **[user]**. One browser is one row, whatever the repeat rule. This refines ADR-0049 (ADR-0051 records it); a run with repeating allowed and the scoreboard hidden still sets no cookie, and AC-70 is reworded to say so without changing what it guards **[call]**. `docs/privacy.md` names the new case **[call]**.
- If the admin turns a hidden scoreboard on while the run is running, attempts submitted before have no participant: each appears as its own anonymous row, and the statistics count it as one participant **[call]**.
- A row is the participant's official attempt among their submitted, valid attempts: the best score, or the first submitted; between equal scores of one participant the earlier counts (ADR-0026) **[user]**, **[docs]**.
- An attempt still waiting for grading is not official until graded; while any attempt of the run waits, the public scoreboard is hidden and says why (AC-16) **[docs]**.
- Test attempts never appear **[docs]**.

### Names

- During a live run with "anonymised", every row shows the anonymous label with a number stable for the participant within the run **[user]**. After the run ends, nicknames are shown **[user]**.
- A participant without a nickname is shown with the anonymous label, or not listed, as the setting says **[user]**. A participant who is not listed still sees their own place on their result **[call]**.
- The participant's own row is marked on their device ("you") **[call]**.

### Revision modes

- **Separate**: one table per revision, newest first, each with its own maximum **[docs]**. The official attempt is chosen within each table, so a participant who played on two revisions appears once in each **[call]**.
- **Merged**: one table; allowed only when every revision of the run has the same maximum points; the admin sees the changes between revisions (the existing change overview) and confirms; the decision is audited; it can be undone **[docs]**, **[call]**.
- **Latest only**: only attempts on the run's current revision **[docs]**.

### Pages

- Public scoreboard at `/q/<slug>/r/<run>/scoreboard`, linked from the quiz page and the result page when visible **[user]**, **[call]**.
- It refreshes itself every 15 seconds **[user]**, without reloading the page, and stops when the run has ended and nothing waits for grading **[call]**.
- A projector button switches to full screen with large type, rank, name and score only, in the quiz's language **[user]**, **[call]**.
- The result page shows the participant's own place, "4. of 30", when the scoreboard is visible to them **[call]**.
- An archived run shows its public scoreboard only with the archived-results switch on, and only the allowed columns (ADR-0031) **[docs]**. Ending the view when retention expires comes with the retention job in D3 **[call]**.
- The admin sees the scoreboard of any run at any time, with names, whatever the visibility **[docs]**.

### Statistics

- A "Statistics" section on the run page **[user]**:
  - participants, started attempts, submitted attempts, unsent attempts;
  - average, median, lowest and highest score;
  - distribution of scores in ten bands as CSS bars;
  - per question: how many answered, average points, share of full points, ordered by the revision's question order;
  - the same split by revision when the run had more than one.
- Test attempts are counted separately, on test links only **[docs]**.
- Under the data profile `none` only the count exists. Per-question numbers need every answer stored (`answers` or `detailed`); under `score` the section is not shown and says it needs a profile that keeps answers, rather than showing only the photo questions **[docs]**, **[call]**.
- On the quiz's "Runs" tab, a comparison of its runs: run number, dates, participants, submitted attempts, average score and percent **[user]**.

### Admin attempts table

- Sortable by name, score, time and duration (when stored), by clicking the column header, without JavaScript (a query parameter) **[docs]**, **[call]**.

## Constraints

- The scoreboard is a projection, not a source of truth: nothing new is stored per attempt apart from what grading already stores **[docs]**. The random tie value is stored once per run (ADR-0026) **[docs]**.
- The view lives in a plugin behind `ResultViewPlugin` (`app/plugins/results/`), declaring its settings in the manifest **[docs]**.
- ADR-0008, ADR-0026, ADR-0031, ADR-0033, ADR-0035, ADR-0049 apply. A new ADR (0051) records the scoreboard cookie rule, the official attempt, anonymised live names and the anonymous label **[call]**.
- Every text in cs, en, uk; a run is `běh` / `run`. Phone width, light and dark, keyboard; no build step **[docs]**.
- New `AC-xx` from AC-81, and tests for AC-06, AC-16 (Stage C part) and AC-18 **[docs]**.

## Risks

- **Load from refreshing**: 50 open scoreboards every 15 s is about 3 requests per second; the projection must be one query per table, cached for a few seconds **[call]**.
- **Cookie on runs that had none**: turning the scoreboard on adds the cookie; the plan form says so, like the repeat rule **[call]**.
- **Anonymised live view and the participant's own row**: the "you" mark must come from their own cookie, never from the name **[call]**.
- **Merging revisions with different questions**: equal maximum points do not mean equal difficulty; the admin decides knowingly (ADR-0008) **[docs]**.

## Left to the builder

- Storage of the scoreboard settings on the run (one JSON field like the participant rules, or columns).
- The refresh mechanism (HTMX polling of a fragment is the expected one).
- Projector layout and font sizes.
- The cache of the projection.
- Exact statistics queries.

## Verification

- `make quality` and `make smoke` **[docs]**.
- Tests through real addresses: each visibility; anonymised live names that turn into nicknames after the end; unnamed participants anonymous and not listed; best and first official attempt with a repeat from the same browser; every tie policy gives the same order on repeated loads; the three revision modes and the refused merge with different maxima; hidden while grading is pending; refused with profile `none` and with answers after each question; archived switch; no e-mail or id in the public HTML; statistics numbers on a known data set; test attempts excluded; attempts table sorting.
- A browser walkthrough on new quizzes in `kvizotron-browser` without deleting its data **[user]**: live scoreboard updating while another browser submits, projector mode, anonymised then named after the end, own place on the result, statistics and run comparison; phone width, dark mode and Ukrainian.
