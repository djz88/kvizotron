---
status: accepted
date: 2026-11-07
---

# ADR-0048: Run schedule without a background process, a limit fixed on the run, one time zone

## Context and Problem Statement

`FR-10` and `FR-11` ask for a run with an optional start and deadline, and an attempt time limit. A run must open and close on time, also when nobody is watching. Participants in one run must get the same time. All times are entered and shown in a configured zone, and last-moment submissions arrive together on one SQLite writer.

## Decision Drivers

* The simplest mechanism that gives a correct result, in line with a single-process deployment
* No status read anywhere may be out of date
* Fair and verifiable time for participants
* No lost attempt when time runs out with half-filled answers

## Considered Options

* Status changes applied on the first request after they are due
* A scheduled job (systemd timer or cron) changing the status
* Status computed from the times on every read

## Decision Outcome

Chosen option: "Status changes applied on the first request after they are due", because it needs no extra process and keeps one stored status for existing readers.

Rules:

* `run_schedule.settle` is idempotent and runs in a middleware before anything reads a status. `/healthz` and assets skip it, as a health check must not touch the database. Reaching the deadline stores `closed_at` equal to the deadline; opening stores `opened_at` equal to the planned start.
* A submission's timing never depends on `settle`. `attempts` compares the receipt time with `min(deadline_at, started_at + limit)` under [ADR-0025](0025-deadline-boundary-second-semantics.md). A run closed by its deadline does not refuse what arrived within it. A manual close refuses what arrived after it.
* The receipt time is read after the whole body has arrived, so a slow upload or a trickling client gains nothing. A photo sent as a run ends has its body read for 10 minutes after the close, stores nothing and hears why it is late; later it gets 415 unread.
* The limit is inherited global → quiz, copied onto the run when it is planned or opened, fixed once it opens, and copied onto each attempt. It has no question level, because it counts from the start of an attempt ([ADR-0042](0042-settings-inherited-and-declared.md)).
* A deadline can move on a running run, at least 60 s ahead, and applies to attempts in progress. Open pages ask for the seconds left every 30 s and when the tab is seen again.
* The automatic submission is lenient: an answer or photo that cannot be read counts as unanswered instead of refusing the attempt. This gains no points, so the client's flag needs no trust.
* The time zone is one global setting, with no quiz override, as one installation serves one place. Stored times stay UTC.
* A planned run takes the newest published revision until it opens.

### Consequences

* Good, because there is no extra process to deploy or monitor
* Good, because a wrong browser clock changes nothing, and the admin sees it in a clock panel
* Bad, because `run.closed` fires on the first request after the deadline, not at the deadline itself
* Bad, because every request pays two indexed queries
* Bad, because an attempt that never arrives is lost; local resume comes in C3

### Confirmation

[AC-07](../acceptance-criteria.md), AC-62 to AC-69, and a load test of 50 simultaneous submissions at a deadline (`tools/load_deadline.py`).

## More Information

Refines [ADR-0010](0010-strict-server-side-deadline.md) and [ADR-0025](0025-deadline-boundary-second-semantics.md).
