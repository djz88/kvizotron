# B3 Banks and flow: design

Status: approved 2026-11-07. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction. A layout sketch was shown to the user and agreed; its source is `.superpowers/brainstorm/2410103-1794031643/content/b3-banks-flow.html` (not in git).

## Why

Organisers want a quiz that differs between participants, drawn from questions they maintain in one place. They also want to choose how the quiz is walked through, and whether it teaches: learning quizzes show the correct answer and why, competitive ones do not.

## Goals

1. Question banks shared by all admins, and quizzes that mix their own questions with draws from banks.
2. Random order of questions and options.
3. Three navigation modes with a progress indicator.
4. Showing correct answers after each question or at the end, in three levels of detail.
5. An optional translated explanation on a question.

## Non-goals

- Showing answers after a run closes. It stays in `FR-23` and moves to Stage C **[user]**, since it needs a lasting result address and identity. The roadmap and `FR-23` note this.
- Storing participants' answers. Nothing here stores them, apart from which questions were drawn **[call]**.
- Inserting a chosen bank question permanently into a quiz **[user: not chosen]**.
- CSV import of banks: B5. Preview and test mode: B5.
- Blocking "after each question" with a scoreboard or rewards (AC-18): those arrive in Stage C, and the check arrives with them **[call]**. Recorded under C in the roadmap.
- Local resume after a reload: Stage C (`FR-22`).

## Anti-goals

- Two participants of one revision play for a different maximum.
- A bank edit changes a published revision or an attempt in progress **[docs]**.
- The page receives a correct answer before the rules allow it, or from a quiz that does not reveal it after each question.
- A mode that works only with JavaScript. Every quiz can be completed without it.
- Existing quizzes behave differently after the upgrade.

## Banks

**Model.** `question_bank` and `bank_question` per `data-model.md` **[docs]**, with these corrections **[call]**: a bank question stores the same dictionary a quiz question stores in a draft, including `sources` and `explanation`, plus `tags` as a list of strings. `labels` on the bank and `active` on the question are dropped as unused. `data-model.md` is updated.

**Administration.** New top-level item **Banks**, available to all admins **[docs: shared]**: list, create, rename, delete, and a bank page listing its questions with their tags and complete languages. The bank question editor is the quiz question editor with a tags field, and without points, because a draw row sets those **[user]**. The question's scoring strategy stays on the question **[user]**.

**Languages.** All three language fields are shown. A bank question must be complete in at least one language to be saved **[call]**. A language counts as complete when the question type's own publication check passes for it **[call]**.

**Deleting.** A bank question is deleted for good, since published revisions hold copies **[call]**. A bank referenced by a draw row in any quiz's draft or latest published revision cannot be deleted; the refusal lists the quizzes **[call]**.

**Tags.** Free text per question, trimmed, compared ignoring case **[call]**. The draw row offers the tags existing in the chosen bank.

## Draw rows

**In the quiz.** The Questions list holds own questions and draw rows in one order **[user]**. A row: bank, optional single tag **[user]**, count, points per question **[user]**. The row shows "usable 17 of 20".

**Usable.** A bank question is usable in a quiz when it matches the tag and is complete in all the quiz's languages **[user]**. Unusable questions are left out silently, and the count shows it.

**Publication.** Publication is blocked only when the rows cannot all be filled without repeating a question **[user, docs: no repeat]**. Two rows may overlap, so the check is whether a full assignment exists (bipartite matching), not a per-row count **[call]**. The message names the row.

**Copy.** Publication copies each row's usable questions into the revision, with the row's points applied **[docs, user]**. The snapshot keeps `questions` for own questions and gains the draw rows with their pool, plus the position of each row in the order.

**Maximum.** `max_score` is the sum of own question points and count × points per row, so it is the same for every attempt **[user]**.

**Bank changed since publication.** The quiz counts as having unpublished changes when a row's usable pool differs from the copy in the latest published revision **[user]**: the state and main button show it, and the change overview lists added, changed and removed bank questions. Today `has_changes` means "a draft exists"; it gains this second cause, and publishing with no draft creates one **[call]**.

**Returning to an older revision** copies its rows as rows and re-reads the bank at the next publication, like any other change **[call]**. If the bank no longer exists the row is a problem blocking publication until removed.

**Duplicating a quiz** copies the rows, which point to the same banks **[call]**.

## Attempt

At start the server fixes, on the attempt **[docs: FR-19]**:

- `selection_json`: the ordered list of question ids given, and a seed for option order.
- `settings_json`: navigation mode, reveal moment, reveal level.

The draw avoids repeats across all rows. Own questions keep their place and each row's questions take the row's position; with question shuffling on, the whole list is shuffled **[user]**.

`manifest_hash` in the token covers the selection, not the whole revision. Scoring, sources, reveal and the page use only the selected questions; answers to any other id are ignored **[docs: FR-19]**.

Randomness uses the operating system's generator, behind one function that tests can replace **[call]**.

**Switching to a new revision** (AC-19). Switching creates a new attempt on the new revision **[docs]**, so its maximum is simply the new revision's, and points come from the new revision **[call]**. An own question is kept as today. A drawn question stays selected when its row still exists in the new revision and the question is in that row's new pool; "unchanged" uses the comparison `_moved_answers` uses today **[call]**. A row with more places draws the rest; a row with fewer drops a random surplus; a removed row's questions go; a new row is drawn in full **[call]**. Answers to kept unchanged questions stay; the rest are empty and marked, as today.

## Settings

Five new keys in the existing catalogue, global with a quiz override, effective for new attempts immediately, and without creating a draft **[user]**. Attempts in progress keep theirs **[user]**.

