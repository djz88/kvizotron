# Privacy & Data Retention

Applies to the Kvízotron v1.0 architecture. This is not a legal assessment of any specific
processing; the operator determines the legal basis for their deployment.

## Requirements

- `FR-32` Per run, admin configures collection and presentation of public name/nickname and e-mail
  (`DISABLED`, `OPTIONAL`, `REQUIRED` for e-mail). Data are requested at the end, before submission,
  if required by settings. Validation happens on the server.
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
(Table is a documentation summary of FR-31/FR-33 dependencies; exact matrix finalised in Stage C.)

## Rules

- Images a quiz loads from their own server (`external_image_mode`, off by default) let that server
  see the participant's IP address. Copies kept by the installation do not. The public privacy page
  says so.
- Images uploaded by participants may show people and are treated as personal data: visible only to
  admins, EXIF removed, deleted with the answers under the run's retention.
- No marketing consent and no e-mail mailing module in v1.0.
- E-mail never published, never sent to external analytics.
- Draw and audit logs minimise PII; on retention expiry or erasure request personal data are deleted
  or pseudonymised while non-personal draw metadata may stay (FR-39, [plugins/drawing.md](_architecture/plugins/drawing.md)).
- Backups are kept for 30 days by default (configurable).
- Exports and backups **MUST** be verified not to bypass retention rules.
- Implementation: [providers/retention.md](_architecture/providers/retention.md);
  decision: [ADR-0012](_architecture/adr/0012-configurable-retention-profiles-and-stateless-mode.md);
  default period: [ADR-0029](_architecture/adr/0029-default-retention.md).

## Stored answers and photos

Answers are stored only as a quiz's settings say ([ADR-0046](_architecture/adr/0046-stored-answers-and-who-sees-them.md)). By default only photos are kept, because a person grades them; `store_answers=all` keeps each answered question.

- Who sees answers: `answers_visibility` chooses admins, the participant through a private link, or everyone on a walkthrough after the run ends, without naming anyone.
- Who sees a photo: `photo_visibility` ([ADR-0047](_architecture/adr/0047-image-answer-photo-visibility.md)). Public needs that level, approval of that photo, and a notice shown before upload.
- A photo is rebuilt from pixels, so EXIF and any other metadata are gone. It stays until an admin deletes it, or its test link is deleted. Automatic cleanup arrives with D3.
- The private link has no end date until D3. Anyone holding it can open it, so the result page asks to save it.
- The participant's browser keeps that link in `localStorage`, per quiz, on that device. Nothing about it is sent anywhere. Without a script only the link itself works.
