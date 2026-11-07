# Technical Debt

Central list of known gaps and deviations from the architecture. This is for what is knowingly
postponed; resolved items are moved to TECH_DEBT_archive.md after some time.

## Format

- Open item: `### TD-NNN Title — OPEN`, followed by a description, a `file:line` reference and a proposed solution.
- Resolved item: `### TD-NNN Title — ✅ RESOLVED (YYYY-MM-DD)`, moved under `## RESOLVED`.
- `## OPEN` is the last section before `## RESOLVED`; new sections go above it.

## OPEN

### TD-008 CI has not run on GitHub — OPEN
- Where: `.github/workflows/quality.yml`; the repository has no remote yet
- Effect: the workflow passes actionlint and its commands pass in a clean Python 3.15 container, but it has never run on a GitHub runner.
- Solution: push to GitHub and confirm that both jobs pass.

### TD-013 Installation modes no network / normal that derive security settings — OPEN
- Where: `allow_internal_image_addresses` in `app/providers/media_local/manifest.py`, `external_image_mode`
- Effect: an installation in a closed network sets each related setting by hand, and its quizzes warn about addresses it can never reach
- Solution: a global mode "no network / normal" from which these settings and their defaults follow

### TD-014 Question categories — OPEN
- Where: `app/domain/question_import.py`, where a category column is reported as unused; `kv_z_17_listopad_st_tnost_a_evropa.md` has one per question
- Effect: categories in a file are lost on import, with a note in the report
- Solution:

### TD-015 Photo files left behind when storing fails midway — OPEN
- Where: `app/api/play.py:337` (`with_files`), `app/providers/media_local/provider.py:236` (`_saved`)
- Effect: if a later photo of one submission fails with anything but `ImageRefused`, such as a full disk or a locked database, the photos already written stay on the volume with no row pointing to them. `_saved` also writes the file before its row, so a failed save leaves one file. Nobody sees them, but they take space
- Solution: let `with_files` append to a list the caller owns and remove it on any exception; remove the file in `_saved` when the row cannot be saved

### TD-016 Walkthrough loads all answers on every request — OPEN
- Where: `app/domain/walkthrough.py:60` (`available`), `:113` (`photo_for_public`), `app/api/public.py` (`_walkthrough_url`)
- Effect: `available` loads every answer row of the run, on each page view of an ended quiz when answers are not public and once per image of the walkthrough, so a gallery of 30 photos loads them 30 times
- Solution: decide from question settings without loading answers where possible, and keep the result for the length of a request

### TD-017 Closed quiz page fails when a question type's module is uninstalled — OPEN
- Where: `app/domain/walkthrough.py:74` (`_plugin`), called from `available` and `of_run`
- Effect: after a question type's module is uninstalled, the public page of an ended quiz answers 500 when its answers are not public, and the walkthrough answers 500 in any case
- Solution: catch `UnknownPort` as `_own_answers` in `app/api/public.py` does, and leave such a question out

### TD-018 Number answer with a thousands separator is graded wrong without a message — OPEN
- Where: `app/plugins/questions/number/plugin.py:39` (`parse_number`)
- Effect: a comma is a decimal separator as the docs say, so `1,000` reads as 1 and is graded wrong, with only the hint under the field to warn about it
- Solution: ask to confirm or show a message for exactly three digits after a separator, in the page's script and without changing what the server accepts

### TD-019 Stale tab posting a photo form to a switched attempt gets a bare 415 — OPEN
- Where: `app/api/play.py:99` (`accepts_upload`), `:113`
- Effect: after an attempt was switched to a new revision, an old tab still holding its photo form posts to the switched attempt and gets a bare 415, instead of the notice that the attempt was replaced
- Solution: admit multipart for a switched attempt too, store nothing, and let `submit` answer `attempt_switched`

### TD-020 Gallery question chips are not in quiz order — OPEN
- Where: `app/api/admin_grading.py:112` (`_gallery`)
- Effect: the links to questions with photos are sorted by question id, so with several photo questions they do not follow the order of the quiz. Cosmetic
- Solution: sort by position in the run's last revision, as `_questions` already lists them

### TD-021 Hand-crafted result photo address logs its token — OPEN
- Where: `app/urls.py:24`, the `uuid` part of `result_photo`
- Effect: `/v/<token>/photo/<not a uuid>` answers 404, and Django logs that with the path, so a token can reach the log. Only a hand-crafted address does this; pages never link to one
- Solution: take the last part as a string, and answer 204 for anything that is not a known id

## RESOLVED

### TD-001 Project purpose missing in README — ✅ RESOLVED (2026-11-05)
### TD-002 Installation steps missing in README — ✅ RESOLVED (2026-11-05)
### TD-003 Commands and API missing in README — ✅ RESOLVED (2026-11-05)
### TD-004 Development commands missing in README — ✅ RESOLVED (2026-11-05)
### TD-005 Security contact missing — ✅ RESOLVED (2026-11-05)
### TD-006 Makefile targets are placeholders — ✅ RESOLVED (2026-11-05)
### TD-007 CI is missing — ✅ RESOLVED (2026-11-05)
