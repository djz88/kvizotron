# B6 Remaining question types, grading and answer visibility: design

Status: approved 2026-11-07. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

Organisers want to ask for a number or a word, and to run photo tasks that a person judges (`FR-15`, `FR-20`, `FR-45`). A person's judgement needs stored answers and a way to tell a participant the final score. Once answers are stored, organisers also want to settle unclear answers and to walk through the quiz publicly after a run. Modules that only work with certain settings need a way to say so (`FR-46`).

The user chose to build all of this in one milestone, including grading, which the roadmap had in C4 **[user]**.

## Goals

1. Type **number**: a numeric answer with a tolerance **[docs]**.
2. Type **text**: one field under the question, or several blanks inside the sentence **[user]**, with configurable comparison and several accepted answers per language **[user]**.
3. Type **image answer**: a participant uploads one image; part of the points are automatic and the rest come from an admin **[docs]**. Works in banks **[user]**.
4. A grading screen, by question or by attempt, as the admin chooses **[user]**. A photo can be deleted **[user]**.
5. A participant learns the final score through a private link and when returning on the same device **[user]**.
6. Admins choose whether all answers are stored or only images, and who sees them: admins, the participant, or everyone **[user]**.
7. A public walkthrough of a finished run, by question **[user]**.
8. Who can see a photo is the admin's choice among three levels **[user]**.
9. Module requirements on settings work, with the image answer as the first real user **[user]**.

## Non-goals

- Scoreboard, rewards and draws: Stage C. What ADR-0033 says about them is added there through the same requirements **[docs]**.
- Results, statistics and export of answers: C4 and D2 **[docs]**.
- Uploading a photo as soon as it is chosen: it goes with the submission **[user]**.
- A unit next to the number field: it belongs in the question's text **[user]**.
- Automatic cleanup and retention: D3 **[docs]**.
- Participant names: the walkthrough and grading stay anonymous until C2 **[call]**.
- Rate limits on uploads: D5, like the rest of the public pages. Not for public deployment until then **[docs]**.

## Anti-goals

- A participant's photo reachable through `/media/<id>` or any address without the right to see it.
- A file reaching storage before being rebuilt from pixels, or EXIF surviving.
- A photo public without the admin choosing that level and approving that photo, or without the participant having been told before uploading.
- A public walkthrough during an open run, or one containing test attempts.
- A correct answer or an accepted text reaching a page before settings allow it.
- A manual point value changing a published revision, or an attempt's score changed by anyone but a logged-in admin.
- An existing quiz behaving differently when settings are at their defaults.
- Ukrainian letters changed by ignoring diacritics.

## Type: number

