# Provider: retention (local-retention)

| | |
|---|---|
| Contract | `RetentionProvider` |
| Package | `app/providers/retention/` (module id `retention.local`) |
| Stage | D |
| Decision | [ADR-0056](../adr/0056-retention-job-summary-held-runs.md), [ADR-0012](../adr/0012-configurable-retention-profiles-and-stateless-mode.md) |

Policy requirements (FR-33, FR-34) are defined in [../../privacy.md](../../privacy.md).

## What the provider does

It keeps the trail of deletions, table `retention_job`, and nothing else. Providers may not import the domain, and the rows being deleted are the domain's.

- `record(run_id, trigger=, admin_id=, policy=, cutoff_at=, counts=, fingerprint=)`: one row per execution. `trigger` is `automatic`, `manual` or `erasure`.
- `history(limit, offset)`, `for_run(run_id)`, `erased(fingerprint)`: newest first, as `RetentionRecord`, which says whether a fingerprint exists but never carries it.
- No settings: the hourly interval, the batch size and the 14 days of warning are constants (`"settings": []`).

## What the domain does

`app/domain/retention.py` decides what is due and deletes it ([ADR-0056](../adr/0056-retention-job-summary-held-runs.md) has the rules).

- `run_pass`: settles runs past their deadline, deletes the data of every due run, finishes a purge that stopped halfway, then sweeps. One run failing is logged by id and does not stop the others.
- `purge_run`: one path for expiry and "Delete data now". In stages, resumable through the stored summary.
- `delete_now`, `erase`, `search_email`, `search_name`, `fingerprint`, `erased_records`, `held_runs`, `release_held`, `sweep`.
- `data_policy.deletion_at`, `is_due`, `days_left`, `deletion_soon`: when a run is due and what the run pages show.

The service `jobs` calls `run_pass` once per hour (`manage.py jobs`). `manage.py retention` makes one pass by hand or from a host's cron.

## Behaviour

- Deleted: attempts in any status, their answers, hidden answer values and assigned questions, participants, reward entitlements, participant photos, and export jobs and files naming the run or all runs of its quiz.
- Kept: the run, its revisions and reward rules, draws with the participant link cleared and the pseudonym left, audit events, and an anonymous summary on the run.
- A deleted run is rewritten to profile `none`, moved to `ARCHIVED` and keeps its summary, which statistics and the comparison of runs read.
- Held runs: marked by the D3 migration when already past their period, or past their deadline and unsettled, and released on the Deletion history page.
- Each execution writes one `retention_job` row and one `audit_event`, and emits `retention.executed`.
- Files are removed after the commit; a photo left behind is found by the sweep of a later pass.
- Default retention period: 90 days after close ([ADR-0029](../adr/0029-default-retention.md)).
- Verified by [AC-14](../acceptance-criteria.md) and AC-110 to AC-119.
