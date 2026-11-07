# B5 Preview, test links and CSV import: design

Status: approved 2026-11-07. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

Two gaps stop an organiser preparing a real quiz with confidence.

- They cannot see a draft as a participant would, and cannot let a colleague try a quiz without opening it to the public (`FR-13`, [ADR-0017](../../_architecture/adr/0017-preview-vs-isolated-test-mode.md)).
- A quiz in three languages has to be typed into the editor question by question. The organiser already has content as text: `kv_z_17_listopad_st_tnost_a_evropa.md` in the repository root holds 5 questions in cs/en/uk with up to 5 options, one to four correct answers, an explanation and a source. It is sample data, and its format is not binding **[user]**. Spreadsheets and LLMs should both be able to produce the file (`FR-40`, `FR-41`, [ADR-0032](../../_architecture/adr/0032-csv-schema.md)).

## Goals

1. An admin clicks through a quiz exactly as a participant would, and nothing is stored **[user]**. Works on the draft and on any published revision **[user]**.
2. An admin creates test links. Each link is fixed to one version the admin picks, including a frozen copy of the draft **[user]**. Anyone with the link can play without an account **[user]**.
3. A link can have an end date, and can be cancelled at any time **[user]**.
4. The admin sees test attempts with score and time, separately from runs, and can delete them **[user]**. They never count anywhere else **[docs]**.
5. A CSV, or a ZIP with a CSV and images, imports as a new quiz, into a quiz's draft, or into a bank **[docs]** (`FR-40`). Nothing is ever published by import **[docs]**.
6. Rows with errors are listed by row; the good rows are imported **[docs]** (`AC-13`).
7. Questions of a quiz or a bank can be downloaded and imported back **[user]**.

## Non-goals

- Markdown or JSON import. JSON stays LATER as a separate module **[docs]**.
- Categories. A category column is reported as unused and skipped **[user]**. Recorded as a new `TD-NNN` through `make tech-debt-create`.
- Answers per question on the test attempts page **[user]**.
- Export of results, participants and statistics: D2 **[docs]**.
- Draw rows in the CSV. An export of a quiz with draw rows says they were left out; questions in a bank are exported from the bank **[call]**.
- Preview of a single bank question **[call]**.
- Limits on how often a test link can be played: D5, like the rest of the public pages **[call]**.

## Anti-goals

- A preview writes a row: no attempt, no run, no audit entry, no change to the draft.
- A test attempt appears in a run, a run count, a score list, a statistic, or anything built later for these. Public quiz address never reaches a test run, and a test run never decides what a quiz's state or main button is.
- A cancelled or expired link still plays. This includes a tester who has the page open: submitting after the link ended is refused with a clear message.
- A published revision changes because of a link, or a frozen copy changes because the draft did.
- An import publishes anything, or changes a published revision.
- An import silently loses data. Every unused column and every dropped language is in the report.
- A ZIP is unpacked to disk, exceeds its limits while being read, or a name inside it reaches the file system.
- A spreadsheet runs a formula from an exported cell.

## Preview

**Entry:** a Preview action in the quiz workspace, for the draft; each revision in the history has one too **[call]**. Admin login required. Not available to participants.

**Behaviour:** the same pages and the same rules as play, using the quiz's current settings: navigation mode, shuffling, draw rows drawn anew on each preview **[user]**, reveal moment and level, the result at the end, language switching. A bar on every step says this is a preview and offers the way back. Nothing is stored **[user]**.

**State:** what a preview needs between requests (revision or draft, chosen questions, seed) travels in a signed token, never in a table **[call]**. If the draft changes under an open preview, the next step says so and offers to start again **[call]**.

**Incomplete draft:** a draft may lack a translation or a correct answer. The preview shows the problems found by the publication check at the top, and a question that cannot be shown or graded says so in its place. It is never a server error **[user]**. A draft with no questions gets a message pointing to the editor **[call]**.

## Test links

### Model

