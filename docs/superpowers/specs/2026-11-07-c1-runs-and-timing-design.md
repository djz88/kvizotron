# C1 Runs: schedule, deadline and attempt time limit: design

Status: agreed in conversation 2026-11-07, awaiting the user's review of this document. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

Stage C is about a complete competition cycle. A competition has a fixed time: it starts at an announced moment, it ends at a deadline, and everyone gets the same time for their attempt (`FR-10`, `FR-11`). When it is over, the organiser runs it again with a clean slate and tucks the old run away (`FR-12`).

Today a run opens with one click and ends with another. Restart already works: a new run gets a new number and empty results (`AC-05`, ADR-0007). There is no schedule, no deadline, no time limit and no countdown, the run status `ARCHIVED` is unused, and every time is shown in UTC with no configured time zone.

## Goals

1. **Plan a run** with an optional start and an optional deadline **[docs]**, next to the existing one-click start **[user]**.
2. **Attempt time limit**, inherited global → quiz → run **[user]**, enforced by the server **[docs]**.
3. **Countdown** for the participant, automatic submission about 5 s before the end **[docs]**, and a notice of the available time before an attempt starts **[user]**.
4. **Move or remove the deadline of a running run** **[user]**.
5. **"Coming up" section** on the public list, a setting global → quiz, off by default **[user]**.
6. **Archive an ended run**, hidden in admin and from the public walkthrough **[user]**.
7. **Configured time zone** and a display of server and browser time for the admin **[user]**.
8. **Test links and preview** have the limit and countdown; preview can switch it off **[user]**.
9. **Count of unsent attempts** per run for the admin **[user]**.

## Non-goals

- A time limit per question: a different feature that changes navigation **[user]**.
- A queue of planned runs: at most one run is running or planned per quiz **[user]**.
- Reopening an ended run: a new run is the way **[user]**.
- Storing answers on the server during play: an unsent attempt is lost **[user]**. Local resume is C3 **[docs]**.
- A rule against starting close to the deadline: the start is not blocked **[user]**.
- Scoreboard, results and reveal after a run closes: C4 **[call]**.
- Deleting data of an archived run: D3 **[docs]**.
- A per-quiz time zone: one zone per installation **[user]**.
- Copying a previous run's settings on restart (ADR-0007 allows it): the limit comes from inheritance, so there is nothing else to copy yet **[call]**.

## Anti-goals

- A browser's clock or a browser's claim about time deciding whether a submission counts.
- A submission accepted after `min(deadline_at, started_at + limit)`, under the rules of ADR-0025.
- A way to gain time: reloading, switching to a new revision, repeating a request or changing the token.
- Participants in one run with different time limits.
- A run shown with an out-of-date status because nobody triggered a job.
- A test attempt or preview counting for anything.
- A draft reaching participants through a planned run.

## Behaviour

### Starting and planning

- `Spustit` keeps opening a run in one click, with the inherited limit and no deadline. A deadline can be added to the running run afterwards **[user]**, **[call]**.
- `Naplánovat…` beside it opens a form: start, deadline, limit **[user]**. The limit is prefilled with the inherited value and can be overridden or emptied **[user]**. An empty start opens the run immediately, which is also how to start at once with a deadline or a different limit **[call]**.
- Refused with a message: a start or deadline in the past; a deadline not after the start; a plan when a run is already running or planned; a plan with no published revision or unmet module requirements **[user]**, **[call]**.
- A planned run can be edited, cancelled, or started now. Cancelling removes it and frees its number, because no attempt can exist yet **[call]**.
- At the start moment the run takes the newest published revision **[user]**. The run page says which revision that is **[user]**. Publishing while a run is planned does not ask anything about it **[user]**.
- A quiz with a planned run cannot be archived, the same as with a running one **[call]**.
- The main button on the quiz, with a planned run: `Spustit hned`, plus edit and cancel **[call]**.
- If module requirements are unmet at the start moment, the run stays planned, does not open, and the admin sees why on the quiz. It opens once they are met, unless the admin cancels it **[call]**.

