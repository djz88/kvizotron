# Plugin: quiz flow

| | |
|---|---|
| Contract | `QuizFlowPlugin` |
| Package | `app/plugins/quiz_flow/` |
| Stage | B (navigation modes), C (local resume) |

## Requirements

- `FR-17` Admin chooses quiz navigation: all questions at once, one by one with going back, one by
  one without going back. The setting must match the capabilities of the question-type plugins.
- `FR-22` Unsubmitted answers may be stored briefly **locally in the browser** if the admin allows it.
  The participant can return in the same browser and continue until the valid deadline. Local state is
  not a trusted source of score, identity or times. See [ADR-0020](../adr/0020-browser-local-resume-untrusted.md).

## Behaviour

- One form holds all the attempt's questions and is submitted once. `assets/flow.js` shows them one at a time, with "Question 3 of 12" and a bar; all at once shows "Answered 3 of 12". Without JavaScript every mode is the one-page form.
- `QuizFlowPlugin.client_options(mode, moment)` tells the page what to offer. Without the module every quiz is one page.
- With `after_each`, `POST /a/<id>/check` returns one question's reveal and stores nothing. It refuses unless the attempt is in progress, its frozen moment allows it and the question was given. The page then locks the answer; a locked answer still goes in with the submission.
- Local storage keeps answers + `attempt_token` with a short TTL and minimum personal data.
- Images are not kept in browser storage: after resuming, the participant selects the image again and
  the page says so.
- Resuming cannot change start time or assigned questions ([AC-11](../acceptance-criteria.md));
  the server re-validates everything on submit.
- "One by one without going back" is enforced only by the page; it is not a security boundary
  ([ADR-0035](../adr/0035-immediate-solutions-only-without-competition.md)).
