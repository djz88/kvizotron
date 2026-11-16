---
status: accepted
date: 2026-11-07
---

# ADR-0043: External images are copied by default, and a mode decides what a participant gets

## Context and Problem Statement

Admins want to use a picture from the web (`FR-21`). A picture loaded from its source can change or disappear inside a published quiz, tells another server who is playing, and fails without internet. Some organisers still want it.

## Decision Drivers

* A published quiz stays as it was published
* Participants' IP addresses stay here unless an organiser decides otherwise
* A server that fetches addresses given to it must not become a way into its own network

## Considered Options

* Fetch on save and show the copy
* Only load from the source in the participant's browser
* Both, chosen by an inherited setting

## Decision Outcome

Chosen option: "Both, chosen by an inherited setting", with the copy as the default.

- `external_image_mode` is `copy` or `external`, inherited as in [ADR-0042](0042-settings-inherited-and-declared.md). The lowest level is the question, so all its images share one value.
- Saving an address always fetches it, whatever the mode, so a copy normally exists and a later mode change needs no fetch. An unchanged address with a copy is not fetched again, so a copy never changes on its own.
- A malformed address is always refused. When a fetch fails, the effective mode decides: `copy` refuses and keeps the form; `external` saves with no copy and marks the question, and each later save tries again.
- An image with no copy always loads from its address. Publication is blocked only when the quiz's mode for that question is `copy`. A later change of a quiz or global value does not touch a published quiz.
- The source address is removed from public pages unless it is what they show. Admins see it in the editor and the change overview.
- The mode is resolved when a page is drawn, not frozen on the attempt, since it only moves where the same picture comes from.
- Opening a quiz checks the addresses it loads images from, after the page has loaded and at most once an hour. A failure warns the admin and blocks nothing.

### Fetch rules

Standard library only. 10 s and 15 MB per address, 25 s for all addresses of one save, 3 redirects. Each redirect is checked again and must stay `https://`. No credentials in an address, certificates always verified, and no cookies sent.

`allow_internal_image_addresses` is global only, and off by default. With it off, every address a name resolves to must be globally routable, and the connection goes to that checked address, so a name cannot answer differently the second time. An intranet picture still works as `external`, since the browser loads it and the server never does.

**Any admin can turn the switch on, so a stolen admin account could use it to reach the internal network.** The settings page says so, and the change is audited.

The branding logo and landing page logo take an address under these fetch rules, always as a copy and with no mode ([ADR-0054](0054-branding-owned-by-domain-and-theme.md), 2026-11-10).

### Consequences

* Good, because a copy goes through the same checks as an upload
* Good, because no job process is needed: the check runs in one of the worker's threads
* Bad, because `img-src` gains `https:` on all pages, which is simpler than a policy per page but wider than strictly needed; page text is escaped, and images carry `referrerpolicy="no-referrer"`
* Bad, because the check runs only when an admin opens a quiz, so nobody is told about a failure during a quiz nobody opens
* Bad, because a check notices only that a picture is gone, not that it changed
