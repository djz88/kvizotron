---
status: accepted
date: 2026-11-05
---

# ADR-0033: Image answer question type with mixed scoring

Who sees a photo, how automatic points are stored and when grading arrives were changed by [ADR-0047](0047-image-answer-photo-visibility.md).

## Context and Problem Statement

The spec's eight question types are all scored automatically. Competitions also need answers where the
participant uploads a photo. A photo cannot be compared with an answer key, yet scoreboard, rewards
and draws depend on a final score.

## Decision Drivers

* Real photo competitions
* Fair rewards and draws
* Short submission transactions on SQLite ([ADR-0036](0036-django-web-framework-and-orm.md))

## Considered Options

* Automatic points for submitting plus manual points from an admin
* Manual points only
* Submission without points
* Automatic points for submitting only

## Decision Outcome

Chosen option: "Automatic points for submitting plus manual points from an admin", because the
participant gets immediate feedback and the admin can still judge quality.

Example: maximum 10 points, 2 awarded automatically on submission and 0–8 by the admin.

Rules:

* The admin sets the split when authoring the question; the plugin may offer defaults. The values are
  stored in the immutable revision.
* `max_points` always includes the manual part. Percentages and reward thresholds use the full maximum.
* An attempt with ungraded answers has status `PENDING_GRADING`. The participant sees a provisional score.
* The public scoreboard stays hidden until the run is closed and nothing is pending.
* Reward entitlements are evaluated, and draws allowed, only once nothing is pending.
* Photos are visible only to admins and are never public, so no public moderation is needed.
* Grading changes are written to `audit_event`.
* The image is rebuilt from pixels ([ADR-0028](0028-upload-limits.md)) and written to the media volume
  **before** the database transaction starts.
* A repeated submission reuses the stored image, and the cleanup job removes files no answer refers to.
* The type declares its requirements on run settings ([ADR-0034](0034-module-requirements-on-settings.md)):
  it needs stored individual answers and a scoreboard visibility of hidden or after grading.

### Consequences

* Good, because photo competitions become possible and affect ranking and rewards
* Good, because the automatic part of scoring stays a pure server operation
* Bad, because it adds an attempt status, a grading screen and recalculation after grading
* Bad, because there is no public scoreboard during such a run
* Bad, because draws wait until the admin finishes grading
* Bad, because it extends the scope of the original spec

### Confirmation

[AC-16](../acceptance-criteria.md).

## More Information

Defined by FR-45 in [../plugins/question-types.md](../plugins/question-types.md). Refines
[ADR-0009](0009-server-authoritative-scoring-signed-token-idempotent-submit.md): the server stays the
authority; manual points come only from an authenticated admin.