| Key | Values | Default **[call]** |
|---|---|---|
| `navigation_mode` | `all_at_once`, `step_back`, `step_no_back` | `all_at_once` |
| `reveal_moment` | `never`, `at_end`, `after_each` | `never` |
| `reveal_level` | `verdict`, `answers`, `explanations` | `verdict` |
| `shuffle_questions` | `off`, `on` | `off` |
| `shuffle_options` | `off`, `on` | `off` |

Levels are cumulative **[user]**: `verdict` shows whether each question is right; `answers` adds the correct answers; `explanations` adds the explanation.

**Conflict.** `after_each` needs a step mode **[user]**. The form refuses a combination it can see: the global form for the global values, the quiz form for the effective ones. When a later global change creates the conflict in a quiz, that quiz uses `at_end` and its settings page shows a warning **[user]**.

`none_option` is unaffected. `show_sources` stays separate from the levels **[call]**.

## Shuffling options

`shuffle_options` applies to Choice **[user]**. Yes/no is never shuffled, and "None of the answers" stays last **[call]**. The setting does not touch Matching in any mode, which keeps the rules in `plugins/question-types.md` **[user]**. The order follows from the stored seed and the question id, so a re-render gives the same order **[call]**.

## Navigation

One form holds all selected questions, and answers are submitted together at the end **[docs: ADR-0035]**. JavaScript shows them one at a time **[call]**. Without JavaScript the page is the all-at-once page, and answers show at the end when the moment is `after_each` **[user]**.

- `step_back`: Back and Next. `step_no_back`: Next only. The page enforces it; it is not a security boundary **[docs: ADR-0035]**.
- An empty answer may be passed over, as an unanswered question scores zero today **[call]**. The last question's button submits.
- **Progress** **[user]**: step modes show "Question 3 of 12" with a bar; all at once shows "Answered 3 of 12" with a bar, only with JavaScript. It is announced to screen readers, and keyboard focus moves to the new question **[call]**.

Implementation follows `QuizFlowPlugin` in `modules/contracts.md`, narrowed to what these modes need **[call]**.

## Reveal

**After each question** **[user]**. The sequence is Check the answer, then the reveal, then Next. The page locks the checked answer, including on going back **[user]**. The lock is a page rule only **[user, docs: ADR-0035]**: a new tab or an edited page gets around it, and the server scores what is submitted. That is accepted because this mode is for learning, and Stage C blocks it in competitions. Nothing is stored, and the checked answer still goes in with the final submission.

A new endpoint `POST /a/<attempt>/check` takes the attempt token, a question id and an answer, and returns the reveal fragment. It refuses unless the attempt is in progress, its frozen moment is `after_each`, and the question is in its selection **[call]**. It stores nothing.

**At the end.** The result page lists the selected questions under the score with what the level allows. It computes this from the submitted answers **[call]**. A repeated submission shows the stored score and computes the list from the answers it carries **[call]**. The list exists only in that response, as the result page does today: no redirect, no later visit, because nothing is stored **[call]**. The lasting result page comes with Stage C.

**What the participant sees** **[call, from the sketch]**:

| State | Condition |
|---|---|
| Answered correctly | earned equals the question's points |
| Partly correct, with points | earned between zero and full |
| Wrong | earned zero, answered |
| No answer | nothing answered |

At level `answers` and above, correct options are marked and the participant's wrong one is marked as theirs. A trick question shows "None of the answers" as correct. Matching shows the correct pairs or order.

Colour is never the only signal; each state has text **[call]**.

**Contract.** Question types gain a method returning the correct answer for display for one locale, with the participant's answer alongside. It is called only by the reveal path, and `public_payload()` is unchanged **[docs: invariant 1]**. A contract test covers it for every type **[call]**. Escaping is covered the same way as the prompt.

## Explanation

Optional text per language on the question, in the quiz editor and the bank editor **[user]**. Plain text with line breaks, like sources; an `https://` line is not linked **[call]**. If filled in one of the quiz's languages it must be filled in all of them to publish **[call]**. For a bank question, an incomplete explanation makes that language incomplete **[call]**. It is included in the change overview, and never in `public_payload()`.

## Documents to change

`FR-18`, `FR-23` (move "after close" to C), `modules/domain.md`, `data-model.md`, `plugins/quiz-flow.md`, `plugins/question-types.md`, `modules/api-ui.md` (the where-things-are-set table), `modules/contracts.md`, `plugin-api.md`, `roadmap.md`, `CLAUDE.md`, and the theme's note on the progress indicator. A new ADR records: draw rows set points, flow settings are immediate and frozen on the attempt, and "after close" is deferred. New AC rows, from AC-30.

## Acceptance

1. A row "3 from a bank, 2 points each" gives each attempt 3 distinct questions and the same maximum. Two rows overlapping in one bank never repeat a question.
2. A bank question missing a quiz language is never drawn. Publication is blocked only when the rows cannot be filled.
3. Editing a bank leaves a published revision and attempts in progress unchanged, and shows unpublished changes on quizzes using it.
4. An attempt is scored only on what it was given; an answer to another question changes nothing. A settings change does not affect an attempt in progress.
5. Each navigation mode works with mouse and keyboard; without JavaScript the quiz can be completed on one page.
6. Each moment and level shows exactly what it should. `/check` refuses in every other case, and no page contains a correct answer before it is allowed.
7. The conflicting combination is refused in the form; a conflict from a global change falls back to `at_end` with a warning.
8. With all settings at their defaults an existing quiz behaves as before.

## Left to the builder

Order of tasks, except that navigation, reveal and explanation come before banks **[call]**. Migrations. Exact URL names. How the draw row is edited on the page. Wording of messages, in all three languages.
