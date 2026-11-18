# Module: app/plugins/participants

Plugin `participants.basic`, port `participant_policy`: pure rules for a participant. It reads the nickname and e-mail and decides what happens when an attempt starts (`on_start`, the table is in `docs/plugin-api.md`).

## What the module contains

`policy.py` (`BasicParticipantPolicy`), `manifest.py` with eight settings (`repeat_attempts`, `unfinished_attempt`, `max_attempts`, `after_pass`, `ask_name`, `ask_email`, `ask_when`, `duplicate_names`), `apps.py`. The settings scope is global and quiz, because they apply to the whole attempt.

## What the module is not

It touches neither the database nor the request. It does not know attempts, runs or cookies: the API hands it the state (`finished`, `used`, `passed`, `open_attempt`; contract 1.1, AC-173) and it returns a decision. It does not read settings, it receives `rules`.

## Forbidden

Importing from `app/domain`, `app/api` or from another plugin: only `app.contracts` is allowed. Writing a nickname or e-mail to the log.
