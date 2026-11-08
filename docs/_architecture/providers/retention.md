# Provider: retention (local-retention)

| | |
|---|---|
| Contract | `RetentionProvider` |
| Package | `app/providers/retention/` |
| Stage | D |
| Decision | [ADR-0012](../adr/0012-configurable-retention-profiles-and-stateless-mode.md) |

Policy requirements (FR-33, FR-34) are defined in [../../privacy.md](../../privacy.md); this plugin
implements them.

## Behaviour

- Scheduled job run by the management CLI (systemd timer/cron or separate job process).
- Per run: compute `cutoff_at` from `quiz_run.retention_json`, then delete or anonymise personal
  records (`participant`, `attempt_answer`, entitlement PII, draw entries) according to policy.
- Images uploaded by participants are deleted together with their answers; files no answer refers to
  are removed too.
- Keep permissible non-personal metadata (draw execution, aggregate counts).
- Record each execution in `retention_job` (`counts_json`) and emit `retention.executed`.
- Verified by [AC-14](../acceptance-criteria.md).
- Targeted admin deletion uses the same code path and is audited.
- Default retention period: 90 days after close ([ADR-0029](../adr/0029-default-retention.md)).

## Status

The C3 part is done: the run holds its period and data profile in `quiz_run.retention_json` ([ADR-0050](../adr/0050-data-profile-and-local-resume.md)), and under profile `none` nothing per attempt is kept. This provider, its job and `retention_job` come in D3; until then nothing is deleted when a period ends.