A link is a hidden run of a new kind, fixed to its revision **[call]**. This refines ADR-0017: instead of a flag on each attempt, the run carries it, so reusing `attempts.start`, `submit`, `check`, tokens and scoring needs no second path, and a filter has one place to look.

**Shape [call]:** `QuizRun` gains `kind` (`normal`, `test`). `one_open_run_per_quiz` and `run_no_per_quiz` apply to `normal` only, so one quiz can have many active links. A test run has no run number and takes none from the sequence, so "Run 4" is never a test. A separate table holds what is only about the link: token, end time, creator. A cancelled link closes its run (`CLOSED`). Expiry changes no stored state: it is a time check at start, submit and check.

This needs care where runs are looked up today. The builder must go through every use of `QuizRun` and `Attempt`, at least: `_open_round`, run numbering in `authoring.py`, `quiz_state.py`, `public.py`, the admin run pages and counts, `usage.py`. A publication never moves a test run **[call]**. A test proves it: a quiz with an active link behaves everywhere as if the link did not exist (`AC-46`).

`usage.py` counts active links, since their attempts need the modules too **[call]**.

### Choosing the version

The form lists the draft, the current published revision and older ones **[user]**.

Choosing the draft stores an immutable copy of its content with its draw pool, the same as publication stores, in a new revision status that is neither published nor shown in history, published lookups or the change overview **[user]**. The draft itself stays a draft. After further edits the old link stays on the copy, and a new link is needed for the new content **[user]**.

A draft that fails the publication check cannot be copied: the form lists the problems, as the publish page does **[call]**. A tester should never meet a broken question; preview is the place for those.

### Lifetime

- Optional end date and time, none by default **[user]**.
- Cancel: the link stops at once, attempts stay. Delete: removes the link, its attempts and any frozen copy **[user]**, after the page's usual confirmation **[call]**.
- An archived quiz stops its links **[call]**.
- Each creation, cancel and deletion goes to the audit log **[call]**.

### The address

`/t/<token>`, with 32 random bytes **[call]**. The token is kept readable, as the admin needs to copy the link again later **[call]**. Security here is proportionate: a leak shows questions and lets people play in a run that counts for nothing. The creation form says in one line that anyone with the link sees the questions and the correct answers revealed by the quiz's settings **[call]**. The address must not appear in application logs **[call]**; the deployment's access logs are checked and, if they record paths, the token is masked there or the docs say so **[call]**. Pages carry `noindex` and `Referrer-Policy: no-referrer` **[call]**.

A tester sees a clear mark that this is a test and that the result does not count **[call]**. Anyone can play repeatedly **[call]**. An invalid, cancelled or expired link gets one plain message, the same for all three **[call]**.

### The admin page

A tab in the quiz workspace **[call]**: links with version, creation time, end, state and number of attempts; copy, cancel, delete. For each link its attempts: state, score, duration, start. Delete all attempts of a link **[user]**. No participant data exists on these attempts **[docs]**.

## CSV import

### The file

One format for import and export, per [ADR-0032](../../_architecture/adr/0032-csv-schema.md): one row per question, one column per language, plain columns for common things, `config_json` where a type needs it **[docs]**. CSV for spreadsheets and LLMs alike **[user]**. UTF-8 with or without BOM, comma or semicolon detected **[user]**. Another encoding is refused with a message saying to save as CSV UTF-8 **[call]**.

Quiz name, description, languages and settings are the first row of the same file, with `row_type=quiz`, instead of a separate file **[user]**. A new ADR refines ADR-0032.

Shape **[call]**, exact names left to the builder:

```text
schema_version,row_type,type,slug,locales,default_locale,title_cs,description_cs,prompt_cs,option_1_cs,option_2_cs,correct,points,scoring,explanation_cs,sources,image,image_alt_cs,option_1_image,option_1_image_alt_cs,setting_show_sources,config_json
```

