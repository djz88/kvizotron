# Inline editing of names with a pencil: design

Tags: **[user]** the user decided, **[docs]** already in `docs/_architecture`, **[call]** my choice, open to correction.

## Why

A name in the administration is edited today in a form: a label, a field across the whole width, a full-width blue **Save** and below it **Delete** (bank page, "Name and removal"). The name looks like a form, takes room and does not say what is only shown and what can be changed. Some names cannot be changed where the user sees them (a folder from inside itself, a bank from its heading). An analysis of the administration (subagent, 2026-11-11, read from code, the bank page also in a browser) found 14 places that edit text and four names where an edit on the spot is missing.

## Goals

1. **A pencil next to a name [user: variant A with HTMX]**: the name is shown as text with a small "edit" icon button; one click turns it into a field with **Save** and **Cancel**; Enter saves and Esc cancels. Saving shows the name again, a refusal shows its message next to the field and keeps what was typed. **[user]** Without JavaScript the same works as full pages: the pencil is a link to `?edit=<field>` that draws the page with the field open, and **Cancel** is a link back.
2. **One component [call]**: a Jinja macro `admin/_inline_name.html` and two partials (the name shown, the name in edit), a small script for Enter and Esc and for focus, and HTMX for the swaps. Each place only gives its URLs and its field.
3. **Places [user]** (the list comes from the analysis, the user's answers decide it):
   - the **name of a bank**, as the heading of its page; the old field and **Save** in "Name and removal" go, **Delete the bank** stays there,
   - the **name of a folder**, in its row (replacing the rename field in the menu) **and for the folder one is inside**, next to its name in the trail and heading (today it can be renamed only from the folder above),
   - the **name of a quiz**, in the header of the quiz pages, **for the default language only**; the other languages stay in "Name and languages" **[call]**. **[user: probably yes]** Every change makes a draft, so next to the icon and after saving the page says that visitors see it after publication,
   - the **name of a reward**, in its row on the rewards page of a run, for the default language **[call]**; the pencil is a button beside the summary, not inside it, because a `<details>` summary would swallow the click,
   - the **nickname of a participant** in the table of attempts of a run, for an admin only **[user: yes, it makes sense]**, see below.
4. **Last one wins [user]**: no version check, as the forms do today.
5. **Banks and folders keep one name for all languages [user: not needed]**, but it must be clear what has languages **[user]**: the bank page shows, under its name, the languages its questions cover with the number of complete questions in each (`cs 40 · en 40 · uk 12`), and a language choice (chips, default the first the bank has) that sets the language of the question texts listed for the chosen folder and its subfolders. A question that lacks that language is listed with its first language and a mark. Folder names and counts do not depend on the language. **[call]** This reads "the languages the bank has, and then the chosen folder and subfolder with the questions in that language" as a display switch, not as translated folder names.

## The nickname of a participant [call on the details]

An admin can rename a nickname in the table of attempts of a run (moderation of a name that should not be on a scoreboard). Rules: the length limit of the field (40); the rule of the run that forbids equal names holds (`participants.name_is_taken`), so a taken name is refused with the same message; an empty value is refused, not an erasure (`Participant.name_dropped` is not touched); `name_key` is set as `claim_name` does; the cached scoreboard of the run is cleared (`results.clear_board_cache`); the audit entry `participant.renamed` carries neither the old nor the new name, as the audit rules require. It does not apply to a run whose data is deleted or whose profile keeps no name.

## Non-goals

- A name for a run (a run is `run_no`; a name needs its own decision) **[user: not now]**.
- The login of an admin, which is the identity in the audit log.
- Editing the prompt of a question inline: it is made of several fields and the editor validates it.
- Names of banks and folders in several languages **[user]**.
- A version check against two admins editing at once **[user]**.
- The silent redirect of a bank rename with an invalid name is **not a separate fix in this package [user: no]**. The inline form of the bank name has to show its refusal, so that path stops being silent as a consequence, and the old field is removed with it.
- The compact "variant D" form for other forms (only the places above change).

## Anti-goals

- A pencil that makes a change look final when it only changes a draft (a quiz).
- A rename that changes a published revision or an attempt in progress (AC-32); a bank or folder rename touches only the name, since draw rows refer to a folder by id and to a bank by id.
- A page that needs JavaScript to rename anything.
- Inline styles or scripts (CSP), or `hx-*` attributes that inherit into a field by accident (`app/api/CLAUDE.md`).

## Constraints

- Project rules apply. `HTMX_CONFIG` already swaps a 4xx response, so a refusal is a 400 partial. Every new POST route needs `{{ csrf_input }}` and an entry in the arguments of `tests/api/test_request_limits.py`; the script goes into `SCRIPTS` (`app/api/rendering.py`) and is used by a template (`tests/test_wiring.py`).
- Accessibility: the icon button has an accessible name with the name it edits ("Edit name: …"); focus goes to the field when it opens and back to the pencil when it closes; a result is announced (`role="status"` for saved, `role="alert"` for a refusal); the pencil is at least 44 px on a phone; the layout works at 390 px and in the dark theme with theme tokens only.
- Texts in cs and uk (`make messages`); new AC with test docstrings; `docs/_architecture/modules/api-ui.md` and the relevant ADR addenda (ADR-0041 for banks and folders, ADR-0054 for quiz names if it is the place, the rewards ADR for rewards) are updated by addenda, not new ADRs.
- The audit entries that exist stay (`bank.renamed`, `bank.folder_renamed`, the draft of a quiz); a rename of a reward and of a nickname is audited without the names.

## What is left to the builder

Names of routes and of partials; whether the quiz and reward renames reuse their current POST routes with a `field` parameter or get their own; the exact wording of the draft notice; where the language chips of a bank sit; how the script finds its fields (data attributes).
