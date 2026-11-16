# Test add-ons — design

Date: 2026-11-12. Status: approved 2026-11-12. Project B of four (A quiz types — done, B test add-ons, C contest rules, D practice add-ons).

## Why

The quiz types of project A (Final test, Mock test) imitate an exam, but the application cannot say whether a participant passed, cannot allow a fixed number of attempts (only one or unlimited), counts only the first or the best attempt, and can reveal answers either during the run or never. Exams in Moodle, Canvas and Microsoft Forms have a pass mark, N attempts with a chosen kept score, and review after the exam closes. This project adds those four things and uses them in the quiz types.

## Task 0: deferred minors of project A

The plan starts with these fixes (commits `50ae781..0195e87`):

1. `quiz_types._plan`: a type with `resets_all` (Basic) makes no `ADJUSTABLE` adjustment; a clash with a run still refuses it.
2. `quiz_types._plan`: an `ADJUSTABLE` fix never overwrites a key the type sets itself; the clash stays and the type is refused (test with a made-up type).
3. `admin/_setting_row.html`: a field with the ▲ mark gets `aria-describedby="mark-<field>"`.
4. `admin/quiz_form.html`: the legend of the type choice is short ("Quiz type"); the sentence moves under it as a hint.
5. `admin_quizzes._with_type`: on `UnknownType` the quiz is still created and a notice says the type is no longer available and the quiz has no type.
6. `admin_forms.clash_message`: an unknown reason raises an error naming the reason.
7. Tests: order of several clashes, deviations with a disabled plugin, two modules setting the same key, the text for an unknown type.
8. `tests/api/test_admin_quiz_types.py` `unique_ids`: the regex does not match `data-id` (`(?<![\w-])id="…"`).

When this project changes the `QuizTypePlugin` contract, its attributes become read-only properties in the Protocol (the plugin is a frozen dataclass). Basic not reporting stored rows outside the catalogue stays as it is.

## What (the user's choices)

### Pass mark