### Status over time

- Run statuses: `SCHEDULED`, `OPEN`, `CLOSED`, `ARCHIVED`. The names are final, internal and never shown **[docs]**, **[call]**. At most one `SCHEDULED` or `OPEN` normal run per quiz, enforced by the database **[user]**.
- No background process is needed: a due change is applied on the first request after it is due, and every status reader sees the result **[call]**. Reaching the deadline stores `closed_at` equal to the deadline and emits `run.closed` as a manual close does; opening stores `opened_at` equal to the planned start **[call]**. The change is idempotent under concurrent requests **[call]**.
- The submission check itself compares against the deadline, so it never depends on the status having been updated **[docs]**.
- A manual end still rejects attempts in progress, as today **[docs]**.

### Time limit

- Setting `attempt_limit`: scopes global and quiz, whole minutes 1 to 1440 or an explicit "no limit", global default "no limit" **[user]**, **[call]**. A quiz inherits unless it has an override, and its override can be a number or "no limit", so a quiz can drop a global limit; removing the override returns to inheriting **[docs]**, **[call]**. An empty limit on the plan form means no limit for that run **[call]**. It is copied onto the run when the run is planned or opened, and a planned run's value can still be edited **[user]**, **[call]**.
- Not on the question: it counts from the attempt's start, so a question has no use for it. This is the written reason ADR-0042 asks for **[user]**.
- Fixed once the run has opened, so everyone gets the same time **[user]**.
- Switching to a new revision keeps the original start, so it gains no time. The code already keeps `started_at` **[docs]**.

### Deadline on a running run

- It can be moved or removed and applies to attempts in progress **[user]**.
- A new deadline must be at least 1 minute ahead, so running pages can learn about it; ending now is the manual end **[call]**. When the deadline moves earlier, the admin is told how many attempts are in progress and confirms **[call]**. The change is audited **[call]**.
- Open play pages ask the server for the remaining time every 30 s and when the tab becomes visible again, so a moved deadline reaches them **[call]**. The server answers with seconds remaining, so a wrong browser clock does not matter **[call]**.

### Participant

- A planned quiz's address and QR code always show the title, description and start time, without a start button **[user]**. Starting before the start moment is refused by the server **[call]**.
- The planned page does not poll. It knows the seconds remaining from the server and reloads once at the start moment, each page with a random delay of up to 5 s, so the start button appears for people waiting in a room **[call]**.
- If the start moment has passed and the run could not open, the page says the quiz has not started yet, without a time **[call]**.
- With the setting on, the public list shows it under `Chystá se` **[user]**. The setting's scopes are global and quiz; a question has no use for it **[user]**.
- Before starting, the page states the limit and the deadline. When the deadline shortens the limit, it states the real time **[user]**. Starting is never blocked **[user]**.
- During play a countdown is always visible when any time applies **[user]**. It is announced to screen readers at 5 minutes and 1 minute, not every second **[call]**.
- About 5 s before the end the page submits what it has **[docs]**. Unanswered questions count as unanswered and do not block this submission, in all three navigation modes **[call]**. The result says the time ran out **[call]**.
- A submission arriving late, including a slow photo, is rejected **[docs]**, with a message that says so **[call]**.
- A submission received in time counts even if storing it finishes after the limit: the time is taken once on receipt (ADR-0025), and a busy database makes the store step wait rather than fail **[docs]**, **[call]**. SQLite already waits up to 20 s for a lock before `with_retry` starts its short retries; the load test in Risks confirms that this is enough or sets a longer budget **[call]**.
- If the automatic submission gets no answer because of a network error, the page retries with the same submission key, so it cannot be stored twice. A retry that arrives after the limit is rejected, unless the first one was stored **[call]**.

### Unsent attempts

- An attempt that never arrives has no score and counts nowhere **[user]**. It stays `IN_PROGRESS`; no new status **[call]**.
- The run page and the list of runs show, next to submitted, how many were not sent: on an ended run all attempts in progress, on a running run those past their limit **[user]**, **[call]**. Attempts replaced by a revision switch are not counted **[call]**.

