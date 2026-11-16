# The shown address of one test link — design

Date: 2026-11-12. Status: draft for approval.

## Why

The address of a test link is built from the address the admin uses (`request.build_absolute_uri`). An admin who works over one address (`https://192.168.1.10:8443`) but sends a tester another one (a forwarded port, a public name) has to rewrite the link by hand every time.

## What

1. **A pencil at the address of each test link**, the same inline editing as names elsewhere (AC-160, `inline_name.py`). Editing opens a field with the start of the address only: scheme, host and port (`https://192.168.1.10:8443`). The path with the token (`/t/<token>`) stays fixed beside the field and cannot be changed.
2. **Saved with that link.** A new field `RunTestLink.shown_origin` (empty by default, migration). Empty means the address the admin uses now, as today. Saving an empty field returns to that.
3. **Only the shown and copied address changes.** The token, the end, the run, other links, the public address of the quiz and its QR code stay as they are. The app keeps serving the link on whatever address reaches it; the admin is responsible for the new address leading to this server.
4. **Validation.** `http://` or `https://`, then a host name, an IPv4 address or an IPv6 address in brackets, then an optional port 1–65535; nothing else (no path, query, fragment or user). Without a scheme `https://` is assumed. A trailing `/` is dropped. At most 200 characters. A refusal keeps the field open with the message (400), as other inline names do.
5. **Audit** `test_link.address_changed` with no value (the token is never in the audit; the origin is not needed there).
6. A link of an archived quiz shows no pencil, and its address cannot be saved (`ensure_editable`, as other changes).
7. **Docs.** AC-167, an addendum to ADR-0044, `data-model.md` for the new field, a line in `app/domain/CLAUDE.md`, Czech translations (administration is cs and en).

## Not in scope

- A global or per-quiz public address, the public address of the quiz and its QR code.
- Changing the token or the path.
- Checking that the new address reaches this server.

## Calls made here

- The pencil needs the inline component to show a fixed part after the value and its own pencil label ("Edit address"), so `NameField` gets `suffix` and `pencil_label`, both optional.
- Without a scheme the field assumes `https://`, as the app is served over HTTPS behind Caddy.
