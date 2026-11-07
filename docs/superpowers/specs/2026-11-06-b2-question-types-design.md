# B2 Question types: design

Status: approved 2026-11-06. Marks: **[user]** decided by the user, **[call]** the author's call, open to correction.

## Why

Organisers need more than one correct answer: several correct answers, trick questions with none, yes/no, matching,
ordering and pictures. The user's own quiz (several correct answers in three languages) cannot be entered today. Most of
these are the same question with different settings, so they become few types, and the rest is configuration **[user]**.

The application runs nowhere yet, so this is a green field: no compatibility with existing data is needed **[user]**.

## Scope changes

| Change | Decision |
|---|---|
| Numeric answer, text fill-in, image upload by a participant (`FR-45`), `FR-46` module requirements with AC-16, AC-17 | Stay required for v1.0, moved from B2 to a new milestone **B6 Remaining question types** **[user: later; call: the milestone]** |
| Uploading images (`FR-21` admin part) | Moved from B4 to B2, because images need it. External HTTPS image addresses stay in B4 **[call]** |
| Sources for correct answers | New, optional per question **[user]**. Next free `FR-xx` |

`FR-46` is not the admin's settings: it is a module refusing publication when a setting it needs is off. No type in this
milestone needs it. All settings below are in scope.

## Goals

1. Question type **Výběr**: one, several or no correct answers; yes/no; pictures in the question or the answers.
2. Question type **Přiřazení**: matching pairs, and ordering with drag and drop.
3. Settings per question, per quiz and globally.
4. Admin image upload.
5. Optional sources, shown with the result if the admin allows it.
6. Warning about unsaved editor changes, and TD-010.

## Non-goals

- Showing correct answers, explanations, random question selection, one question at a time: B3.
- External image addresses: B4.
- Disabling sources automatically in competitions: Stage C, noted in `roadmap.md` under C with [ADR-0035](../../_architecture/adr/0035-immediate-solutions-only-without-competition.md) **[call]**.

## Anti-goals

- The controls reveal a trick question or how many answers are correct, unless the admin chose to show it.
- The order of items shown to a participant depends on the correct order.
- A type that works only with a mouse or only with JavaScript.

## Types

### Výběr `choice` **[user: one type]**

Replaces `choice.single` everywhere **[user: green field]**.

Definition: `prompt` per locale, optional `image`, `options` each with an id, text per locale and optional `image`, `correct` as a
list of option ids (possibly empty), `reveal_count`, `kind` of `standard` or `yes_no`.

- One answer at most is the default, with radio buttons, and the admin may allow several, with checkboxes **[user, replacing the earlier "always checkboxes"]**. Several correct options need that allowed, and the form refuses them otherwise **[call]**. Yes/no is always one answer **[user]**.
- An option needs text or an image, or both **[call]**. Up to 6 rows as today.
- Two options in one language cannot have the same text (already built): ignores case and extra spaces, and options without text.
- No correct option marked means a trick question **[user]**.

Answer: `{"options": [ids], "none": bool}`.

**Reveal count** **[user]**: a checkbox on the question. When on, the question shows "(vyberte 3)". A trick question shows no such hint even when
the box is on, because "vyberte 0" would give it away. The editor says so. Note that a quiz mixing hints with trick questions gives a clue by the hint's absence; the admin chooses **[call]**.

**"Žádná z odpovědí"** **[user]**: a translated answer the admin does not write. A quiz setting says where it appears:

- `all_questions`: on every `standard` question of the quiz (default **[call]**, since it hides trick questions).
- `trick_questions`: only on trick questions.

Nothing ticked means unanswered and scores zero, even on a trick question **[call]**: only ticking "Žádná" counts as answering "none". Ticking "Žádná"
with other options is treated as a wrong answer without an error **[call]**; a small script unticks the others.

**Yes/No** **[user: wanted now; call: how]**: an item in the add menu, creating a `choice` with `kind: yes_no` and two options translated
in every language of the quiz, so the admin only marks the correct one. Exactly one correct, and no "Žádná". The texts are editable.

### Přiřazení `matching` **[user: both behaviours; call: one type]**

Definition: `prompt` per locale, `mode` of `pairs` or `order`, `items` each with an id and text per locale, up to 8 rows **[call]**.
In `pairs` each item also has `match` text per locale, and in `order` a `direction`.

