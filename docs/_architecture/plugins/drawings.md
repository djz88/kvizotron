# Plugin: drawings (drawings.manual)

| | |
|---|---|
| Contract | `DrawingPlugin` |
| Package | `app/plugins/drawings/` |
| Stage | C |
| Decision | [ADR-0013](../adr/0013-manual-draw-csprng-append-only-audit.md), [ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md) |

## Requirements

- `FR-37` A draw happens **only on explicit admin command** after the run is closed; for runs without
  deadline after manual close. The server builds a deterministic snapshot of eligible participants and
  selects using a cryptographically secure random generator.
- `FR-38` Draw audit includes time, admin ID, run ID, rules version, count and fingerprint of the
  candidate list, selected identifiers, algorithm used, and the reason for any repeated draw. The
  original record is never overwritten. Admin chooses whether to publish the winner and contacts
  winners manually; the system sends no e-mails automatically.
- `FR-39` Minimise PII in the draw log and audit records. When retention or an erasure request
  applies, related personal data are deleted or pseudonymised without needing to delete non-personal
  metadata about the draw execution.

## Behaviour

- A draw belongs to one `draw` reward rule of a run and runs on the page `/admin/runs/{id}/draw`.
- Refused while the run is not closed or archived, under the data profile `none`, while manual grading
  is pending ([AC-16](../acceptance-criteria.md)), on a test run, and with nobody eligible; a refusal
  stores nothing.
- `preview` shows the eligible snapshot (count and fingerprint) before drawing; the action rebuilds it.
  Eligible: participants with an official attempt that meets the rule's minimum (percent or points,
  or none). Test attempts are excluded ([AC-12](../acceptance-criteria.md)).
- One CSPRNG draw picks the winners and the alternates ranked 1..M; fewer eligible than requested draws
  everyone. Move up, substitute and redraw each need a reason and append a record
  ([ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md)).
- Publishing the winners is a per-rule switch, off by default; the public scoreboard page then lists
  them by nickname or anonymous label, never by e-mail. A published winner whose participant link was
  removed (D3) is left out of that list.
- Draw is auditable at application level, not cryptographically indisputable towards the DB admin.

## Contract

`DrawingPlugin` (port `drawing`, implementation `drawings.manual`) is pure: `order(ids)` sorts and
de-duplicates, `fingerprint(ids)` is the SHA-256 of the ordered ids joined by newlines, and
`select(ids, count)` uses `secrets.SystemRandom().sample`. Its `algorithm` is
`"secrets.SystemRandom.sample+sha256"`, stored with each record. Eligibility, records, alternates and
audit live in `app/domain/draws.py`.

## Data owned

`draw` (one row per action, never updated) and `draw_entry` (participant link, pseudonym, position,
role) ([../data-model.md](../data-model.md)). The pseudonym is a salted HMAC-SHA256 of the participant
id, so D3 can drop the participant link and keep the draw metadata (FR-39).

The module cannot be disabled while a planned, open or closed run has a draw rule
([ADR-0053](../adr/0053-rewards-tiers-alternates-and-draw-history.md)); the draw page and every action call it.
