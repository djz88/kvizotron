# Third-party files in the repository

Vendored unchanged, verified against the npm registry's `dist.integrity`. Never loaded from a CDN.

| File | Package | Licence | SHA-256 |
|---|---|---|---|
| `app/api/assets/htmx.min.js` | `htmx.org@2.0.11` | 0BSD | d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717 |
| `app/plugins/theme_default/assets/pico.min.css` | `@picocss/pico@2.1.1` | MIT (`pico.LICENSE.md`) | fbc9a63fc9fc9f72d12fd7fc9806e11fa9f77ae4f9cad146b27003a1119ba3db |

`htmx.min.js` contains `eval`, which the application switches off with `allowEval: false` (tested in `tests/api/test_security_headers.py`). Scanner findings in these files cannot be fixed here.

## Python dependency with a special reason

Pillow (pinned in `pyproject.toml`) rebuilds and shrinks uploaded images ([ADR-0028](docs/_architecture/adr/0028-upload-limits.md)). Licence: MIT-CMU.