- `correct` holds option letters: `A` or `A,C`, as the sample has them. Numbers are not accepted, so a file has one way to say it **[call]**.
- Each question type defines its own columns through its contract, as ADR-0032 says **[docs]**. Plugins keep parsing their own data; the importer knows no type **[call]**. Choice and matching (pairs, ordering) are both covered; matching may use `config_json` **[docs]**. Row ids inside a definition are generated on import **[call]**.
- Question settings use `setting_<key>` where their scope includes a question; quiz settings on the quiz row where it includes a quiz. Scopes come from the catalogue, so a new setting works without touching the importer **[call]**.
- Sources are one cell, one per line **[call]**.
- A bank question's tags have a `tags` column, so a bank survives the round trip. Imported into a quiz's draft, they are unused and reported **[call]**.
- A downloadable sample built from the user's 5 questions, plus a description of the columns written so it can be handed to an LLM **[user]**. Category is not in the downloadable sample. It stays in a test fixture, to prove it is reported **[call]**.

### Images

- `image` holding `https://…` is an address. Anything else is a file name inside the ZIP. A file name without a matching file, or without a ZIP, is a row error. So addresses and local files cannot be confused **[docs]** (`AC-13`).
- Both address and ZIP file are supported **[user]**. A ZIP file goes through the same processing and limits as an upload (ADR-0028) **[docs]**. An address goes through the same fetch and rules as ADR-0043, so the internal-address protection holds **[docs]**.
- An image that cannot be fetched does not stop the question **[user]**. It is saved with its address and no copy, and the report names it. Publication in `copy` mode blocks it and names the question, and the next save of the question tries again, both as in B4 **[user]**. This is a deliberate difference from the editor, which refuses in `copy` mode: a file should not fail over one temporary outage **[user]**.
- Fetching happens at the confirm step, never at the check **[call]**. One confirm counts as one save, so ADR-0043's budget of 25 s for all addresses applies unchanged, and there is no deployment change **[call]**. What does not fit is treated as a failed fetch. It takes one of the 8 threads **[call]**.

### ZIP rules

**[call]** The uploaded ZIP is kept whole as one file (see Steps). Its entries are read entry by entry, never extracted to disk. Images are processed and stored at the confirm step only, so an unconfirmed import stores no media. The builder measures a confirm at the entry limit in Docker; if it takes over 60 s, the entry limit goes down. One `.csv` at the top level, otherwise refused. Names are only compared against the `image` cells. Limits: upload 100 MB, 500 entries, 200 MB unpacked in total, each image the ADR-0028 limit, and reading stops at the limit rather than trusting declared sizes. Not a ZIP, encrypted or corrupt: a message.

CSV limits: 5 MB and 2000 rows **[call]**. These are constants, like ADR-0028, not settings: they guard the server, are not per-quiz, and no one has asked to change them **[call]**. The provider's manifest therefore says `settings: []`.

### Steps

1. **Upload.** From the quiz list (new quiz), a quiz's editor (add to its draft), a bank page (add to the bank) **[docs]**.
2. **Mapping, only if something does not fit [user].** A column the importer does not know opens a page with a select per unknown column: an existing target, or "do not use", which is preselected **[call]**. So a file with a category needs one click and then reports it **[user]**.
3. **Check.** Nothing is stored in quiz content yet; this is the dry run (`FR-41`) **[docs]**. Counts, errors and warnings per row with file row number and column, and the first few questions as the admin would read them **[call]**.
4. **Confirm.** Imports the good rows **[docs]**.
5. **Report.** What was added, what was skipped and why, what was unused, with a link to the draft or bank **[call]**. The audit log records the counts, never content **[call]**.

Between steps the report is in an `import_job` row with `expires_at` **[docs]**, and the uploaded file on the media volume in a directory that is never served **[call]**. Each admin has at most one unconfirmed import: a new upload replaces the previous one, so disk use is bounded at 100 MB per admin **[call]**. A job lasts 24 h and expired ones are removed when any later import runs, as there is no scheduler **[call]**.

### What is an error

**Row error, row skipped [call]:** unknown type or scoring; no prompt in any language; `correct` naming a missing option; points not a positive whole number; a setting value not offered, or a setting not allowed on a question; an invalid address; a missing ZIP file; a value the type's parser refuses.

