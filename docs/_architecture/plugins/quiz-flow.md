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
  The participant can return in the same browser and continue until the valid deadline, at most 24 hours. Local state is
  not a trusted source of score, identity or times. See [ADR-0020](../adr/0020-browser-local-resume-untrusted.md).

## Behaviour

- One form holds all the attempt's questions and is submitted once. `assets/flow.js` shows them one at a time, with "Question 3 of 12" and a bar, or in pages of `page_size` questions (2 to 20, default 5, fixed on the attempt) with "Questions 6–10 of 12" and going back; all at once shows "Answered 3 of 12". Without JavaScript every mode is the one-page form.
- A new installation steps one question at a time with going back; migration 0015 keeps all at once on an installation that already has an admin or a quiz ([ADR-0052](../adr/0052-setting-groups-levels-and-step-default.md)). Answers after each question cannot go with pages or all at once.
- `QuizFlowPlugin.client_options(mode, moment)` tells the page what to offer: `step`, `back`, `check` and `pages`; the page size comes from the attempt. Without the module every quiz is one page.
- With `after_each`, `POST /a/<id>/check` returns one question's reveal and stores nothing. It refuses unless the attempt is in progress, its frozen moment allows it and the question was given. The page then locks the answer; a locked answer still goes in with the submission.
- Setting `local_resume` (`on` by default, `off`), declared in the manifest. While an attempt is open, `assets/resume.js` keeps its `attempt_token`, the answers, the step and an expiry in `localStorage` under a key for the run: never photos, a name or an e-mail. The copy ends with the attempt and within 24 hours, and is deleted on submission, on a refusal that ends the attempt and on expiry ([ADR-0050](../adr/0050-data-profile-and-local-resume.md)).
- "Continue" posts the token to `POST /r/<run>/resume`, which renders the attempt's own questions; the page fills in answers and step, drops what no longer fits and tells the participant to choose a photo again. "Start again" is offered only when the run's rules allow a new attempt.
- Resuming cannot change start time or assigned questions ([AC-11](../acceptance-criteria.md), [AC-80](../acceptance-criteria.md));
  the server re-validates everything on submit.
- "One by one without going back" is enforced only by the page; it is not a security boundary
  ([ADR-0035](../adr/0035-immediate-solutions-only-without-competition.md)).
