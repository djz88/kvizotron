# Plugin family: question types

| | |
|---|---|
| Contract | `QuestionTypePlugin` (one module/adapter per type) |
| Package | `app/plugins/questions/` |
| Stage | A (single choice), B (remaining seven) |

## Requirements

- `FR-15` Base question types for v1.0, each as its own module/adapter: single correct answer;
  multiple correct answers; yes/no; image choice; ordering; matching; text fill-in; numeric answer.
  Video question is an extension after v1.0.
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
  ([ADR-0035](../adr/0035-immediate-solutions-only-without-competition.md)).

- `FR-45` Image answer type: the participant uploads one image as the answer. The question combines
  automatic points for submitting with manual points from an admin; the admin sets the split when
  authoring. Until grading finishes the score is provisional and the public scoreboard stays hidden.
  Images are visible only to admins. See [ADR-0033](../adr/0033-image-answer-question-type.md).

## Type catalogue (proposed ids)

| Type | Proposed id | Notes |
|---|---|---|
| Single correct answer | `choice.single` | id used as example in spec |
| Multiple correct answers | `choice.multiple` | partial scoring candidate |
| Yes / No | `choice.boolean` | |
| Image choice | `choice.image` | requires `media_storage` |
| Ordering | `ordering` | |
| Matching | `matching` | |
| Text fill-in | `text.fill` | locale-aware normalisation (FR-20) |
| Numeric answer | `number` | see [Numeric answers](#numeric-answers) |
| Image answer | `upload.image` | FR-45; requires `media_storage`, stored answers |
| Video (LATER) | `question.video` | manifest example in [../../plugin-api.md](../../plugin-api.md) |

Ids other than `choice.single` and `question.video` are proposals.

## Single correct answer

Definition: `{"prompt": {locale: text}, "options": [{"id", "text": {locale: text}}], "correct": option id}`.
Option ids are random (`secrets.token_hex(4)`), so an id says nothing about the correct option. The
editor has 6 rows, a row empty in all languages is dropped, and at least 2 options are required. The
answer is `{"option": option id}`.

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

## Invariants

- `public_payload()` never includes the answer key ([contracts](../modules/contracts.md) invariant 1).
- Revisions store type id + type version and all data needed for re-evaluation/audit
  ([ADR-0021](../adr/0021-plugin-manifest-and-versioning.md)).
- Question bank: `question_bank`, `bank_question` ([../data-model.md](../data-model.md)).
- Images and alt texts: [media-local.md](../providers/media-local.md).
