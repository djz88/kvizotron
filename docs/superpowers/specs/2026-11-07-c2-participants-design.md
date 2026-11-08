# C2 Participants: cookie identity, attempt rules, access code, name and e-mail: design

Status: agreed in conversation 2026-11-07, awaiting the user's review of this document. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

A competition needs to know who played and to stop the easy ways of playing twice (`FR-27`, `FR-28`). An organiser running a closed event needs to keep strangers out with a code (`FR-06`), and may need a name for the results or an e-mail to contact the winner (`FR-32`).

Today every attempt is anonymous and independent: there is no participant, no cookie, no access code and no name. Anyone with the link can play any number of times. C1 gave runs a schedule, a deadline and a time limit; C2 gives them people.

## Goals

1. **Repetition rule** per run: allow or forbid, default allow **[user]**.
2. **Anonymous cookie identity** per run, so a forbidden repeat can be recognised **[docs]**.
3. **Name and e-mail collection**: off, optional or required, asked before the start or at the end **[user]**.
4. **Duplicate nicknames** in a run: allow or forbid **[docs]**.
5. **Access code** per run, stored as a hash only **[docs]**, **[user]**.
6. **Attempts table** on the run page for the admin: name, e-mail, score, submission time **[user]**.

## Non-goals

- Official ranking policy (first valid, best valid) and the scoreboard: C4 **[docs]**.
- Showing names publicly: C4 with the scoreboard **[call]**.
- Sorting and export of the attempts table: C4 **[user]**.
- Keeping entered answers of an unfinished attempt across reloads: C3 **[docs]**.
- Retention, deletion and anonymisation of participant records: D3 **[docs]**.
- Accounts, logins or any guarantee that one cookie is one person **[docs]**.
- Settings of these rules per question: they concern the whole attempt, which is the reason ADR-0042 requires **[user]**.

## Anti-goals

- An access code readable anywhere after it was set: in the database, a log, a QR code or a page.
- An e-mail shown anywhere outside the logged-in administration, or written to a log **[docs]**.
- A forbidden repeat that works by reloading the page or opening a new tab in the same browser.
- A cookie, or a participant row, for a run whose rules do not need one.
- A forbidden repeat that works by abandoning an attempt and starting another.
- Two runs linkable through the stored cookie hash.
- A participant losing a valid score because a name was missing when the time ran out.
- Security heavier than a quiz needs: no CAPTCHA, no fingerprinting, no e-mail verification **[user]**.

## Behaviour

### Settings

All five rules are settings inherited global → quiz, copied onto the run when it opens or is planned, editable on the plan form, fixed once the run is open **[user]**. This is the same path as the attempt time limit in C1.

| Setting | Values | Default |
|---|---|---|
| Repetition | allow, forbid | allow **[user]** |
| Unfinished attempt when repetition is forbidden | continues the same attempt; used up by starting; counts only when submitted | continues **[user]** |
| Name | off, optional, required | off **[call]** |
| E-mail | off, optional, required | off **[call]** |
| When to ask | before the start, at the end | at the end **[user]**, **[docs]** |
| Duplicate nicknames in a run | allow, forbid | allow **[call]** |

- `FR-32` today says the data are asked at the end. The user made it a choice with the end as default; `docs/privacy.md` is updated to say so **[user]**.
- "When to ask" only matters when name or e-mail is not off; the form says so **[call]**.

### Cookie and participant

- A participant row and its cookie are created only when the run needs them: repetition forbidden, or name or e-mail not off **[call]**. Otherwise play works as today and stores nothing new.
- An access code alone needs no participant row. A correct code is remembered in a separate signed cookie for that run, carrying no identity **[call]**.
- The cookie holds a random key. The database stores only a hash of the key together with the run id, so the same browser gives different hashes in different runs **[docs]**, **[call]**.
- The cookie is `HttpOnly`, `Secure` behind TLS, `SameSite=Lax`, limited to the run's path or keyed by run, and lives at least as long as the run can accept attempts **[call]**.
- The plan form says that the cookie does not guarantee one person: a different browser or a private window is a new participant **[docs]**.
- An attempt records its participant when there is one **[docs]**.

### Repetition

- Allow: every start is a new attempt, as today **[user]**.
- Forbid, with the three values for an unfinished attempt **[user]**:
  - **continues**: returning to the quiz resumes the same attempt with the same questions; the time limit keeps running; answers entered before the reload are gone until C3. If the limit or the deadline has passed and the attempt was never submitted, the participant sees "time is up", has no score and cannot play again **[user]**.
  - **used up by starting**: once started, the participant cannot start again, even if never submitted.
  - **counts only when submitted**: an unsubmitted attempt does not block a new one; a submitted one does. Starting a new attempt closes the previous unsubmitted one, which can then no longer be submitted **[call]**.
- A refused second attempt sees a plain page saying they already played this run, with a link to their own result if it exists **[call]**.
- The check runs on the server at start and again at submission, in one transaction, so two tabs cannot both pass **[call]**.