- A new setting: the pass mark in **percent of the maximum score** (0–100; empty or 0 means no pass mark). Scope global → quiz; on a question it makes no sense, because it concerns the whole attempt (`scope_reason`). Default: no pass mark, so existing quizzes do not change.
- Passing is judged **separately for the attempt and for the participant** (user's choice):
  - **An attempt** passes on its own score as a percentage of its own maximum, against the run's pass mark. Since the pass mark is copied to the run, an attempt's mark never changes after submitting.
  - **A participant** passes on the **kept score** (below). With best, last or average it can change with each new attempt of theirs; nothing else changes it.
- The participant sees at the result (and on `/v/<token>`) the attempt's own line, "Passed ✓ — 78 % (pass mark 70 %)" or "Not passed — 62 % (pass mark 70 %)", and, when they have more than one submitted attempt, a line for the kept score: "Kept score: 80 % (best of 2) — Passed". No result without a pass mark changes.
- The admin sees: in the run's attempts table and the attempts export file each attempt's own mark; in the run statistics (share of participants who passed), the participants export file and the scoreboard (a mark at the row, public wherever the scoreboard is public) the participant's mark from the kept score.
- An attempt still waiting for grading (photo answers) has no mark yet ("waiting for grading"), and neither does a participant whose kept score depends on it (Claude's call).

### Number of attempts

- Under "Repeat attempts: allow" a new field **"At most attempts"** (0 = no limit, the default). "Forbid" stays one attempt. Existing quizzes do not change.
- Attempts are counted per browser, as "forbid" counts them today (the anonymous participant cookie); a test link does not count them, as it ignores "forbid" today (Claude's call).
- **Every started attempt counts** toward the limit, abandoned and expired ones too (user's choice): otherwise a participant could start, read the questions, leave and start again without limit. An unfinished attempt follows the existing "Unfinished attempt" setting (continue / used / submitted) as it does under "forbid" today; that setting now matters whenever the run limits attempts. "Forbid" is the limit 1 under the same rules.
- Like "forbid", a limit needs a participant, so it is refused with the data profile `none` where "forbid" is refused today (Claude's call, by analogy).
- A new setting **"More attempts after passing": yes / no** (default yes, Claude's call). With no, a participant whose kept score passed cannot start another attempt; one waiting for grading may (Claude's call). Without a pass mark it has no effect.
- Before the start the quiz page says how many attempts are left ("2 attempts left"). When none are left, the participant sees a message and their kept result (score and passed / not passed).

### Kept score

- `official_attempt` gets two new values besides first and best: **last** and **average**.
- Average is the average of the participant's submitted attempts and counts **everywhere the kept score counts today**: scoreboard, passed / not passed, reward thresholds and the draw. On the scoreboard, the time shown for an average is that of the last attempt (Claude's call).

### Changing these during a run

- The pass mark, at most attempts, more attempts after passing and the kept score are **copied to the run** when it is planned or opened, like the participant rules and the scoreboard settings today. The run plan shows them and lets the admin change them on a planned run; an open run keeps them. A change of settings never changes a result after the fact; only the participant's own new attempt can change their kept score.

### Reveal after the run closes

- `reveal_moment` gets a new value **after the run closes**. During the run the result shows no answers; once the run is closed or archived, the participant's private result link (`/v/<token>`) shows them at the chosen `reveal_level`.
- The result page right after submitting says: "You will see the correct answers at this link after the run ends (date)" — the deadline when the run has one, otherwise without a date.
- It needs stored answers: with the data profile `none` or `score` it is a clash — the settings forms refuse it with a message, and a quiz type adjusts the profile (`ADJUSTABLE`).
- The data profile is copied to the run, so the clash is also checked against runs (Claude's call), like `RUN_BOARD` and `RUN_REWARDS` today: the quiz settings refuse "after the run closes" while a planned or open run has profile `none` or `score`, and planning or opening a run with such a profile is refused while the quiz reveals after close. A quiz type with this clash is refused, as in project A.
- It needs the participant to be allowed to see their answers: "after the run closes" requires `answers_visibility` `participant` or `public` and never overrides it (Claude's call: the visibility rules stay the single place that decides, `app/domain/visibility.py`). With `admins` it is a clash the settings forms refuse; a quiz type adjusts visibility to `participant` (`ADJUSTABLE`). Without this the private link would not exist and the note would promise nothing.
- The answers are shown once the run is closed or archived **and** no late submission can still be accepted: answers are shown from `closed_at` plus 10 minutes (`attempts.LATE_UPLOAD_WINDOW`, the window a late photo upload is accepted, moved from `play.LATE_PHOTO_WINDOW`), so nobody still submitting sees them (Claude's call).
- Like the other reveal values it is read live from the quiz (TD-101), not copied to the run (Claude's call).

### Quiz types

| Setting | Final test | Mock test | Exam with a resit (new) |
|---|---|---|---|
| pass mark | 70 | 70 | 70 |
| repeat_attempts | forbid | allow | allow |
| at most attempts | – | 0 | 2 |
| official_attempt | first | – | best |
| reveal_moment | never | at_end | after the run closes |
| reveal_level | – | explanations | explanations |
| data_profile | answers | score | answers |
| answers_visibility | – | – | participant |

The other columns of the new type follow Final test (navigation `step_no_back`, shuffle on, time limit 30, ask name required at start, duplicate names allow, scoreboard hidden, sources off). Names: Zkouška s opravným pokusem / Exam with a resit; uk through the catalogue. Practice, Contest, Pub quiz and Basic set none of the new keys.

## Not in scope

- Counting attempts by e-mail or name.
- A result that changes when the pass mark changes later.
- Copying the reveal values to the run (TD-101).
- The add-ons of projects C and D.

## Left to the builder

- Setting keys, labels and groups (`kvizotron-add-setting`); where the copied values live on the run (`participant_rules_json`, `results_json`, or a new field with a migration).
- How average fits `results.official_attempt`, which returns one attempt today, and every place that reads it (scoreboard, rewards, draws, export, statistics).
- The clash rules for reveal after close (data profile, answers visibility, runs) in `app/domain/setting_rules.py`, with their messages in `admin_forms`.
- How the attempt count reaches the participant policy: `ParticipantPolicyPlugin.on_start` takes `finished: bool` today, so counting attempts is a contract change (ADR and contract tests); `attempts._check_not_played` and the start page's "attempts left" follow it.
- Whether an attempt's pass mark is stored on `Attempt` at submit or computed from the run's copied pass mark (both give a mark that never changes).
- Acceptance criteria (next free AC), ADR for the kept score average if it changes ADR-0026/ADR-0051/ADR-0053 behaviour, docs and cs/uk strings.
