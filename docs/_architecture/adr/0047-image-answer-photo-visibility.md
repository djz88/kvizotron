---
status: accepted
date: 2026-11-07
---

# ADR-0047: Photo visibility chosen by the admin, automatic points as a share, grading in Stage B

## Context and Problem Statement

[ADR-0033](0033-image-answer-question-type.md) says photos are visible only to admins, and [the roadmap](../roadmap.md) put grading in C4. Organisers also run photo contests with public results, and a question in a bank gets its points from a draw row, so fixed automatic points do not fit.

## Decision Drivers

* A photo is never public by accident
* No change to the contract between types and strategies ([ADR-0040](0040-question-types-grade-and-strategies-weigh.md))
* A file from the public is never served as sent

## Considered Options

* A three-level setting with approval per photo, and a share carried by `ItemGrade`
* Admins only, as before
* A new scoring strategy for mixed points

## Decision Outcome

Chosen option: "A three-level setting with approval per photo, and a share carried by `ItemGrade`".

* `photo_visibility` belongs to the image answer module, with all scopes: `author` (default) shows a photo to admins and its author through the private link; `admins` to admins only; `public` also to everyone on the walkthrough after the run ends, once an admin approves that photo. With `public` the question says so before upload. This replaces ADR-0033's statement that images are visible only to admins.
* The automatic part is stored as a whole-number fraction. `grade` returns it as `right` of `total`, with `wrong` 0, and the type offers only `partial`, which pays exactly that share. In a quiz the editor asks for points; in a bank it asks for whole percent, as points come from the row. Points stay whole; earned points need not.
* The module requires `reveal_moment` other than `after_each`, as a person's points do not exist yet ([ADR-0034](0034-module-requirements-on-settings.md)). This is the first real requirement.
* Grading arrives in Stage B. A row holds automatic and manual points, the score recalculates, and an attempt leaves `PENDING_GRADING` when no photo waits. Only a logged-in admin can change them, and every change is audited.
* Photos are private assets: `/media/<id>` answers 404, and they are served only through routes that check the right, with `Cache-Control: private, no-store`, so a withdrawn photo stays in no cache. Multipart on a public address is admitted only for `/a/<id>/submit` of an attempt holding such a question, in progress or finished, checked before the body is read. A finished one stores nothing, so a repeat after a lost answer still gets its result.
* A photo can become public only if the page warned about it when that attempt began. `told_public` on the attempt lists such questions, so raising the level later makes no earlier photo public, and only later attempts can be approved.
* One submission carries all photos of an attempt, so Caddy allows 101 MB on `/a/*/submit`, as on an import (amended by [ADR-0066](0066-single-container-image.md): 101 MiB, held by the application too). Each file stays within 15 MB, and the application admits multipart only as above.
* A file is stored before the transaction, under [ADR-0028](0028-upload-limits.md). One stored for a submission that then fails, or that lost to another, is removed at once. A form field naming an asset is dropped: the value comes only from a file received.

### Consequences

* Good, because public photos need two decisions, by level and per photo
* Good, because scoring stays one mechanism
* Bad, because deleting a photo cannot be undone, by design
* Good, because since D5 a photo reaches the server only through `submit`, which is limited per address ([ADR-0058](0058-rate-limit-buckets.md)), besides the per-run image limit and the body limit in Caddy

### Confirmation

[AC-55](../acceptance-criteria.md), [AC-56](../acceptance-criteria.md), [AC-57](../acceptance-criteria.md), [AC-61](../acceptance-criteria.md).

## More Information

Scoreboard, rewards and draws stay in Stage C, through the same requirements.
