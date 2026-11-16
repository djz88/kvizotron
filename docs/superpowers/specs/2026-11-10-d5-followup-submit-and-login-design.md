# D5 follow-up: submissions survive, login limit holds

Closes TD-022, TD-083, TD-084, TD-051, TD-018 (package A) and TD-090, TD-081, TD-041 (package B) before the tag `v1.0.0`.

## Why

D5 added request limits and a daily backup. The triage of the open technical debt after D5 [user: "A-B, and add the related ones"] found two groups that must not wait for 1.0:

- **A, a participant must not lose an answer.** The automatic submission at the deadline is repeated only after a network error (`app/api/assets/countdown.js`). A 5xx, a hanging connection and, since D5, a 429 leave the page waiting until the time has run out (TD-022, TD-083). A 429 is shown in the browser's language, not the form's (TD-084). An `IntegrityError` from `rewards.refresh` would be reported as a used submission key (TD-051). A number answer such as `1,000` is read as 1 and graded wrong without a word (TD-018).
- **B, the administration login limit has holes.** The window is checked before `authenticate()` and a failure is stored after it, so parallel guesses can pass (TD-090). Nothing limits one address that sprays many login names (TD-081). The public scoreboard answer depends on language and cookie but names neither in `Vary` (TD-041).

## Goals

1. **Login limit is atomic [call]**: a slot is reserved under the lock before `authenticate()` and given back when the login succeeds, so at most the limit of wrong guesses is possible in a window however many requests run in parallel.
2. **Address ceiling [call]**: a second login bucket, keyed by the address alone, counts failures of all names. Default 30 a minute, variable `KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE`.
3. **The automatic submission is repeated [call]** after a 5xx and a 429 as well, tells the participant it is waiting, and gives up only when the server answers something else. What this can save is limited by the server, which refuses any send after the limit (no grace, ADR-0025): a repeat saves the attempt only when a lost connection or a 5xx clears within the margin before the limit, and a later repeat at least brings the server's explicit verdict instead of silence. There is no request timeout: a hung request is neither cut nor repeated.
4. **429 in the form's language [call]**: the start and submit forms carry `?lang=` as `revision_status` already does.
5. **The cause of an `IntegrityError` is not hidden [call]**: only the submission key constraint becomes `submission_key_used`; anything else is raised.
6. **`1,000` does not pass silently [call]**: the number field warns, in the page's script, when the text is one separator and exactly three digits. The server still accepts and grades exactly what it does today.
7. **`Vary: Accept-Language, Cookie`** on the public scoreboard page and rows [call].
8. Every closed TD moves to the archive with `make tech-debt-resolve`.

## Non-goals

- Package C (jobs heartbeat, backup visibility, TD-068, TD-082, TD-085, TD-089) and package D (TD-021, TD-076, TD-015), and TD-047, TD-008: [user] not now.
- A shared limit store, limits in Caddy, a login lockout that survives a restart [docs: ADR-0030, ADR-0058].
- A retry of `start` after a 5xx: a repeated start would create a second attempt. Only the automatic submission is repeated (its key makes a repeat safe) [call]. TD-087 stays open and its text says so.
- A JavaScript test harness (TD-039). The scripts are tested as text in pytest and shown in the browser walkthrough [call].
- Any change to what the server accepts as a number answer, or to scoring.

## Anti-goals

- A login ceiling that locks the administration out of its own installation: the ceiling is per address and per minute, never per account, and a correct login never counts toward either bucket.
- 50 participants on one address blocked at the default values (unchanged from D5).
- A retry that writes twice: every repeat uses the same submission key, and the page stops after a fixed number of tries.
- A request timeout that cuts off a request the server is still storing.
- Passwords, login names beyond what ADR-0030 already keys on, or answers in logs.

## Behaviour

### 1. Login limit

- `rate_limit.try_acquire(bucket, key, now) -> bool` checks the window and, when there is room, appends the event in one lock acquisition. `rate_limit.release(bucket, key)` removes the newest event of that key (nothing when there is none). `allow` and `record` stay for the code and access-code buckets [call].
- The login view builds two keys, `name|address` (bucket `login`) and `address` (bucket `login_address`). It acquires both before calling `authenticate()`: if either refuses it releases what it took and answers 429 as today. A wrong login keeps the slots; a correct one releases both and logs in. [call]
- Two parallel wrong logins for the same name and address with a limit of 5 can never make the sixth through; the same holds for the ceiling. [docs: AC-129 stays true]
- Default of the ceiling is 30, ten times the per-name value so that a few administrators behind one address never meet it while a spray over many names does. The variable follows `_positive_int` like the other four [call].
- A ceiling hit is shown as the same 429 page and message as a per-name hit [call].

### 2. Automatic submission

