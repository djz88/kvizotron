# C3 Data policies: what a run stores, how long, and local resume: design

Status: agreed in conversation 2026-11-08, awaiting the user's review of this document. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

An organiser should keep only the data their event needs (`FR-33`), and some events need nothing stored at all: the participant sees a score and the database keeps no result (`FR-31`, `AC-09`). Today every submitted attempt keeps its score and duration, and the choice of stored answers is a separate setting from B6 that only covers answers.

A participant who reloads the page or loses the connection loses every answer entered so far, even when the attempt itself continues on the server (C2 "continues"). `FR-22` asks for a short-lived copy in the browser.

C3 also lets the organiser record how long a run's data are kept (`ADR-0029`), so the privacy page can say it; the deleting job itself comes in D3.

## Goals

1. **One data profile** per run with four levels: nothing, score only, score and answers, detailed **[user]**, **[docs]**.
2. **Stateless mode** under "nothing": the participant gets a score and no result remains **[docs]**, **[user]**.
3. **Retention period** chosen per run and shown, without deletion yet **[user]**.
4. **Local resume** of an unsubmitted attempt in the same browser **[docs]**, **[user]**.

## Non-goals

- Deleting or anonymising data when the period ends, targeted deletion and backup retention: D3 **[docs]**, **[user]**.
- The public scoreboard, draws, statistics and export that depend on the profile: C4, C5 and D2 **[docs]**. C3 only records what a profile allows, so they can refuse later.
- Time spent on each answer. The server receives one submission and does not trust client times **[call]**.
- Resuming without JavaScript **[call]**.
- Keeping a chosen photo across a reload: the participant selects it again **[docs]**.

## Anti-goals

- A row, a name, an e-mail, an answer or a duration left in the database after a submission under "nothing".
- A setting combination the server would silently ignore. The form refuses it.
- A browser copy trusted for score, identity, start time or which questions were given **[docs]**.
- A name or e-mail written to `localStorage` **[call]**.
- Answers left in the browser after the attempt was submitted.
- An existing quiz that changes what it stores because of the upgrade, apart from the duration under the default **[user]**.

## Behaviour

### Data profile

One setting `data_profile` replaces `store_answers` **[user]**. Inherited global → quiz, copied onto the run when it is planned or opened, editable on the plan form, fixed once the run opens **[user]**, the same path as the participant rules in C2. No question level: it concerns the whole attempt, the reason ADR-0042 asks for **[user]**.

