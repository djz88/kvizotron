---
status: accepted
date: 2026-11-16
---

# ADR-0067: A quiz title is unique among active quizzes, and a quiz can name its public address

## Context and Problem Statement

An admin duplicated a quiz and then planned a run of the unpublished copy, which bore the same title as the published original; the refusal went unnoticed and the run never appeared. Separately, an operator who sends participants through another name or a redirect needs the QR code and public link of a quiz to use that address, while the admin works over another one (an IP address, a forwarded port).

## Decision Drivers

* Two quizzes an admin works with are never mistaken for each other
* A copy says that it is a copy
* A printed QR code leads where participants can actually reach the quiz
* No rule that a hand edit, an import or a restore can bypass

## Considered Options

* (a) Unique titles enforced by the database
* (b) Unique titles per language among quizzes that are not archived, checked by the domain on every path that sets a title
* (c) A global public address only
* (d) A public address per quiz, empty for the admin's own address

## Decision Outcome

Chosen options: (b) and (d).

* Titles compare per language, ignoring letter case and runs of spaces; archived quizzes do not count (`authoring.taken_titles`, `ensure_title_free`). A title stored as JSON per language cannot carry a database constraint, so (a) was not possible.
* A new quiz, the content form and the name edited on the spot refuse a taken title at the field (the name on the spot with 400, like any name that does not validate); restoring from the archive, going back to a revision and discarding a draft refuse with 409 when another quiz took the title meanwhile.
* A duplicate is always named "Title (copy)", "Title (copy 2)" in each language (cs "kopie", uk "копія"), even of an archived quiz, cut so that the whole stays within 200 characters; an import takes the first free "Title (2)" with a warning, as it does for a taken address.
* `Quiz.public_origin` holds `https://host:port` (validated like the address of a test link, `run_links.clean_origin`: no path, query or credentials). The QR code, the public address on the Runs tab and run page and the link in the quiz header use it; empty keeps the address the admin is on. It is set on the new quiz form and in the quiz settings, a duplicate keeps it, and it may change at any time; the help text says to print the QR code again.

### Consequences

* Good, because copies and originals are told apart in every list.
* Good, because the QR code works behind a redirect or another host name.
* Neutral, because quizzes that already shared a title before this decision keep it: only a title that changes is checked (`new_titles`), so they can still be saved, go back to a revision and discard a draft.
* Neutral, because the rule compares `Quiz.title`, the title being edited; public pages show the title of the published revision until the next publication, so for that time two public pages can show one name.
* Neutral, because `taken_titles` reads the titles of every quiz that is not archived and compares them in Python (JSON titles have no index); that is meant for hundreds of quizzes, not thousands.
* Neutral, because a form checks the title before the transaction that saves it; two admins saving the same new title at the same moment can both succeed. With a handful of admins this is accepted.
* Neutral, because test links keep their own shown address ([ADR-0044](0044-preview-and-test-links.md)).