### Archiving a run

- Only an ended run can be archived, and it can be restored **[user]**, **[call]**. Nothing is deleted **[user]**.
- It disappears from the main list of runs, behind `Zobrazit archivované` **[user]**. The public walkthrough stops working **[user]**.
- A participant's private result link keeps working **[user]**. Attempts waiting for grading can still be graded **[call]**.
- Audited **[call]**.

### Time zone and clocks

- A global setting, default `Europe/Prague` **[user]**, with an IANA zone name chosen from a list **[call]**. No quiz override: one installation serves one place, and different zones in one list would mislead **[user]**.
- Stored times stay UTC **[docs]**. All times shown in admin and on public pages use this zone and name it, including those shown in UTC today (runs, revisions, test links) **[user]**, **[call]**.
- Entered times are read in this zone. A time that does not exist on a clock change is refused; an ambiguous one takes the first occurrence **[call]**.
- **Clock panel for the admin** **[user]**: server time and browser time, each with its zone. It is on the plan form, the run page and the settings page **[call]**. It warns when the clocks differ by more than 60 s, or when the browser's zone differs from the configured one **[call]**.

### Test links and preview

- A test link takes the limit from the quiz settings when an attempt starts, with countdown and automatic submission **[user]**. A run's deadline does not touch it **[call]**.
- Preview has the limit and countdown too, with a switch on the preview page **[user]**. The switch starts off, because preview is mostly for looking at questions; turning it on simulates whether the quiz can be finished **[call]**. A submission over the limit is refused as in a real run, and nothing is stored **[call]**. Reloading a preview starts it again with a full limit: nothing counts there, and the time lives only in its signed token **[call]**.

## Constraints

- Boundary rules are ADR-0010 and ADR-0025: server receive time, whole seconds, `<=` **[docs]**. `AC-07` must pass as written **[docs]**.
- Every text in cs, en and uk through the catalogues; a run is `běh` / `run`, never `kolo` **[docs]**.
- Works at phone width, in light and dark, by keyboard **[docs]**. No build step **[docs]**.
- No answers or personal data in logs **[docs]**.
- `QuizRun.objects` keeps hiding test runs (ADR-0044). Code that reads runs must not treat a planned run as one that happened: grading, results and statistics ignore it, and it holds no attempts **[call]**.
- A new ADR records the run timing decisions: lazy status changes, the limit's inheritance ending on the run, the time zone's scope and the polling. `domain.md` stops calling the status names a proposal, `api-ui.md` gets the new settings, new `AC-xx` from AC-62 **[docs]**.

## Risks

- **Many submissions at one moment.** A deadline makes all participants submit within seconds, on one SQLite writer. The roadmap asks for an early load test. Verification: 50 simultaneous submissions at a deadline, all accepted within the 5 s margin **[docs]**, **[call]**.
- **Polling.** 50 pages every 30 s is under 2 requests per second, read only, and needs no writes unless a change is due **[call]**. The one reload at the start moment adds at most 50 page loads over 5 s **[call]**.
- **Time zone data.** The container may have no system zone database. The builder checks this in Docker, and adds a pinned `tzdata` with its reason if it is missing **[call]**.
- **Clock accuracy.** Depends on the server's clock (ADR-0025); the clock panel makes a wrong one visible **[docs]**, **[user]**.

## Left to the builder

- Where the due-change step sits, provided no path reads a stale status.
- How the remaining-time address is shaped, provided it reveals only the seconds remaining and needs the attempt token.
- Migration details, including `opened_at` no longer meaning the row's creation.
- Layout of the plan form, the countdown and the clock panel, following existing pages.

## Verification

- `make quality` and `make smoke` **[docs]**.
- Tests for each rule above, with time controlled in the tests.
- The load test from Risks.
- A walkthrough in the browser on a new quiz in the `kvizotron-browser` stack, without deleting its data **[user]**: plan, wait for the start, play with a short limit until automatic submission, move the deadline with a page open, end by deadline, restart, archive. Phone width, dark mode and Ukrainian included.
