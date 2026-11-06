---
status: accepted
date: 2026-11-05
---

# ADR-0028: Upload rules and limits

## Context and Problem Statement

FR-21 requires allowed types, sizes and a content check, without concrete values. Ordinary phone photos
must be accepted, but stored images must stay small for mobile viewing and must not fill the disk,
because a full disk also stops SQLite. Admins are trusted and need formats such as SVG. Participants
are anonymous, so their uploads also carry disguised files, hidden data, decompression bombs and GPS
metadata.

## Decision Drivers

* Ordinary phone photos must fit
* Small stored images and bounded disk use
* Proportionate security; no unnecessary machinery

## Considered Options

* Shrink and compress raster images, with limits per file and per run; basic check for admin SVG
* Store files unchanged with a small per-file limit
* Add a sanitiser for SVG and an antivirus scanner

## Decision Outcome

Chosen option: "Shrink and compress raster images, with limits per file and per run; basic check for
admin SVG", because phone photos are accepted while stored size stays predictable.

| | Admin upload | Participant upload |
|---|---|---|
| Formats | Common image formats including SVG | PNG, JPEG, WebP |
| Upload limit per file | 15 MB (SVG, GIF: 5 MB) | 15 MB, plus a pixel limit |
| Processing | Raster shrunk and compressed; SVG and GIF stored unchanged after a basic check | Rebuilt from pixels, shrunk and compressed; original discarded |
| Stored raster image | WebP, longest side 1600 px, at most 700 KB | WebP, longest side 1600 px, at most 700 KB |
| Total limit | None | 2 GB per run |

All values are configurable defaults.

Rules:

* If a compressed image exceeds 700 KB, quality is lowered step by step, then dimensions.
* When the per-run limit is reached, further images are refused with a clear message.
* No SVG sanitiser and no antivirus scanner. This deliberately relaxes the original spec wording
  "reject or sanitise" for SVG, because only admins upload it.
* SVG is embedded through `<img>`, where browsers do not run its scripts.

### Consequences

* Good, because rebuilding removes hidden data, disguised files and EXIF including GPS
* Good, because images load quickly on phones
* Good, because the per-run limit bounds disk use: 2 GB holds about 2 900 images of 700 KB
* Good, because the only added dependency is an image library (Pillow)
* Bad, because someone can exhaust a run's limit and block further image answers in that run
* Bad, because a compromised admin account could upload a harmful SVG
* Bad, because compression costs CPU during upload, and the image library must be kept up to date
* Bad, because detail is lost, and HEIC behaviour must be verified on phones in Stage B

### Confirmation

Upload tests: false extension, oversized file, too many pixels, EXIF removed, stored size at most
700 KB, per-run limit reached. [AC-16](../acceptance-criteria.md).

## More Information

Resolves [OQ-07](../open-questions.md). [../providers/media-local.md](../providers/media-local.md).
