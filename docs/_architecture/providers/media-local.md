# Provider: local media

| | |
|---|---|
| Contract | `MediaStorageProvider` |
| Package | `app/providers/media_local/` |
| Stage | B |

## Requirements

- `FR-21` Images/media: local upload as well as external HTTPS URLs; allowed types and sizes, check of
  MIME/actual content, safe serving and protection against scripts in uploaded files. Images have
  alternative texts for supported languages.

## Behaviour

- Store `kind`, `storage_key`, `mime_type`, `size`, `sha256` in `media_asset`, and files under `KVZ_MEDIA_PATH`. Alternative texts belong to the question definition, so a revision freezes them; a missing one blocks publication.
- Plugins see only asset ids. The API stores uploads through the provider and builds addresses, so a replacement provider keeps the route `/media/<id>`.
- An address is fetched when a question is saved and goes through the same checks as an upload. What a participant gets, the fetch rules and the hourly check: [ADR-0043](../adr/0043-external-images.md). The provider declares `external_image_mode` and `allow_internal_image_addresses`.
- An admin's images are not deleted, so a published revision keeps its pictures. A participant's photo goes with the run's data, and the hourly pass removes private photos older than an hour that no answer refers to (`private_assets_older_than`, [ADR-0056](../adr/0056-retention-job-summary-held-runs.md)).
- The content decides, never the file name: formats PNG, JPEG, WebP, GIF, SVG. HEIC is refused with a message saying what to do. Images over 40 million pixels are refused, JPEG over 100 million, because it decodes small; the application has one worker.
- An SVG must parse as XML with the root `svg`, and may not declare entities or document type rules; a plain `DOCTYPE` from a drawing program is fine. Every file is served with `Content-Security-Policy: sandbox`, so an SVG opened directly runs nothing.
- Admin uploads: raster images are shrunk and compressed; SVG and GIF get a basic check and stay
  unchanged. SVG is embedded through `<img>`.
- Participant uploads: PNG, JPEG or WebP only, rebuilt from pixels, shrunk and compressed; the original
  is discarded. Served only to authenticated admins, never publicly.
- Files served from the media volume with safe headers (no inline execution).
- Limits (15 MB per upload; stored WebP at 1600 px and at most 700 KB; participant images 2 GB per run):
  [ADR-0028](../adr/0028-upload-limits.md).
