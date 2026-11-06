# Plugin: participants (browser-anonymous)

| | |
|---|---|
| Contract | `ParticipantPolicyPlugin` |
| Package | `app/plugins/participants/` |
| Stage | C |
| Decision | [ADR-0011](../adr/0011-anonymous-cookie-participant-identity.md) |

## Requirements

- `FR-27` Admin configures repetition: forbid / allow; for the official ranking: first valid, best
  valid, or a chosen policy. Recalculation must be deterministic; on an equal best score an explicit
  rule applies: the earlier attempt counts ([ADR-0026](../adr/0026-scoreboard-tie-break-rule.md)).
- `FR-28` Repeat participants are distinguished by an anonymous cookie identifier; admin allows or
  forbids duplicate nicknames in a given run. The cookie does not guarantee a unique person.

## Behaviour

- Only a hash of the anonymous key is stored (`participant.anonymous_key_hash`).
- If duplicate nicknames are forbidden, the normalised `display_name` is checked within the run in an
  atomic transaction (not only in UI).
- Name/e-mail collection and presentation: [../../privacy.md](../../privacy.md) (FR-32).
- Access code per run (FR-06) is verified at attempt start: [../security.md](../security.md).
