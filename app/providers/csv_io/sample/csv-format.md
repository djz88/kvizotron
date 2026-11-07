# Kvízotron question file

Written for a person or an LLM preparing an import. Save the result as CSV in UTF-8, with commas or semicolons. A spreadsheet's "CSV UTF-8" is fine. A ZIP may hold this CSV at its top level, with image files next to it.

One row is one question. The first row of a file for a new quiz describes the quiz. Download the sample from the import page to see a whole file.

`<language>` is `cs`, `en` or `uk`. `<N>` is an option number, from 1 to 6.

## Rows

| Column | Meaning |
|---|---|
| `schema_version` | `1`, or blank |
| `row_type` | `quiz` on the quiz row, otherwise `question` or blank |

## The quiz row

Needed only for a new quiz. Ignored, with a warning, when adding to a draft or a bank.

| Column | Meaning |
|---|---|
| `slug` | Address of the quiz, like `my-quiz`. Taken from the title when blank. A taken address gets a number |
| `locales` | Languages, comma separated: `cs,en,uk`. Taken from the titles when blank |
| `default_locale` | One of them. The first when blank |
| `title_<language>` | Name of the quiz. At least one is required |
| `description_<language>` | Description. Publication needs it in every language |
| `setting_<key>` | A quiz setting, see below |

## Every question

| Column | Meaning |
|---|---|
| `type` | `choice`, `matching`, `number`, `text` or `image_answer` |
| `points` | A positive whole number. 1 when blank. Not used in a bank |
| `scoring` | A scoring strategy of the type. The type's first when blank |
| `explanation_<language>` | Shown when the quiz reveals explanations |
| `sources` | One source per line within the cell. An `https://` line becomes a link |
| `tags` | Comma separated. Used only in a bank |
| `setting_<key>` | A question setting, see below |

## Type `choice`

| Column | Meaning |
|---|---|
| `prompt_<language>` | The question |
| `option_<N>_<language>` | The text of an option |
| `correct` | Correct options by letter, where A is option 1: `A` or `A,C`. Numbers are refused |
| `kind` | `standard`, or `yes_no` for exactly two options and one correct |
| `allow_multiple` | `true` or `false`. When blank, true if more than one option is correct |
| `reveal_count` | `true` or `false`: tell the participant how many are correct |
| `image` | The question's image, see below |
| `image_alt_<language>` | Its description for those who cannot see it. Publication needs it |
| `option_<N>_image` | An option's image |
| `option_<N>_image_alt_<language>` | Its description |

## Type `matching`

| Column | Meaning |
|---|---|
| `prompt_<language>` | The question |
| `config_json` | JSON with the items, see below |

Pairs:

```json
{"mode": "pairs", "items": [{"text": {"cs": "Praha"}, "match": {"cs": "Česko"}}]}
```

Ordering, with `direction` `top_down` or `bottom_up`, items in the correct order:

```json
{"mode": "order", "direction": "top_down", "items": [{"text": {"cs": "První"}}]}
```

## Type `number`

| Column | Meaning |
|---|---|
| `prompt_<language>` | The question |
| `correct_value` | The correct number, with a comma or dot for decimals, such as `3,14` |
| `tolerance` | How far an answer may be, such as `5`. Blank means an exact value |
| `tolerance_kind` | `none`, `absolute` or `percent`. When blank, `absolute` if a tolerance is written. `percent` needs a correct value other than 0 |
| `image` | The question's image, see below |
| `image_alt_<language>` | Its description |

## Type `text`

| Column | Meaning |
|---|---|
| `prompt_<language>` | The question. `{1}`, `{2}` mark blanks inside the sentence, in any order per language, up to 10. Without them there is one field under the question. A literal brace is written `{{` |
| `answer_<N>_<language>` | Accepted answers of blank N, one per line within the cell |
| `ignore_case` | `true` or `false`. True when blank |
| `ignore_spaces` | `true` or `false`. True when blank |
| `ignore_diacritics` | `true` or `false`, for Latin letters only. False when blank |
| `image` | The question's image, see below |
| `image_alt_<language>` | Its description |

## Type `image_answer`

A participant uploads a photo. Part of the points are automatic and the rest come from an admin. Write one of the two below, or neither for no automatic points.

| Column | Meaning |
|---|---|
| `prompt_<language>` | The question |
| `auto_points` | Automatic points, a whole number. Needs `points` in the same row, and cannot be used in a bank |
| `auto_share` | Automatic share in whole percent, from 0 to 100 |
| `image` | The question's image, see below |
| `image_alt_<language>` | Its description |

## Images

A cell starting with `https://` is an address. Anything else is the name of a file in the ZIP, with its folder: `images/a.png`. An address is fetched when you confirm. If it fails, the question stays, with a warning, and publication in copy mode names it.

## Settings

`setting_<key>` holds one of the values the setting offers. The settings page shows them. A key that cannot be set at that level is an error on that row.

## Errors

A row with an error is skipped and listed with its number and column, where the header is row 1. The rest is imported. A missing translation or missing answer is only a warning: the draft may be incomplete, and publication checks it. Text in a language the target does not use is left out, with a warning. Nothing is published by an import.

## Example

```csv
schema_version,row_type,type,title_cs,locales,prompt_cs,option_1_cs,option_2_cs,correct,sources
1,quiz,,Můj kvíz,cs,,,,,
1,question,choice,,,Hlavní město Česka?,Praha,Brno,A,https://example.test/zdroj
```
