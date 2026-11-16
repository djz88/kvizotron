---
status: accepted
date: 2026-11-10
---

# ADR-0060: Login slots reserved before the password is checked, an address ceiling, and a repeated automatic submission

## Context and Problem Statement

[ADR-0058](0058-rate-limit-buckets.md) limits failed administration logins per name and address, and left five loose ends that were recorded as technical debt before the tag `v1.0.0`:

* The login view checked the window, called `authenticate()` and stored a failure afterwards. With gunicorn's threads, parallel wrong guesses for one name and address could all pass the check first, so a few more than the limit slipped through each minute (TD-090).
* One address could try the limit of wrong passwords for every name in turn; nothing limited the address as a whole (TD-081).
* The automatic submission at the deadline was repeated only after a lost connection. A 5xx, a connection that hangs and, since D5, a 429 left the page waiting until the time had run out and the attempt was lost (TD-022, TD-083).
* A refusal (429) of the start or the submit was shown in the browser's language, not in the language of the form the participant was using (TD-084).
* A number answer such as `1,000` is read as one and graded wrong without a word (TD-018).

Two smaller fixes belong to the same change and need no decision: the public scoreboard answers `Vary: Accept-Language, Cookie` because its language and its "you" mark depend on both (TD-041), and `attempts._store` names a unique failure `submission_key_used` only when it is the submission key constraint, so an unrelated `IntegrityError` is not hidden behind it (TD-051).

## Decision Drivers

* A participant must not lose an answer to a hiccup of the server or the network
* A repeat must never write twice
* The administration must never be locked out of its own installation; a correct login never counts
* About 50 people behind one address are never refused at the default values ([ADR-0030](0030-rate-limit-thresholds.md))
* One process with threads and no extra service ([ADR-0058](0058-rate-limit-buckets.md))
* The server decides what is accepted and how it is graded; nothing the page does changes that

## Considered Options

* Login: reserve a slot before `authenticate()` and give it back on success, against checking first and recording after
* Login: a second bucket keyed by the address alone, against a lockout per account, against nothing more
* Repeating the automatic submission only, against repeating `start` as well
* A fixed schedule of repeats with a `Retry-After` rule for 429, against an endless loop
* The language of a refusal from the form's address, against a cookie or a header the page sets
* `1,000`: a note that never blocks, against refusing the answer or reading it as a thousand

## Decision Outcome

### Login: reserve, then release

`rate_limit.try_acquire(bucket, key, now)` looks at the window and, when there is room, appends the event, all under one lock acquisition. `rate_limit.release(bucket, key)` removes the newest event of that key and does nothing when there is none. The login view builds two keys, `name|address` for the bucket `login` and `address` for the bucket `login_address`, and takes both before it calls `authenticate()`. If either refuses it gives back what it took and answers 429 as before. A wrong login keeps its slots; a correct one releases both and logs in, so a correct login still counts toward nothing.

With a limit of 5, two parallel wrong logins can no longer make a sixth guess through, whatever the number of threads. The old pair `allow` and `record` stays for the `code` bucket and is still used by `play._limited` for the `submit` and `start` buckets, so those keep the same check-then-record race: parallel requests can all pass the check before any is recorded. That is acceptable there because they are volume limits on writes, not limits on guessing: an overshoot is bounded by the 8 gunicorn threads, a few requests over 120 or 300 a minute, and nothing is gained by it. A guess limit has to hold exactly, a volume limit only roughly.

Considered and rejected: keeping check-then-record and adding a second check after `authenticate()`, which still lets parallel guesses all reach `authenticate()` (the expensive and guessable step) before any of them is counted.

### Login: a ceiling per address

The bucket `login_address` counts failed logins of all names from one address. The default is 30 a minute, variable `KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE`, read like the other four limits (a positive integer, an empty value means the default). It is first-class: Compose passes it through and [configuration.md](../../configuration.md) lists it.

Why 30: ten times the per-name value. A few administrators behind one office address make a typo or two a minute and never come near it, while a spray of guesses over many names reaches it in the first seconds. It is a choice, not a measurement: it bounds a spray over many names to 30 guesses a minute. A hit is shown as the same 429 page and message as a per-name hit.

The ceiling is per address and per minute, never per account, so it cannot lock a named administrator out for everybody; it clears when the window ends, and when the process restarts.

### Only the automatic submission is repeated

The automatic submission at the deadline carries a submission key, and the server stores the answers once for one key, so a repeat of it cannot write twice. `start` has no such key: a repeat of a start whose answer was lost would create a second attempt and a second row, and it is the very thing the start limit exists to bound ([ADR-0058](0058-rate-limit-buckets.md)). So the page repeats the automatic submission and leaves `start` as it was; a reset of a start still shows as an error and the participant presses the button again. [TD-087](../TECH_DEBT.md) stays open for that.

### The schedule

