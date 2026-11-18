# Module: app/plugins/drawings

Plugin `drawings.manual`, port `drawing`: pure drawing rules (FR-37, ADR-0013). Deterministic snapshot order (`order`: sorted and unique ids), snapshot fingerprint (`fingerprint`: sha256 of the ids joined by `\n`) and selection through `secrets.SystemRandom().sample` (`select`). The algorithm name is in `algorithm` and is stored with the drawing.

## What the module contains

`selection.py` (`ManualDrawing`), `manifest.py` without settings, `apps.py`.

## What the module is not

It touches neither the database nor the request. Who is eligible, the drawing records, substitutes and the audit are in the domain; the plugin receives participant ids (not names) and returns the order or the selection.

## Forbidden

Importing from `app/domain`, `app/api` or from another plugin: only `app.contracts` is allowed. Randomness only from `secrets`, never `random` with its own seed.