- At least 2 items **[call]**.
- **Pairs** **[user: A→1, B→4]**: each left item has a dropdown with the right-hand texts. Unanswered rows are wrong. Two right-hand texts in one language cannot be the same; each text can be used once, enforced by the server and greyed out with JavaScript **[user, replacing the earlier call]**. Answer: `{"pairs": {item id: item id}}`.
- **Order** **[user]**: the participant moves items by drag and drop, with up and down buttons for keyboard and accessibility **[call]**. Answer: `{"order": [ids]}`.
- **Correct order** **[call]**: the admin always writes the rows in the correct order, first to last. `items` keeps that order.
- **Direction** **[user]**: on the question the admin sets top-down or bottom-up. The question shows it to the participant, for example "Seřaďte shora dolů". Bottom-up means the first item belongs at the bottom, so the expected answer is the reversed list.
- Without JavaScript, order falls back to a position dropdown per item **[call]**, and repeated positions are refused with a message that keeps the answers.
- Items and right-hand texts are shown sorted by their random ids, so the order does not depend on the correct one and stays the same for a question **[call]**.
- Drag and drop is one small script without a library: pointer events, working on touch screens, and delegated events so it works after an HTMX swap **[call]**.

## Scoring **[user: both]**

The editor offers points and scoring on each question:

- **Points:** a whole number from 1 to 100, default 1 **[call]**, in `settings.points`.
- **All or nothing** (existing) and a new **partial** strategy, chosen per question.

Partial:

- `choice` **[call]**: a correct tick adds points divided by the number of correct options, a wrong tick subtracts the same, and the total stops at zero. Ticking everything does not pay. Trick and yes/no questions behave as all or nothing.
- `matching` **[call]**: each correct pair or position adds points divided by the number of items. No subtraction.

Grading and weighing are apart **[call]**: `QuestionTypePlugin` gains `grade(config, answer) -> ItemGrade` with `right`, `wrong` and `total`, because only a type knows its definition. Strategies only weigh the result, so a strategy needs no knowledge of a type. This is a contract change, in the contract suite, `plugin-api.md` and the new ADR.

- All or nothing pays when `right == total` and `wrong == 0`.
- Partial pays `points * max(0, right - wrong) / total`, computed once for the question with `Fraction` and rounded to 4 decimal places as `Decimal` at the end, so three of three correct ticks give exactly the points, not 0.9999. Contract score types change from `float` to `Decimal` **[call]**.
- **"Žádná" scoring** **[call]**: on a trick question, "Žádná" alone is `right = total = 1`, anything else `right = 0`. On a question with correct answers, "Žádná" alone, or with other ticks, scores zero for the whole question.

Percentages are rounded only for display (FR-25).

## Images **[user: in the question or in answers]**

Follows [ADR-0028](../../_architecture/adr/0028-upload-limits.md) and [media-local](../../_architecture/providers/media-local.md):

- Formats PNG, JPEG, WebP, GIF, SVG; 15 MB, SVG and GIF 5 MB. Raster images become WebP, longest side 1600 px, at most 700 KB. Pillow at a pinned version is the one new dependency **[ADR-0028]**.
- HEIC is refused with a message saying what to do, because it would need another library **[call]**. ADR-0028 asks to verify this behaviour in Stage B; the result goes there.
- The content is checked, not the file name. SVG gets the basic check and is shown through `<img>`, and is served with `Content-Security-Policy: sandbox` so opening it directly runs nothing **[call]**.
- Alternative text per language is required for every image: a missing one blocks publication (`FR-21`).
- `media_asset` row per file, kept on the media volume. Revisions refer to assets by id, so a published revision keeps its pictures. Nothing is deleted in this milestone; removing unused files belongs to D3 **[call]**.
- Files are served at a public address with safe headers, since participants see them.
- **Upload:** ordinary file inputs in the question form, saved with the form **[call]**. If validation fails, already stored images stay referenced in the form so they need not be chosen again. The API stores files through `MediaStorageProvider` and hands plugins only asset ids, so plugins stay free of file handling **[call]**.
- `RefuseMultipartMiddleware` (TD-009) allows multipart only on the admin question editor routes. Everything else keeps refusing it, and `tests/api/test_request_limits.py` pins that **[call]**. Caddy's 16 MB limit stays.

