# Plugin family: question types

| | |
|---|---|
| Contract | `QuestionTypePlugin` (one module/adapter per type) |
| Package | `app/plugins/questions/` |
| Stage | A (single choice), B2 (`choice`, `matching`), B3 (banks, explanation, reveal), B6 (numeric, text fill-in, image answer) |

## Requirements

- `FR-15` Base question types for v1.0, each as its own module/adapter: single correct answer;
  multiple correct answers; yes/no; image choice; ordering; matching; text fill-in; numeric answer.
  Video question is an extension after v1.0.
  One module can provide several kinds through settings ([ADR-0040](../adr/0040-question-types-grade-and-strategies-weigh.md)).
- `FR-16` Each type defines its editor, client rendering, configuration and answer schema, safe
  server-side validation and available scoring strategies.
- `FR-18` Static or random order of questions and options. Selection from a shared question bank
  with number of picks and filters/categories according to configuration, without repeating a
  question within one attempt.
- `FR-19` Bank configuration and question selection are frozen when the attempt starts; evaluation
  is performed against what the participant was actually given.
- `FR-20` Text answers: configurable normalisation of letter case, whitespace and possibly
  diacritics, plus multiple accepted alternatives. Rules are stored in the revision. Mind the meaning
  of characters in a specific language (especially Ukrainian) — diacritics stripping must not be
  applied blindly to all languages.
- `FR-23` Admin chooses whether/after which phase to reveal correct answers: after each question, at
  the end, after the run closes, or never — including the scope of revealed information. Reveal after
  each question is available only in runs with a hidden scoreboard and no rewards
  ([ADR-0035](../adr/0035-immediate-solutions-only-without-competition.md)). "After the run closes" arrives
  in Stage C ([ADR-0041](../adr/0041-draw-rows-and-flow-settings.md)).

- `FR-45` Image answer type: the participant uploads one image as the answer. The question combines
  automatic points for submitting with manual points from an admin; the admin sets the split when
  authoring. Until grading finishes the score is provisional and the public scoreboard stays hidden.
  Who sees an image is the admin's choice. See [ADR-0033](../adr/0033-image-answer-question-type.md) and [ADR-0047](../adr/0047-image-answer-photo-visibility.md).

- `FR-54` A question may have sources for its correct answers: one per line, up to 10 lines of 300 characters, not translated, frozen in the revision. A line that is a whole `https://` address becomes a link with `rel="noopener noreferrer"`, anything else stays text. The result lists them under the question's text unless `show_sources` is off ([settings](../modules/api-ui.md#where-things-are-set)). A change of sources alone does not count as a changed question when moving answers (FR-47).

## Type catalogue