| Value | Kept after submission |
|---|---|
| `none` | Nothing per attempt; the run keeps a count of submitted attempts **[user]** |
| `score` (default) | Score, submission time, and answers a person must grade, photos included **[user]** |
| `answers` | As `score`, plus every answered question (today's `store_answers=all`) **[user]** |
| `detailed` | As `answers`, plus the attempt's duration **[user]** |

- The upgrade turns `store_answers=all` into `answers` and `images` into `score`, at every level where it is set **[user]**. Attempts already stored keep what they have.
- Every existing run, planned, open or ended, gets its quiz's converted value copied at upgrade, which is what its attempts use today. An open run is then fixed like any other; a planned one stays editable **[call]**.
- Under `score` and `answers` the duration is not stored **[user]**. The admin's test-link list shows the duration only when it exists.
- `answers_visibility` other than `admins` needs `answers` or `detailed`, as it needed `store_answers=all` (ADR-0046) **[docs]**.
- A test run reads the quiz's profile live, as it reads the other rules **[call]**.

### Stateless mode (`none`)

- A start creates an attempt row as today, holding the assigned questions, the start and the token. It has no participant **[user]**.
- A submission computes the score, deletes the attempt row with anything attached to it, increments the run's count, and answers with the score on the page **[user]**. No private result link is offered.
- A second submission of the same attempt, for example an automatic one racing a manual one, finds no row. A token with a valid signature but no row gets a plain page saying the attempt was already submitted or has ended, without the score; no tombstone row is kept **[call]**.
- An attempt never submitted stays as an anonymous row with no answers until D3 cleans it up **[call]**.
- The form refuses `none` together with any of: repeating forbidden, name or e-mail not off, `answers_visibility` other than `admins`, a photo question in the revision, or public photos. The refusal names the conflicting setting **[user]**, **[call]**.
- A running `none` run refuses a switch to a revision with a photo question; publishing it still works, and the run keeps its revision with a notice saying why **[call]**.
- Reveal works as today: `at_end` is shown in the submission response and `after_each` stores nothing. No later page exists under `none`, so nothing to refuse **[call]**.
- The admin sees, before choosing `none`, what it rules out: attempts table, private result link, later scoreboard, draw and export (`FR-31`) **[docs]**.
- The run page shows the count of submitted attempts instead of the attempts table **[user]**.

### Retention period

- The run stores a period: 30, 90 or 180 days, 1 year, 3 years, or permanent, counted from the run's close **[docs]**. Pre-filled 90 days **[docs]**.
- Inherited global → quiz like the profile, copied onto the run **[call]**. Unlike the profile it stays editable on a running or ended run, because it changes no data collected **[call]**.
- The run page shows the run's period. The public privacy page shows the global default and says a quiz may set a different one; it reads no run data **[call]**. No job deletes anything yet; both pages say that deletion arrives in a later version **[call]**.
- Under `none` the period still applies to the anonymous unsubmitted rows and the count **[call]**.

### Local resume

- Setting `local_resume`, on or off, default on, inherited global → quiz, declared by the module `quiz_flow` **[user]**, **[call]**. Changing it on a running run applies to attempts started afterwards **[call]**.
- While an attempt is open, the page keeps in `localStorage`, under a key for the run: the attempt token, the entered answers except photos and the name and e-mail fields, the current step, and an expiry **[docs]**, **[call]**.
- The expiry is the attempt's end (limit or deadline) when it has one, else 24 hours from the start, never longer than 24 hours **[user]**.
- The copy is deleted on a successful submission, on a refusal saying the attempt is over, and when it expires **[user]**.
- Returning to the quiz page with a valid copy shows "Continue" as the main button. "Start again" appears beside it only when the run's rules allow a new attempt **[user]**.
- "Continue" sends the token to the server, never in the address. The server checks that the attempt belongs to this run, is in progress, not abandoned, and still in time, and that the run accepts submissions; otherwise it refuses and the page deletes the copy. It then renders the attempt's own questions in their own order, and the page fills in the stored answers and step **[docs]**, **[call]**.
- The token is proof that the attempt was started, so "Continue" needs no access-code cookie, matching C2 where a changed code still lets a running attempt resume (ADR-0049) **[docs]**, **[call]**.
- A stored answer that no longer fits its question, for example after a revision switch, is dropped silently **[call]**.
- The page says that a photo must be chosen again **[docs]**.
- Under "used up by starting" a resume of the same attempt is allowed, since it is not a new start **[call]**. Under "counts only when submitted" a resume keeps the attempt instead of abandoning it.
- The server re-validates every answer at submission as today; the copy changes no score, time or identity **[docs]**.

### Admin forms

- The quiz settings and global settings pages show the profile with a short line per value about what it keeps and what it rules out **[call]**.
- The plan form shows the profile and the period; the run page shows both, and the period can be changed there **[call]**.

## Constraints

- ADR-0012 (profiles and stateless mode), ADR-0020 (untrusted local resume), ADR-0029 (default period), ADR-0042 (setting inheritance), ADR-0046 (stored answers and visibility) **[docs]**.
- A new ADR-0050 records: the profile replacing `store_answers`, the four values, the stateless attempt that lives until submission, the period as a run value without a job, and local resume on by default, which changes ADR-0020's "opt-in" **[user]**.
- Every setting declared in a manifest or the domain catalogue, with its scope and reason **[docs]**. The profile and period stay in the domain catalogue next to today's `store_answers` **[call]**; the `retention` provider with its job comes in D3.
- Every text in cs, en and uk; a run is `běh` / `run` **[docs]**. Phone width, light and dark, keyboard. No build step **[docs]**.
- New `AC-xx` from AC-77 **[docs]**.

## Risks

- **Shared device.** Answers stay in the browser until the attempt ends, at most 24 hours; another person on the same browser could see them. The quiz page says answers are kept on this device, and the admin can turn resume off **[call]**.
- **Lost score under `none`.** If the response with the score never arrives, the participant cannot see it again. Accepted: that is the meaning of the mode, and the page says so before the start **[call]**.
- **Duration gone by default.** Rankings by time in C4 need `detailed`; the form says so **[user]**.
- **Migration of settings.** Settings rows and frozen attempt settings must convert without changing what existing attempts show **[call]**.

## Left to the builder

- Field names and storage of the profile, the period and the count on the run.
- The address and form of "Continue", provided the token travels in a POST body.
- The `localStorage` key format and how the page restores a step.
- Where in submission the stateless delete happens, provided it is in the same transaction as the scoring.
- Layout of the new fields, following existing pages.

## Verification

- `make quality` and `make smoke` **[docs]**.
- Tests through real addresses: each profile stores exactly what the table says; `none` leaves no attempt, answer, participant or photo row after submission and shows the score; a repeated stateless submission; each refused combination; the settings migration; the period copied, shown and editable; resume refused for a finished, expired or other run's token; a resumed attempt keeps its start and questions.
- A browser walkthrough on a new quiz in `kvizotron-browser`, without deleting its data **[user]**: each profile on the form, a stateless run, the period on the run page, a reload in the middle of a one-page and a step-by-step attempt, a photo question after a reload, "Start again" shown and hidden by the rules, and the copy gone after submission. Phone width, dark mode and Ukrainian included.