The server refuses any send after the limit with `attempt_expired` (`attempts._check_still_valid`, whole seconds, no grace; [ADR-0025](0025-deadline-boundary-second-semantics.md), [ADR-0010](0010-strict-server-side-deadline.md)), and this ADR does not change that. `countdown.js` sends the answers when 5 seconds or less remain (4 to 5 seconds before the limit, the margin) and repeats that send after `htmx:sendError` (a lost connection) and after `htmx:responseError` with status 500 or more. The waits are 1, 1, 1.5, 3, 6 and 12 seconds, so at most six repeats. The first three fall about 1, 2 and 3.5 seconds after the send, inside the margin, and can still be accepted; the later ones can only bring the participant the server's explicit verdict instead of silence. After a 429 it waits the `Retry-After` the answer carries, at least one and at most 60 seconds, 60 when the header is missing, and does so at most twice. `Retry-After` is always 60 seconds, so that repeat always lands after the limit: a 429 at the deadline is not recoverable by waiting ([TD-091](../TECH_DEBT.md)). Any other answer (a 200, a 4xx that is not 429) stops the repeating; the page does not guess what the server meant.

The automatic submission has no request timeout, and a request that hangs is neither cut nor repeated; the browser or the network ends it ([TD-092](../TECH_DEBT.md)). A timeout was tried and removed: a cut request that the server was still storing made the repeat meet a stored attempt (410), and the participant was told the time had run out although the original committed. This holds for every quiz, with or without a photo question. Each repeat is the same `requestSubmit()` as the first send, so it reuses the key. While a repeat is pending the countdown box shows a translated line (cs, en, uk; en "Sending your answers again.") in a live region; it goes when an answer arrives or the repeating ends. The submit bucket (120 a minute per address) bounds a storm, and the repeats count toward it: each participant of a shared address sends once and may send up to six times more, so a very large group that hits the deadline together on one address can meet 429 ([TD-091](../TECH_DEBT.md)).

`resume.js` accepts a `?query` on the submit and resume addresses so that the saved copy is still dropped after a submit whose address carries `?lang`.

### The language of a refusal

The `action` and the `hx-post` of the start form and of the submit form carry `?lang=<locale>`, as `revision_status` already does; the submit form of the administration preview does not, because that address would switch the administrator's own language. A refusal then names the language the participant chose on the page, not the one the browser sends.

### Why `1,000` only warns

A comma is a decimal sign in cs and uk and a thousands sign in en, and the server already accepts both a comma and a dot as the decimal separator ([question-types.md](../plugins/question-types.md)). Changing what is accepted would regrade answers and make the page disagree with the server. So `number.js` shows a translated note under the field when the text is an optional minus sign, one to three digits, one separator and exactly three digits: the note says what the value is read as (`1,000` is 1, `2,500` is 2.5) and to type a large number without a separator. It never blocks the sending and the server accepts and grades exactly what it did.

## Consequences

* Good: at most the limit of wrong guesses is possible for a name and address in a window, and at most the ceiling for an address, however many requests run in parallel.
* Good: a repeat can save an attempt when a lost connection or a 5xx clears within about 3.5 seconds of the send, inside the margin before the limit; later repeats only bring the participant the server's explicit verdict instead of silence, and the participant sees that the answers are being sent again.
* Bad: a 429 at the deadline is not recoverable by waiting, because `Retry-After` (60 seconds) is always after the limit; and the repeats raise the submit volume of a shared address (up to 1 + 6 sends per participant), so 429s can follow when a very large group hits the deadline together ([TD-091](../TECH_DEBT.md)).
* Bad: a hung request at the deadline is neither cut nor repeated ([TD-092](../TECH_DEBT.md)).
* Bad: after a lost connection the original send may still be being stored, and a repeat that arrives after the limit then gets `attempt_expired` although the attempt was stored. This is rare: the participant is told the time ran out, and the attempt still counts.
* Good: a refusal is in the language of the form, and a number such as `1,000` does not pass silently.
* Bad: the ceiling counts an address, so a shared address where many wrong logins happen in a minute can lock its own administrators out, and a neighbour that keeps making 30 wrong logins a minute keeps them refused for as long as the spray goes on. 30 is far above honest typos; a restart clears it (the counters live in process memory, [ADR-0058](0058-rate-limit-buckets.md)).
* Bad: a correct login from an address whose buckets are full is refused too, because the check comes before the password is looked at.
* Bad: a reset of `start` is still not repeated ([TD-087](../TECH_DEBT.md)).
* Bad: the scripts have no JavaScript test harness ([TD-039](../TECH_DEBT.md)); they are checked as text in pytest and in a browser walkthrough.

### Confirmation

`tests/api/test_login_limit.py` (`test_parallel_wrong_logins_never_exceed_the_limit`, `test_one_address_spraying_many_names_hits_the_ceiling`) and `tests/api/test_rate_limit.py` (`test_try_acquire_reserves_and_refuses_past_the_limit`, `test_release_gives_back_the_newest_slot`, `test_try_acquire_never_exceeds_the_limit_under_threads`; [AC-140](../acceptance-criteria.md)), `tests/api/test_countdown_script.py`, `tests/api/test_play_limits.py` and `tests/api/test_local_resume.py` ([AC-141](../acceptance-criteria.md)), `tests/api/test_scoreboard_page.py` and `tests/api/test_number_script.py` ([AC-142](../acceptance-criteria.md)).

## More Information

Refines [ADR-0058](0058-rate-limit-buckets.md) and, through it, [ADR-0030](0030-rate-limit-thresholds.md). Variable: [configuration.md](../../configuration.md).