| Kind | Id | Status |
|---|---|---|
| Single and multiple correct answers, trick question, image choice | `choice` | B2 |
| Yes / No | `choice` with `kind: yes_no` | B2 |
| Matching, ordering | `matching` | B2 |
| Text fill-in | `text` | B6; see [Text](#text-text) (FR-20) |
| Numeric answer | `number` | B6; see [Numeric answers](#numeric-answers) |
| Image answer | `image_answer` | B6; see [Photo](#photo-image_answer), FR-45 |
| Video (LATER) | `question.video` | manifest example in [../../plugin-api.md](../../plugin-api.md) |

## Výběr: `choice`

Definition: `prompt` per locale, optional `image`, `options` each with an id, text per locale and optional `image`, `correct` as a list of option ids, `allow_multiple`, `reveal_count`, `kind` of `standard` or `yes_no`. An image is `{"asset": id, "alt": {locale: text}}`.

- One answer at most is the default, with radio buttons. The admin may allow several, with checkboxes that say nothing about the number of correct answers; several correct options require that. Yes/no is always one answer. Up to 6 rows; at least 2 options.
- An option needs text or an image. Text started in one language must exist in all of them. Two options in one language cannot have the same text, ignoring case and extra spaces.
- No correct option marked means a trick question. A correct mark on an empty row is refused.
- With several answers allowed, `reveal_count` shows "(choose 3)". A trick question shows nothing, because "choose 0" would give it away, so in a quiz mixing them a missing hint is a clue.
- "None of the answers" is a translated answer the admin does not write. `none_option` says where it appears: `all_questions` (default, hides trick questions) or `trick_questions`. Yes/no never has it.
- Yes/no is an item in the add menu, creating two translated options with exactly one correct.

Answer: `{"options": [ids], "none": "1"}`, both optional; among radio buttons "None of the answers" is `{"options": ["none"]}`. More than one answer where one is allowed is refused. Nothing ticked is valid and scores zero, also on a trick question.

Grade: `right` correct ticks, `wrong` other ticks, `total` correct options. On a trick question "none" alone is `right = total = 1`. On any other question "none" gives `right = 0`.

## Přiřazení: `matching`

Definition: `prompt` per locale, `mode` of `pairs` or `order`, `items` each with an id and text per locale, 2 to 8 rows. In `pairs` an item also has `match_id` and `match` per locale, and in `order` the question has `direction` of `top_down` or `bottom_up`. Texts on one side cannot repeat in a language.

- `items` are written in the correct order. Items are shown sorted by their random ids, and right-hand texts by their own random ids, so neither the order nor the markup shows a pair.
- Pairs: a dropdown per row. Answer `{"pair_<item id>": "<match id>"}`. Each text can be used once: the server refuses a repeated one and the form comes back with the answers, and with JavaScript a used text is greyed out in the other rows.
- Order: drag and drop by mouse or touch, up and down buttons for the keyboard. Answer `{"order": [ids]}`. Without JavaScript a position dropdown per item: `{"pos_<item id>": "<number>"}`. A repeated position is refused and the form comes back with the answers.
- The participant sees the direction. Bottom-up means the first item belongs at the bottom, so the expected list is reversed.

Grade: `right` rows in the right place, `wrong = 0`, `total` rows.

## Numeric answers

- The page uses a numeric input field that allows only digits, a minus sign and one decimal separator.
- A browser or phone keyboard may still offer either `,` or `.`, and the server does not trust the page.
  The server therefore accepts both as the decimal separator: `3,14` equals `3.14`.
- Thousands separators are not supported; a value with more than one separator is invalid.
- The admin sets the correct value and an optional tolerance, either absolute (±) or as a percentage of
  the correct value. Example: 1 000 with ±5 % accepts 950 to 1 050. Both limits are inclusive.
- A percentage tolerance is computed from the absolute correct value, and the editor refuses it when the
  correct value is 0.
- Values are compared as exact decimals (`Decimal`), not floats.

Definition: `prompt` per locale, optional `image`, `value` as a decimal string, `tolerance`, `tolerance_kind` of `none`, `absolute` or `percent`. Answer: `{"value": text}`. Exponents, `NaN` and infinity are refused; an empty field is no answer. Only `all_or_nothing`. The solution shows the value and its tolerance. A unit belongs in the question's text.

## Text: `text`

Definition: `prompt` per locale, optional `image`, `blanks` with an id and accepted answers per locale, and three switches stored in the revision as question content: `ignore_case` (on), `ignore_spaces` (on), `ignore_diacritics` (off).

- A prompt may hold numbered markers `{1}`, `{2}`, up to 10, in any order per language, as word order differs. With markers each becomes an input, and with none there is one field under the question. Every language must use the same set, which publication checks. A literal brace is written `{{`.
- An answer is right if it matches any accepted answer of its blank, in any of the question's languages. Comparison normalises to NFC and folds with `casefold`.
- Ignoring diacritics removes marks only from Latin letters, decided by the character, so `й` and `ї` stay.
- `all_or_nothing` or `partial`, with each blank one part. A wrong blank is not a wrong tick, so `wrong` stays 0.

## Photo: `image_answer`

Definition: `prompt` per locale, optional `image`, `auto` as `{"right", "total"}`, the automatic share as a whole-number fraction. Answer: `{"image": asset id}`, set only by the API from a file received.

- `grade` returns the share for a submitted image, and `partial`, the only strategy offered, pays it. 10 points with 2 automatic is `2/10`; a bank asks for whole percent, so a row of 5 points at 20 % gives 1 automatic and up to 4 manual.
- One image per question, optional. No image gives 0 and nothing to grade.
- `photo_visibility` and the requirement on `reveal_moment`: [ADR-0047](../adr/0047-image-answer-photo-visibility.md).

## Invariants

- `public_payload()` never includes the answer key ([contracts](../modules/contracts.md) invariant 1).
- Revisions store type id + type version and all data needed for re-evaluation/audit
  ([ADR-0021](../adr/0021-plugin-manifest-and-versioning.md)).
- Question bank: `question_bank`, `bank_question` ([../data-model.md](../data-model.md)).
- `render_solution()` is called only when the attempt's frozen settings allow a reveal, or on a public walkthrough with public answers ([ADR-0046](../adr/0046-stored-answers-and-who-sees-them.md)).
- `file_fields()` names answer fields a page uploads, `needs_grading()` says a person finishes this answer, `summarize()` counts answers for a walkthrough, in plain text.

## Banks and draw rows

A quiz holds own questions and draw rows in one order. A row names a bank, optionally one tag, a count and the points per question ([ADR-0041](../adr/0041-draw-rows-and-flow-settings.md)). A bank question is usable when it matches the tag and is complete in all the quiz's languages, including its explanation if it has one. Publication is blocked only when the rows cannot all be filled without repeating a question; rows can overlap, so this is an assignment check, not a count per row.

## Explanation and reveal

A question may have a translated explanation in plain text. If it is filled in one of a quiz's languages it must be filled in all of them.

Levels are cumulative: `verdict` tells whether each answer is right; `answers` adds the correct answers; `explanations` adds the explanation. Moments are `never`, `at_end`, `after_each` and `after_close`; `after_each` needs a one-by-one mode. With `after_close` the result page lists nothing and says where and from when the answers can be seen; the private result link shows them from `closed_at` plus `attempts.LATE_UPLOAD_WINDOW` (10 minutes), decided by `reveal.is_shown` with an allowlist of moments ([AC-175](../acceptance-criteria.md)). It needs stored answers and visibility `participant` or `public` (clashes in `app/domain/setting_rules.py`: `AFTER_CLOSE_PROFILE`, `AFTER_CLOSE_VISIBILITY`, `RUN_PROFILE`); test runs and the preview act as `at_end` with a note. States shown: right, partly right with points, waiting for grading, wrong, no answer. With `at_end` and `after_each` the result lists the attempt's questions, computed from the submitted answers; nothing is stored.
- Images and alt texts: [media-local.md](../providers/media-local.md). An image is `{"asset", "source" (optional), "alt"}`; the API decides which one a page shows, and a plugin receives `url`.
- `question_settings()` lists the settings an admin can set on a question of this type ([ADR-0042](../adr/0042-settings-inherited-and-declared.md)).