As in [Numeric answers](../../_architecture/plugins/question-types.md#numeric-answers) **[docs]**: an input allowing digits, a minus sign and one decimal separator, comma or dot accepted by the server, no thousands separators, exact `Decimal` comparison, tolerance absolute or in percent of the absolute correct value, inclusive limits, percent refused when the correct value is 0.

Exponents, `NaN` and infinity are refused **[call]**. An empty field is no answer; what cannot be read is refused like any invalid answer, keeping the form **[call]**. The correct value is stored as a decimal string **[call]**. Only `all_or_nothing` scoring **[call]**. The solution shows the value and its tolerance **[call]**.

## Type: text

**Form [user]:** both forms are one type **[call]**. The prompt per language may contain numbered markers `{1}`, `{2}`, in any order, as word order differs between languages. With markers the page puts an input in each place. With none, there is one field under the question. Every language must use the same set of markers; publication checks this **[call]**. Up to 10 blanks **[call]**. A literal brace is written `{{` **[call]**.

**Accepted answers [user]:** per blank and language, one per line. An answer is right if it matches any accepted answer of that blank, in any of the question's languages, so the type needs no knowledge of the attempt's language **[call]**.

**Comparison [user]:** three switches on the question, stored in the revision, as question content and not settings (ADR-0042):

| Switch | Default |
|---|---|
| Ignore letter case | on |
| Ignore extra spaces | on |
| Ignore diacritics | off |

Ignoring diacritics removes marks only from Latin letters, decided by the character, so `й`, `ї` and any Cyrillic letter stay as they are **[user]**. Unicode is normalised to NFC before comparing, and case folding uses `casefold` **[call]**.

**Scoring:** `all_or_nothing` and `partial`, with each blank one part of the grade **[call]**. A wrong blank is not a wrong tick: `wrong` stays 0 **[call]**. The solution lists accepted answers in the attempt's language **[call]**.

## Type: image answer

### Authoring

The admin enters total points and automatic points, for example 10 and 2 **[docs]**. The application stores the automatic part as a share of the total, here 20 %, so a draw row's points also work: a row of 5 points gives 1 automatic and up to 4 manual **[user]**. In a quiz the editor always shows points, never percent **[user]**; in a bank, where points come from the row, it asks for the share **[call]**. Automatic points may be 0 **[call]**. A question's `points` stay whole, as everywhere. Only earned points can be non-whole, as `partial` already allows: 5 points at 33 % earn 1.65, leaving up to 3.35 manual, kept to 4 places **[call]**.

A `prompt` per language and an optional image, like `choice`. No new strategy and no contract change, so ADR-0040 stands: the share is stored as a whole-number fraction, and `grade` returns it as `right` of `total`, with `wrong` 0, for a submitted image and `right` 0 otherwise. The type offers only `partial`, which then pays exactly the automatic share **[call]**. A bank share is entered in whole percent, stored as n/100 **[call]**.

### Answering

One image per question, optional **[call]**: no image gives 0 and nothing to grade. Upload happens with the submission **[user]**, so the form is multipart when the attempt holds such a question, through HTMX and without it **[call]**.

Processing as [ADR-0028](../../_architecture/adr/0028-upload-limits.md) **[docs]**: PNG, JPEG, WebP, 15 MB, pixel limit, rebuilt from pixels, EXIF gone, stored as WebP at most 1600 px and 700 KB, written before the database transaction, 2 GB per run.

A refused file, or a run over its limit, returns the form with the other answers kept and a message **[docs]**. The file must be chosen again **[user]**. A repeated submission reuses what is stored **[docs]**. A file stored for a submission that then fails is removed at once **[call]**.

`RefuseMultipartMiddleware` admits multipart on a public address only for `/a/<id>/submit` of an attempt that exists, is in progress and holds this type, checked before the body is read. The 16 MB limit in Caddy stands **[call]**.

Preview reads and checks the file and stores nothing **[call]**. A test attempt works fully, and deleting a link also removes its photos **[call]**.

### Photos are private by default

`MediaStorageProvider` gains a method storing a participant image under the rules above, and `MediaAsset` a private flag, so the public `/media/<id>` answers 404 for them **[call]**. They are served only through routes that check the right below, with `Cache-Control: private, no-store`, so a withdrawn or deleted photo is not kept in a cache. The year-long cache of `/media/` stays for admin images **[call]**.

The setting `photo_visibility` decides **[user]**:

| Value | Who sees a photo |
|---|---|
| `admins` | Admins |
| `author` (default **[call]**) | Admins, and its author through the private link |
| `public` | As `author`, and everyone on the walkthrough after the run ends, once an admin approves that photo |

With `public`, the question says before upload that the photo may be shown publicly **[user]**. Approval is per photo, off by default **[user]**.

Owner: the image answer module. Scopes: global, quiz, question **[call]**.

## Attempts and grading

`Attempt.Status` gains `PENDING_GRADING` **[docs]**. On submit, automatic points give the score; `max_score` includes the manual part **[docs]**. An attempt with an image waits for grading; one without is simply submitted **[docs]**. The participant sees a provisional score, marked as such: 2 of 10 **[docs]**.

A new tab **Grading** in the quiz workspace **[call]**, showing the number waiting. Each attempt is shown as an anonymous number **[call]**. `grading_view` chooses the view **[user]**:

- `by_question` (default **[call]**): a gallery of one question's photos side by side, with a points field each.
- `by_attempt`: one attempt after another, with all its photos and all its stored answers **[user]**. Only photos can be graded **[user]**.

Saving a value stores it, recalculates the score, and moves the attempt out of pending once none of its photos waits **[docs]**. Works by HTMX, and without it by whole-page post **[docs]**. Points from 0 to the manual maximum, in any decimal the score accepts **[call]**. Grading again later is allowed, including after a run ended **[call]**. Every change goes to the audit log **[docs]**.

Runs are chosen on the page, the running one first. The tab's list and count hold no test attempt. Each link on the Test links tab has a Grade action leading to the same page for that test run, where its photos can be graded, so a test can go through the whole flow **[call]**.

**Deleting a photo [user]:** with confirmation and an audit entry. The file goes, manual points become 0, the score recalculates, and the answer says the photo was removed **[user]**. Automatic points stay, as the image was submitted **[call]**.

## Stored answers

`store_answers` **[user]**: `images` (default) or `all`, frozen on the attempt at start, like other flow settings **[call]**.

A table for stored answers, one row per question of a submitted attempt: the answer, automatic and manual points, who graded and when, the asset, approval, and hidden **[call]**. With `all`, every answered question gets a row **[user]**. A replaced attempt keeps nothing: only the one submitted counts **[call]**.

## Who sees answers

`answers_visibility` **[user]**: `admins` (default), `participant`, `public`. It covers stored answers other than photos, which have their own setting **[call]**.

| Value | Meaning |
|---|---|
| `admins` | The by-attempt view only |
| `participant` | Also the participant, on their private link |
| `public` | Also everyone on the walkthrough, after the run ends |

Anything other than `admins` needs `store_answers=all`. The quiz form refuses the combination, and a global change falling into it behaves as `admins`, with a warning, like a flow conflict in ADR-0041 **[call]**.

Scopes of `store_answers`, `answers_visibility` and `grading_view`: global and quiz **[user]**. Reason: each applies to an attempt or a quiz as a whole **[call]**.

## The private link and the same device

`/v/<token>`, a signed reference to the attempt, without an end date until retention arrives in D3. A deleted photo is gone from it at once, and deleting an attempt's test link ends it **[call]**. Shown on the result page when the attempt waits for grading, or when `answers_visibility` or `photo_visibility` lets the participant see more **[call]**, with a line asking to save it **[user]**.

It shows the score and whether it is final **[user]**; own answers when allowed; own photo when allowed; correct answers only as the attempt's reveal settings allow **[call]**. It carries `noindex` and `no-referrer`, and answers with status 200 and one message when invalid, so the token never reaches the log, as in ADR-0044 **[call]**.

**Same device [user]:** the page stores this link in `localStorage` per quiz. Returning to the quiz's public page shows a link to the result. Without JavaScript only the private link works **[call]**. The privacy page mentions it **[call]**.

## The public walkthrough

`/q/<slug>/r/<run>/answers`, only after the run has ended **[user]**, and when `answers_visibility=public` or any of its questions has `photo_visibility=public`. Otherwise one plain message **[call]**. Correct answers, explanations and counts appear only with `answers_visibility=public`; with public photos alone the page shows each such question's prompt and approved photos, so a photo contest needs no public answers **[call]**. A link appears on the quiz's public page for that run, and on the run's admin page **[call]**.

By question **[user]**: the prompt and image, the correct answer, the explanation, then what people answered with counts: `Praha 12×, Brno 3×` **[user]**. No link to a participant **[user]**. Approved photos, if `photo_visibility` is `public` **[user]**. Test attempts never **[user]**.

Each type summarises its answers through a new contract method, so a future type cannot skip it, covered by the shared contract tests **[call]**. Text answers are counted after the question's comparison **[call]**.

Free text can say anything. An admin viewing the same page gets a hide action on each value, recorded in the audit log **[user]**. Without an admin's hide a value is shown **[user]**. The settings page says so in one line **[call]**.

A run moved to a newer revision shows the questions of its last revision, and answers given to questions it no longer has are left out **[call]**.

## Module requirements

`settings_requirements` in a manifest, declarative values only **[docs]**: per setting key, the allowed or refused values and a reason in the module's catalogue. Requirements of settings a module does not own are allowed **[docs]**. An unknown key or value is a start-up error **[call]**. Requirements that contradict each other block the combination **[docs]**.

A module counts as selected for a quiz when its type is used in the draft or in a draw pool **[call]**.

- **Editor:** a question of such a type shows the requirement and a **Use** button setting the quiz's override **[docs]**.
- **Publication and opening a run** are blocked, with the reason **[docs]**. A test link's draft copy follows the publication check, so it is blocked too.

The image answer requires `reveal_moment` other than `after_each`, as an admin's points do not exist yet **[user]**. An attempt that started before a change keeps its frozen settings; a reveal at the end says the photo is waiting for grading **[call]**.

## Fitting into what exists

- **CSV:** all three types provide `csv_columns`, `from_csv`, `to_csv` **[docs]**. An image answer imports its question only, with `auto_points` or `auto_share` **[call]**. `csv-format.md` describes the columns, and its test covers them.
- **Settings rule:** `photo_visibility` is the module's; `store_answers`, `answers_visibility` and `grading_view` go to the domain catalogue **[call]**. Number and text state `settings: []`.
- **Add menu:** the three types appear where the existing ones do **[docs]**.
- **Accessibility:** inputs have labels with blanks named by number, the file input works by keyboard, and the gallery's points fields are in reading order **[call]**.

## Documents

- ADR-0046: stored answers, who sees them, the private link and the walkthrough.
- ADR-0033 updated by a new decision: photo visibility is chosen by the admin, the share of automatic points, and grading in Stage B. Its old statement that photos are never public is superseded **[user]**.
- ADR-0034: implemented as written, noting the first real requirement.
- `plugins/question-types.md`, `plugins/scoring.md`, `modules/kernel.md`, `modules/domain.md`, `modules/contracts.md`, `data-model.md`, `security.md`, `docs/privacy.md` and the privacy page, `docs/plugin-api.md`, `roadmap.md` (C4 narrows), `CLAUDE.md`s.

Acceptance criteria: AC-16 and AC-17 move in part. The grading, privacy and upload parts of AC-16 are B6, its scoreboard, draw and threshold parts stay in C. New, from AC-53:

- **AC-53 Number:** `3,14` equals `3.14`; 1000 with ±5 % accepts 950 and 1050 and refuses 949.99; two separators, `1e5` and `NaN` are refused; a percent tolerance on 0 is refused in the editor.
- **AC-54 Text:** with markers each blank scores separately and word order differs per language; with none there is one field. Default comparison ignores case and spaces and respects diacritics. With diacritics ignored, `Plzen` equals `Plzeň`, while `и` does not equal `й`.
- **AC-55 Split:** 10 points with 2 automatic shows 2 of 10 and pending. In a bank, a row of 5 points gives 1 automatic and at most 4 manual.
- **AC-56 Grading:** both views grade and recalculate; the attempt leaves pending when nothing waits; a non-admin cannot grade; each change is audited; a deleted photo is gone, with points at 0.
- **AC-57 Photo privacy:** with each level, exactly the right people get a photo. `/media/<id>` answers 404 for it. Public needs approval of that photo and a notice before upload. EXIF is gone.
- **AC-58 Result:** the private link shows the final score after grading, and own answers and photo only as settings allow, with no correct answer before reveal. An invalid token logs nothing. The same device shows the link on return.
- **AC-59 Answers:** with `images` only images are stored, and with `all` every answered question. With defaults nothing changes for an existing quiz. `public` without `all` is refused in the form.
- **AC-60 Walkthrough:** it is unavailable during an open run and when neither answers nor photos are public. With public answers it shows counts without any link to a participant, and no test attempt. A hidden value is gone from it. With public photos alone it shows approved photos and no correct answer.
- **AC-61 Requirements:** an image question with `after_each` shows the requirement, offers Use, and blocks publication and opening a run with an explanation; satisfying it allows both. Contradicting requirements block. (Refines AC-17.)

## Left to the builder

Names of fields, routes, tables and module ids not given above (`number`, `text.fill` and `upload.image` are proposals); how the strategy gets the share within ADR-0040; the layout of the gallery; automated tests use small generated images and no network. Verification in Docker, as usual, without touching `kvizotron-browser` data.
