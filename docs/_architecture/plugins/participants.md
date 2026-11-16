# Plugin: participants (browser-anonymous)

| | |
|---|---|
| Contract | `ParticipantPolicyPlugin` |
| Package | `app/plugins/participants/` |
| Stage | C |
| Decision | [ADR-0011](../adr/0011-anonymous-cookie-participant-identity.md), [ADR-0049](../adr/0049-participants-and-access-code.md) |

## Requirements

- `FR-27` Admin configures repetition: forbid / allow, with an optional number of attempts and a stop after passing; for the official ranking: first valid, best
  valid, last, average ([ADR-0063](../adr/0063-kept-score.md)), or a chosen policy. Recalculation must be deterministic; on an equal best score an explicit
  rule applies: the earlier attempt counts ([ADR-0026](../adr/0026-scoreboard-tie-break-rule.md)).
- `FR-28` Repeat participants are distinguished by an anonymous cookie identifier; admin allows or
  forbids duplicate nicknames in a given run. The cookie does not guarantee a unique person.

## Behaviour

- The plugin `participants.basic` declares eight settings, inherited global → quiz and copied onto the
  run (`participant_rules_json`): `repeat_attempts` (allow, forbid), `unfinished_attempt` (continue, used, submitted), `max_attempts` (0 to 20, 0 is no limit, only under `allow`), `after_pass` (more, stop), `ask_name`
  and `ask_email` (off, optional, required), `ask_when` (end, start), `duplicate_names` (allow, forbid).
- The contract holds pure decisions: `clean_name`, `name_key`, `valid_email` and `on_start`, which tells
  the domain whether a returning participant starts anew, resumes, replaces an open attempt, or is
  refused. Since contract 1.1 it is also given `used` (the started attempts) and `passed` (the kept score reached the pass mark); the table is in [plugin-api.md](../../plugin-api.md#participant-policy). The domain keeps the rows and the transactions.
- Attempt limit ([AC-173](../acceptance-criteria.md)): under `allow` every started attempt of the browser counts, abandoned and expired ones too, a switched chain once; `unfinished_attempt` decides what an open one does. `after_pass=stop` refuses another attempt once the kept score passed, with or without a limit; an attempt waiting for grading does not stop it. `forbid` is unchanged. Test runs ignore both. A limit under the data profile `none` is a clash, because a limit needs a participant. The quiz page shows "Attempts left: N" and, when none are left or the participant passed, a message with the kept result.
- A participant exists only when the run forbids repeating or asks for a name or e-mail. Only an HMAC of
  the anonymous key with the run id is stored (`participant.anonymous_key_hash`).
- A nickname is shown with inner spaces collapsed and compared case-insensitively, at most 40
  characters. If duplicates are forbidden it is checked within the run in the submission's atomic
  transaction (not only in UI). Only submitted attempts hold a name.
- Name/e-mail collection and presentation: [../../privacy.md](../../privacy.md) (FR-32).
- Access code per run (FR-06) is verified at attempt start: [../security.md](../security.md).