**Warning, row imported [call]:** a missing translation, a question with no correct answer, or a missing alternative text, since a draft may be incomplete and the publication check names these **[docs]**; text in a language the target does not list, which is dropped and reported.

**Whole file refused [call]:** wrong encoding; unreadable; unknown `schema_version`; a new quiz with no valid quiz row. A file where no row is usable creates no quiz and no draft.

A taken slug gets a number added, with a warning **[call]**. A quiz row imported into a draft or bank is ignored with a warning, so a full export can be used anywhere **[call]**. Into a draft, questions are added after the existing ones, and an archived quiz is refused **[call]**.

## Export

A Download action on a quiz and on a bank **[user]**. Content: the questions, and for a quiz the quiz row. For a quiz, the draft if there is one, otherwise the current published revision **[call]**. A CSV when no image is a local file, otherwise a ZIP with the CSV and files, so what is exported can always be imported **[call]**. An exported image with a source address gives the address, without a file **[call]**.

Formula protection on every text cell, with a character added in front of a cell starting with a dangerous character, removed on import, so the round trip gives the same data **[docs]**. It must be lossless: a text that really starts with that protective character survives the round trip **[call]**.

The download holds answer keys, so it is admin only and audited **[call]**.

## Architecture

- `app/providers/csv_io/` provides `ImporterProvider` and `ExporterProvider` **[docs]**. Files and rows are its job, the contract it presents is plain data; the domain saves questions; the API joins them, as with media **[call]**.
- Question types gain what they need to read and write their columns, as a contract extension covered by the shared contract tests, so a future type cannot skip it **[call]**. The B6 types will then have to provide it.
- Domain cannot import providers **[docs]**.

## Documents

- New ADR: preview and test links, refining ADR-0017.
- New ADR: one file with a quiz row, export of questions in Stage B, failed image fetches on import, refining ADR-0032 and ADR-0043.
- `providers/csv-io.md`, `modules/domain.md`, `data-model.md`, `security.md`, `privacy.md` if needed, `roadmap.md` (D2 narrows to results and the rest), `docs/plugin-api.md`, `CLAUDE.md`: updated.

New acceptance criteria, Stage B, from AC-45:

- **AC-45 Preview:** clicking through a draft and a published revision in each navigation mode stores nothing: row counts in all tables stay the same. An incomplete draft shows its problems, never a server error. The preview is refused without login.
- **AC-46 Test isolation:** a quiz with test attempts shows the same runs, counts, state and main button as one without. The public page never reaches a test run. Publishing moves no test run.
- **AC-47 Test links:** a link plays its chosen version without login. Changing the draft or publishing leaves a link's version unchanged. A cancelled, expired or invalid link gives the same message, also when submitting from an open page. A draft failing the publication check cannot be sent to test.
- **AC-48 Test attempts:** the admin sees them per link and can delete them. Deleting a link removes its attempts and frozen copy, and nothing else.
- **AC-49 Import flow:** nothing changes until confirmation. A file with good and bad rows imports the good ones and lists the others with row and column. No quiz or draft is created if no row is usable.
- **AC-50 Sample:** the sample with category columns imports as a draft in cs/en/uk with all texts, correct answers, explanations and sources, and reports the category as unused.
- **AC-51 Import images:** an address and a ZIP file are told apart; a missing file is a row error. A failed address keeps the question, warns, and blocks publication in `copy`. The internal-address protection holds. A ZIP over any limit is refused without being unpacked.
- **AC-52 Round trip:** export followed by import gives a quiz with the same content, for both question types, images, settings and a text beginning with a formula character. An exported cell never starts with a formula character.

## Left to the builder

Names of fields, routes and tables not given above; exact column names, within the shape above; how the preview reuses the play views; the layout of the pages, consistent with the existing workspace; automated tests use a local fake, never the network; verification in Docker, as usual, without touching `kvizotron-browser` data.
