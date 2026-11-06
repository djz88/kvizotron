# Plugin: drawing (manual-draw)

| | |
|---|---|
| Contract | `DrawingPlugin` |
| Package | `app/plugins/drawings/` |
| Stage | C |
| Decision | [ADR-0013](../adr/0013-manual-draw-csprng-append-only-audit.md) |

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

- `preview_eligible()` shows the eligible snapshot before drawing.
- Test attempts are excluded ([AC-12](../acceptance-criteria.md)).
- A draw is refused while manual grading is pending ([AC-16](../acceptance-criteria.md)).
- Draw is auditable at application level, not cryptographically indisputable towards the DB admin.

## Data owned

`draw`, `draw_entry` / `draw_winner` ([../data-model.md](../data-model.md)).
