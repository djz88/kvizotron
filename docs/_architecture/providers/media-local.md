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

- Store `sha256`, `mime_type`, `size`, `locale_alt_json` in `media_asset`.
- Admin uploads: raster images are shrunk and compressed; SVG and GIF get a basic check and stay
  unchanged. SVG is embedded through `<img>`.
- Participant uploads: PNG, JPEG or WebP only, rebuilt from pixels, shrunk and compressed; the original
  is discarded. Served only to authenticated admins, never publicly.
- Files served from the media volume with safe headers (no inline execution).
- Limits (15 MB per upload; stored WebP at 1600 px and at most 700 KB; participant images 2 GB per run):
  [ADR-0028](../adr/0028-upload-limits.md).
