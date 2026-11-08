# Plugin: participants (browser-anonymous)

| | |
|---|---|
| Contract | `ParticipantPolicyPlugin` |
| Package | `app/plugins/participants/` |
| Stage | C |
| Decision | [ADR-0011](../adr/0011-anonymous-cookie-participant-identity.md), [ADR-0049](../adr/0049-participants-and-access-code.md) |

## Requirements

- `FR-27` Admin configures repetition: forbid / allow; for the official ranking: first valid, best
  valid, or a chosen policy. Recalculation must be deterministic; on an equal best score an explicit
  rule applies: the earlier attempt counts ([ADR-0026](../adr/0026-scoreboard-tie-break-rule.md)).
- `FR-28` Repeat participants are distinguished by an anonymous cookie identifier; admin allows or
  forbids duplicate nicknames in a given run. The cookie does not guarantee a unique person.

## Behaviour

- The plugin `participants.basic` declares six settings, inherited global → quiz and copied onto the
  run: `repeat_attempts` (allow, forbid), `unfinished_attempt` (continue, used, submitted), `ask_name`
  and `ask_email` (off, optional, required), `ask_when` (end, start), `duplicate_names` (allow, forbid).
- The contract holds pure decisions: `clean_name`, `name_key`, `valid_email` and `on_start`, which tells
  the domain whether a returning participant starts anew, resumes, replaces an open attempt, or is
  refused. The domain keeps the rows and the transactions.
- A participant exists only when the run forbids repeating or asks for a name or e-mail. Only an HMAC of
  the anonymous key with the run id is stored (`participant.anonymous_key_hash`).
- A nickname is shown with inner spaces collapsed and compared case-insensitively, at most 40
  characters. If duplicates are forbidden it is checked within the run in the submission's atomic
  transaction (not only in UI). Only submitted attempts hold a name.
- Name/e-mail collection and presentation: [../../privacy.md](../../privacy.md) (FR-32).
- Access code per run (FR-06) is verified at attempt start: [../security.md](../security.md).