### Name and e-mail

- Asked before the start: fields on the quiz page next to the start button; the attempt does not start until they validate **[user]**.
- Asked at the end: fields on the last step before submission **[user]**, **[docs]**.
- If the time runs out with a required name or e-mail missing at the end: the attempt is accepted and its score is valid, and the result page asks to fill them in. Until then the admin sees "bez jména" **[user]**.
- A taken nickname under "forbid" during automatic submission: the attempt is accepted without a name, and the result page offers to enter a different one **[call]**.
- A taken nickname on a manual submission: refused with a message, the attempt stays open and the answers stay on the screen **[call]**. With "before the start" the name is also checked at the start, for early feedback; the binding check is at submission **[call]**.
- Only submitted attempts hold a nickname; an abandoned attempt reserves nothing **[call]**.
- A missing name or e-mail is filled in through the private result link, until the run is archived **[call]**.
- Nickname comparison ignores case and surrounding spaces and collapses inner spaces; the shown name keeps what was typed **[call]**. Length limit 40 characters **[call]**.
- The duplicate check is atomic per run, not only in the form **[docs]**.
- E-mail is validated by the server for format only; no confirmation message is sent **[docs]**, **[call]**.
- Next to the fields: one short line about what the data are for and a link to `/privacy` **[docs]**.
- No name, e-mail or answer is written to a log **[docs]**.

### Access code

- Belongs to the run only, not inherited **[call]**. It is set on the plan form or on a running run. `Spustit` in one click opens a run without a code **[call]**.
- The admin types a code or generates one. It is shown once after saving; afterwards only a hash exists **[user]**. A forgotten code cannot be shown, only replaced **[user]**.
- The QR code and the public link never contain it **[user]**.
- The participant enters it on the quiz page before the start, once per run per browser; success is remembered in the browser for that run **[user]**, **[call]**.
- Changing the code on a running run stops those who have not started yet; attempts already started continue **[call]**. Removing the code opens the run to everyone **[call]**.
- Failed codes are limited to 10 per minute per IP, in process memory **[docs]**.
- The public walkthrough after a run closes and the private result link do not ask for the code **[call]**.

### Admin attempts table

- On the run page: name, e-mail, score, submission time, one row per submitted attempt **[user]**, **[call]**. Unsubmitted attempts are only counted, as in C1 **[docs]**.
- No deletion of names and e-mails in C2: it comes with retention in D3 **[user]**.
- E-mail appears only here, in the logged-in administration **[user]**, **[docs]**.

### Test links and preview

- No access code and no repetition limit **[call]**.
- The name and e-mail fields appear, so the admin can see them **[call]**.
- Preview stores nothing. A test attempt's data are deleted together with its test link **[call]**.

## Constraints

- The feature lives behind a contract as the participant policy (`ParticipantPolicyPlugin`, `app/plugins/participants/`) **[docs]**. Every setting is declared in the manifest **[docs]**.
- ADR-0011 cookie identity, ADR-0030 code attempt limit, ADR-0042 setting inheritance **[docs]**.
- Every text in cs, en and uk; a run is `běh` / `run` **[docs]**.
- Phone width, light and dark, keyboard **[docs]**. No build step **[docs]**.
- A new ADR (0049) records: cookie created only on need, the separate code cookie, the hash bound to the run id, the code per run without inheritance, and "when to ask" as a setting. New `AC-xx` from AC-70 **[docs]**.

## Risks

- **Cookie blocked or cleared.** The participant becomes new. This is the documented limit of ADR-0011, said on the plan form **[docs]**.
- **Shared device at an event.** Under "forbid", the second person on the same browser is refused. The refusal page says it is per browser **[call]**.
- **In-memory code limit.** Resets on restart and is per worker process. Accepted for a quiz by ADR-0030 **[docs]**.
- **Personal data in the database.** Names and e-mails now exist; retention comes in D3. Until then `docs/privacy.md` says plainly that they are kept and that deletion arrives with retention in D3 **[user]**.

## Left to the builder

- Cookie name and exact path.
- Hash construction, provided it uses a keyed hash with the server secret and the run id, and is not reversible.
- Where in the play flow the checks sit, provided start and submission both enforce them on the server.
- Code generator length and alphabet, provided it is easy to read aloud (no `0/O`, `1/l`).
- Layout of the fields, the code form and the attempts table, following existing pages.

## Verification

- `make quality` and `make smoke` **[docs]**.
- Tests for each rule above through real addresses, including two simultaneous starts under "forbid" and two simultaneous identical nicknames under "forbid".
- A test that no log line contains a test e-mail or name.
- A walkthrough in the browser on a new quiz in the `kvizotron-browser` stack, without deleting its data **[user]**: code set and changed, wrong code, forbidden repeat in each of the three modes, name before the start and at the end, time running out with a required name, duplicate nickname, the attempts table. Phone width, dark mode and Ukrainian included.
