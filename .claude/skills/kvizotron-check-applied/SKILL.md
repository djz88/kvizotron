---
name: kvizotron-check-applied
description: Use when Kvízotron work looks finished and before saying so, before review-roles, before a merge, or when asked whether everything from a plan or spec was really applied and connected.
---

# Check that everything is applied and wired

It answers one question: **is what was meant to be created really in the code, and can it be reached?** It is done by running, not by reading.

| Here | In `review-roles` |
|---|---|
| Facts from commands: a file changed, a URL leads to a page, someone calls the function | Judgement from reading: is it well designed, safe, understandable |

Do not judge code quality here. Pass the result to `review-roles` as input so the roles do not do it again.

## 1. Plan against git

```bash
make plan-check plan=docs/superpowers/plans/<plan>.md base=main
```

- "Plan names it, it did not change": for each file write why, or add the change. Do not pass over it silently.
- "Changed, not committed": what is not in a commit is not done.
- "The plan does not name it": one sentence for each. It is not an error, but an unplanned change must have a reason.

Work without a plan skips this step, and the report says so.

The check sees only the files the plan names. It will not find a lost change in a file outside the plan, and it does not verify that a change in a file is correct.

## 2. Wiring

```bash
make wiring
```

It guards modules, templates, URLs, scripts, styles, settings, events and the login to the administration. The list of exceptions in `tests/test_wiring.py` only shrinks. Do not add a new entry there to make the test pass; fix the wiring.

## 3. Spec against reality

List a table with a row for every goal and every behaviour bullet from the spec:

| Requirement | Input (URL, command) | How verified | Evidence |
|---|---|---|---|

Evidence is one of these:

- the name of a test that goes through a real URL and would fail without that change,
- a line from `make smoke`,
- a screenshot from `kvizotron-browser-walkthrough`.

A test of a function is not evidence of wiring: a function can work and nobody calls it. If the change touches several layers, **REQUIRED SUB-SKILL:** `kvizotron-check-integration`; its table is the evidence for the affected rows.

Write a row without evidence as **unverified**. It is not done until you fill it in or the user decides otherwise.

## 4. Running outside tests

| Change | Verify |
|---|---|
| Migration, dependency, Docker, new module, new file in `app/api/assets/` | `make smoke` on a clean build |
| Look, script, HTMX, translation | `kvizotron-browser-walkthrough` |
| Deadlines, concurrency | `tools/load_deadline.py` or a test with controlled time |

When `kvizotron-browser` is running, run smoke with `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543`.

## 5. Output

The results of steps 1 to 4 with the command output and the table from step 3. At the end a list of **unverified**, even if it is empty.
