# Privacy & Data Retention

Applies to the Kvízotron v1.0 architecture. This is not a legal assessment of any specific
processing; the operator determines the legal basis for their deployment.

## Requirements

- `FR-32` Per run, admin configures collection and presentation of public name/nickname and e-mail
  (`DISABLED`, `OPTIONAL`, `REQUIRED` for e-mail). Data are requested at the end, before submission,
  or before the start, as the admin chooses; the end is the default. Validation happens on the server.
- `FR-33` Admin chooses a data-retention profile: aggregate score only; score + individual answers;
  detailed times and history. Settings respect functional dependencies. E-mail is stored only if it is
  actually required for a declared purpose.
- `FR-34` Retention per run: e.g. 30/90/365 days or permanent; periodic cleanup anonymises or deletes
  matching personal records per policy. Restarting a run does not bypass retention. Admin can delete
  data selectively. Backups must have their own limited retention so that deleted personal data are
  not restored without reason.
- `FR-35` The participant receives basic information about data processing and a link to the privacy
  policy. The policy must describe purpose, controller, retention period and contact; the legal basis
  is determined by the specific deployment. It must not be assumed that consent is required for all
  purposes.

## Functional dependencies of retention profiles

| Feature | Requires stored |
|---|---|
| Public scoreboard | attempt score + participant (nickname) |
| Draw / rewards | attempt score + participant (+ contact if winner must be reached) |
| Attempt limit across sessions | participant key hash + attempt |
| Per-question statistics | individual answers |
| Duration-based ranking | detailed times |
| Image answer type (FR-45) | individual answers + uploaded images |
| None of the above (stateless mode) | nothing — score only shown to participant (FR-31) |

Admin UI shows these dependencies and the retention setting **before** activating data storage.
The table is a summary; the profile below decides what is kept. The scoreboard, draws, statistics and
export that need more than a profile keeps refuse to run on it from C4, C5 and D2.

## Data profile and retention period

A run keeps what its data profile says ([ADR-0050](_architecture/adr/0050-data-profile-and-local-resume.md)). The profile replaces `store_answers`, is inherited global → quiz, copied onto the run when it is planned or opened, and fixed once the run opens.

| Profile | Kept after submission |
|---|---|
| `none` | Nothing per attempt; the run keeps a count of submitted attempts |
| `score` (default) | Score, submission time, and answers a person must grade, photos included |
| `answers` | As `score`, plus every answered question |
| `detailed` | As `answers`, plus the attempt's duration |

- Under `none` the participant sees a score and nothing remains: the attempt row is deleted at submission with the attempts it replaced, and no private result link exists. The form refuses `none` with repeating forbidden, a name or e-mail asked, visible answers or a photo question. A test run follows the live profile and does not count.
- The period (30, 90 or 180 days, 1 year, 3 years or permanent, 90 days by default) is counted from the run's close and stays editable on the run. It is only recorded: no job deletes anything until D3. The public privacy page shows the global default, says a quiz may set another, and says deletion comes in a later version.

## Rules

- Images a quiz loads from their own server (`external_image_mode`, off by default) let that server
  see the participant's IP address. Copies kept by the installation do not. The public privacy page
  says so.
- Images uploaded by participants may show people and are treated as personal data: visible only to
  admins, EXIF removed, deleted with the answers under the run's retention.
- No marketing consent and no e-mail mailing module in v1.0.
- E-mail never published, never sent to external analytics.
- Draw and audit logs minimise PII (audit details also hold the eligible count and the fingerprint of the eligible set, no personal data); on retention expiry or erasure request personal data are deleted
  or pseudonymised while non-personal draw metadata may stay (FR-39, [plugins/drawings.md](_architecture/plugins/drawings.md)).
- A draw record keeps, next to each participant link, a pseudonym: a salted HMAC-SHA256 of the
  participant id with the server secret. Draw audit records and `audit_event` hold only pseudonyms and
  ids of rules and draws, never a name, an e-mail or a reason typed by the admin about an entitlement
  ([ADR-0053](_architecture/adr/0053-rewards-tiers-alternates-and-draw-history.md)).
- Backups are kept for 30 days by default (configurable).
- Exports and backups **MUST** be verified not to bypass retention rules.
- Implementation: [providers/retention.md](_architecture/providers/retention.md);
  decision: [ADR-0012](_architecture/adr/0012-configurable-retention-profiles-and-stateless-mode.md);
  default period: [ADR-0029](_architecture/adr/0029-default-retention.md).

## Stored answers and photos

Answers are stored only as a quiz's data profile says ([ADR-0046](_architecture/adr/0046-stored-answers-and-who-sees-them.md)). By default only what a person grades is kept, photos included; the profiles `answers` and `detailed` keep each answered question (they replace `store_answers=all`).

- Who sees answers: `answers_visibility` chooses admins, the participant through a private link, or everyone on a walkthrough after the run ends, without naming anyone.
- Who sees a photo: `photo_visibility` ([ADR-0047](_architecture/adr/0047-image-answer-photo-visibility.md)). Public needs that level, approval of that photo, and a notice shown before upload.
- A photo is rebuilt from pixels, so EXIF and any other metadata are gone. It stays until an admin deletes it, or its test link is deleted. Automatic cleanup arrives with D3.
- The private link has no end date until D3. Anyone holding it can open it, so the result page asks to save it.
- While an attempt is unfinished and the quiz allows it (`local_resume`, on by default), the browser keeps its token, the entered answers, the step and an expiry in `localStorage`, per run: no photo, name or e-mail. The copy is deleted on submission or when the attempt ends, and is not kept past its expiry of 24 hours at most: the next page of this site that you open removes an expired copy. Another person on the same browser could see those answers meanwhile; the quiz page says so, and an admin can turn it off. The copy decides nothing: the server re-checks every answer and keeps the start and questions.
- The participant's browser keeps that link in `localStorage`, per quiz, on that device. Nothing about it is sent anywhere. Without a script only the link itself works.

## Participants, names and e-mails

How a run identifies people and what it keeps ([ADR-0049](_architecture/adr/0049-participants-and-access-code.md)):

- A run that forbids repeating, asks for a name or e-mail, or shows a public scoreboard sets the cookie `kvz_p_<run>` with a random key ([ADR-0051](_architecture/adr/0051-scoreboard-participants-and-official-attempt.md)). The database keeps only an HMAC of that key with the run id, so runs cannot be linked through it. Other runs set no cookie and store no participant.
- A run with an access code sets the cookie `kvz_c_<run>` after a correct code. It says only that this browser entered the current code, and holds neither the code nor any identity.
- E-mails are shown only in the logged-in administration, on the run's page. Nicknames are shown there too, and on the run's public scoreboard when the admin turns it on: during the run they can be replaced by anonymous labels, and a participant without a nickname is shown with an anonymous label or left out. The scoreboard never shows an e-mail or an internal id. They are not written to logs or audit records, and pages that show them back to the participant are not cached.
- A run with reward rules sets the cookie too, so one browser holds one set of entitlements. A winner's e-mail is shown only on the run's rewards and draw pages in the administration; the system sends no e-mail. Published draw winners appear on the run's public scoreboard page by nickname, or by the anonymous label when there is none. A participant's own rewards and claim instructions are shown only on their result page and private result link.
- They are kept until retention arrives in D3; until then there is no deletion in the administration.