Public rendering uses the alternative text and `loading="lazy"`. CSP `img-src 'self'` already covers it.

`/privacy` stays true, because all images are served from this server.

## Sources **[user]**

- Optional field on each question for every type: one source per line, up to 10 lines of 300 characters **[call]**. Not translated **[call]**.
- Stored beside `settings` on the question, frozen in the snapshot, shown in the change overview. A change to sources alone does not count as a changed question when moving answers.
- A line starting with `https://` is rendered as a link with `rel="noopener noreferrer"`, anything else as text **[call]**.
- Shown on the result page under each question that has sources, with the question's text. New setting `show_sources`, global with a quiz override, on by default **[user: visible after submitting, configurable by the admin]**.

## Settings

| Setting | Where | Takes effect |
|---|---|---|
| Points, scoring, reveal count, direction, sources | On the question | After publication |
| `none_option`: `all_questions`, `trick_questions` | Global, quiz override | Immediately |
| `show_sources`: on, off | Global, quiz override | Immediately |

Rendering `none_option` needs the quiz's value: the API passes it to the plugin through the public payload, and a contract test pins that the plugin does not read settings itself **[call]**.

`none_option` is read when questions are drawn, so a change affects new page loads and does not invalidate running attempts. Scoring treats "none" the same under either value **[call]**.

## Editor

Layout as shown to the user: question text, image, answers with correct marks, question settings, sources, Save. The common fields (points, scoring, sources) are drawn by the API around the plugin's form **[call]**. The strategies come from `available_scoring_strategies`.

**Unsaved changes** (B2 scope from the earlier decision): leaving the question editor or the quiz settings tab with changed fields asks the browser's standard confirmation. Saving does not. Needs JavaScript; without it nothing is lost by the page itself **[call]**.

## TD-010

- A double click on Save adds one question, also when the script is off: a one-use form key checked on the server, and a disabled button **[call]**.
- A slug race or a double click on Create shows the form error, using the `IntegrityError` pattern from `admin_users.py`.
- Numbers follow the language: `50 %` and `12,5 %` in Czech, `12.5 %` in English; `50.0 %` is gone.
- Already done in B1.5: a change of "featured" alone creates no draft, and types have a `label`.

## Constraints

- Plugins import only `app.contracts`. `choice` and `matching` each pass `QuestionTypeContract`, including escaping and answer key checks. `describe_definition` covers every field, including images and direction.
- `render_public` shows a given answer for every mode, so "Switch" keeps answers.
- Moving answers: unchanged rule, same id, type and definition.
- New strings in cs and en for admin, plus uk for public ones.
- Docs in English, each fact in one place: `roadmap.md`, `plugins/question-types.md`, `plugins/scoring.md`, `providers/media-local.md`, `data-model.md`, `modules/api-ui.md` table of settings, `plugin-api.md`, `security.md`, `CLAUDE.md`, `TECH_DEBT` (TD-010 resolved). New ADR for the merged types, next free number. New ids take the next free numbers.
- Verified in Docker: `make quality`, `make smoke`, and a browser walkthrough: each type at phone and desktop width, drag and drop by touch and mouse, ordering by keyboard, all without JavaScript, images in both modes.

## Acceptance

- A question with 3 correct of 5 answers: partial scoring gives the right sum; ticking everything gives no more than the correct ticks minus the wrong ones.
- A trick question scores only with "Žádná" ticked; nothing ticked scores zero. With `trick_questions`, "Žádná" appears only there, with `all_questions` everywhere except yes/no.
- Pairs and order score as defined, with bottom-up reversing the order. The HTML does not depend on the correct order.
- The participant sees the direction, and drag and drop, keyboard and no-JS ordering all give the same result.
- A published revision still shows its images. An image without alternative text blocks publication. A file that is not an image, or above the limit, is refused with a message and keeps the rest of the form.
- Multipart is refused everywhere except the question editor.
- Sources show on the result when on, and not when off. A line with markup is escaped; only `https://` becomes a link.
- A double click on Save creates one question. Leaving a changed form warns.

## Left to the builder

Template structure, exact labels beyond those here, how the form key is stored, internal names, the media table's details beyond `data-model.md`, and how the partial strategy is named in code.