- The page sends the answers when 5 seconds or less remain (4 to 5 seconds before the limit, the margin) and repeats that send with the same submission key. The server refuses any send after the limit with `attempt_expired` (`attempts._check_still_valid`, whole seconds, no grace, ADR-0025 and ADR-0010), so only a repeat that is sent inside the margin can still count. [call]
- Triggers for a repeat: `htmx:sendError` (as now), `htmx:responseError` with status 500 or more, and status 429. Any other answer stops the repeating. [call]
- Delays after a network error and a 5xx: 1, 1, 1.5, 3, 6 and 12 seconds (six repeats at most). The first three fall about 1, 2 and 3.5 seconds after the send, inside the 5 second margin; the later ones cannot be accepted and only bring the participant the server's verdict instead of silence. [call]
- A 429 carries `Retry-After`, which is always 60 seconds; the page waits it (at most 60), at most two times. That is always after the limit, so a 429 at the deadline is not recoverable by waiting; the repeat still shows the participant the verdict. This is recorded as a technical debt (TD-091). [call]
- There is no request timeout, for every quiz. A hung request is only ended by the browser or the network and is neither cut nor repeated (TD-092). A timeout was tried and removed: a cut request that the server still stores made the repeat get 410, and the participant was told the time had run out although the original committed. After a lost connection the same can happen rarely: the original is still being stored and a repeat after the limit gets `attempt_expired`; the attempt still counts. [call]
- While a repeat is pending the countdown box shows a translated line (cs/en/uk, en: "Sending your answers again.") in a live region; it disappears when an answer arrives or the repeating ends. [call]
- The server decides whether a send counts, exactly as now; nothing here is trusted.

### 3. Language of a refusal

- The `action` and `hx-post` of the start form and of the submit form get `?lang={{ locale }}`. A 429 on either is then shown in the language the participant chose on the page [call].

### 4. IntegrityError

- `attempts._store` turns an `IntegrityError` into `submission_key_used` only when it names the submission key constraint; others are raised. A test counts the queries of `rewards.refresh` for one participant so that a change in its cost shows [docs: TD-051].

### 5. Thousands separator

- In the page's script, when a number field holds an optional minus sign, one to three digits, one separator (`,` or `.`) and exactly three digits, a translated note appears under the field saying what the number is read as (the value with the separator the participant typed: `1,000` is read as 1, `2,500` as 2,5, `2.500` as 2.5), that a comma or a dot is a decimal sign, and to type a large number without a separator (en: "“{value}” is read as {read}: a comma or a dot is a decimal sign. Type a large number without a separator."). It never blocks sending. [call]

### 6. Vary

- The scoreboard page and its rows answer `Vary: Accept-Language, Cookie` in both branches of `_cache` [call].

## Constraints

- `deploy/compose.yaml` passes the new variable through (`NAME: ${NAME:-}`), `docs/configuration.md` lists it; `tests/test_configuration_docs.py` fails otherwise [docs].
- `app/api/play.py` and `app/domain/attempts.py` are at least MEDIUM, `deploy/compose.yaml` is LARGE; the work as a whole is LARGE (UI and domain together) [docs: profile].
- Single gunicorn process with threads; the limiter is safe for threads.
- Texts: public cs/en/uk, admin cs/en, `make messages` at the end. "Run", never "round".
- A new ADR (0060) refines ADR-0058 and gets a "Refined by" line there; `docs/_architecture/security.md` and `docs/deployment.md` follow.
- Do not touch the data or global settings of the user's `kvizotron-browser` stack; use a new quiz with prefix `d6`.

## Risks

- **The ceiling blocks a real administrator** behind a busy shared address: 30 failures a minute is far above honest typos, but a neighbour that keeps spraying keeps them refused for as long as it goes on. A restart clears it. Documented.
- **A retry storm**: the schedule is fixed and short, and the submit bucket (120 a minute per address) already bounds it. The repeats count toward that bucket too, up to 1 + 6 sends per participant, so a very large group on one address that hits the deadline together can meet 429 (TD-091).
- **A late repeat is refused**: the server rejects any send after the limit, so only the first three repeats, inside the 5 second margin, can save an attempt; the rest show the verdict. A 429 at the deadline is lost (TD-091), and a hung request is neither cut nor repeated (TD-092).
- **No JavaScript tests**: mitigated by text tests of the handlers and message keys and a browser run that forces a 429 and a 500 with Playwright route interception.

## Left to the builder

Names of constants and events inside `countdown.js` and the number script, where the note element lives in the templates, the wording of the two new messages, how many tests each behaviour needs, the exact constraint name test for the submission key.

## Verification

- Failing test first for each behaviour: parallel wrong logins never exceed the limit (threads), a correct login releases its slots, the ceiling counts across names and never counts a success, 429 with `Retry-After` for the ceiling, the forms carry `?lang=`, the 429 on submit is in the form's language, `IntegrityError` of another constraint is not `submission_key_used`, `Vary` on both scoreboard routes, the configuration test sees the new variable.
- `make quality`; `make smoke` (`SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543` while `kvizotron-browser` runs).
- Browser walkthrough with a new quiz `d6-…`: force a 500 and a 429 on the automatic submission with route interception and watch the answers arrive and the waiting line appear and go; `1,000`, `2,500` and `2.500` show the note with their own reading; a 429 on start in uk.
- A fresh reviewer of the whole branch, on the most capable model.
- `make tech-debt-check` after the eight TDs moved to the archive.
