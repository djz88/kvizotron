---
name: kvizotron-browser-walkthrough
description: Use when a Kvízotron change affects what a person sees or clicks (templates, CSS, JavaScript, HTMX, translations) and needs checking in a real browser, or when using or rebuilding the kvizotron-browser Docker stack.
---

# Browser walkthrough

Tests see HTML, not the browser: CSS, JavaScript and the inheritance of `hx-*` are verified only by this walkthrough.

## The stack's data stays

The `kvizotron-browser` stack (`https://localhost:18443`) is also used by the user.

- Volumes are not deleted and the stack is not created again. For every check create a **new quiz** with a milestone prefix, for example `c2-`.
- Do not change its global settings. Need a different value? Use an override on your new quiz.
- Leave finished quizzes alone after the check, do not offer to clean up.
- Deleting volumes is also stopped by the hook `.claude/hooks/guard_docker_volumes.py`.

## Build from the current code

The secret key is taken from the running container so that logins and tokens stay valid. Never print it.

```bash
KVZ_SECRET_KEY="$(docker inspect kvizotron-browser-app-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^KVZ_SECRET_KEY=//p')" \
KVZ_DOMAIN=localhost KVZ_HTTP_PORT=18080 KVZ_HTTPS_PORT=18443 \
docker compose -p kvizotron-browser -f deploy/compose.yaml up -d --build
```

When the stack is not running there is nowhere to take the key from: ask the user.

## Script

Load `mcp__plugin_playwright_playwright__browser_run_code_unsafe` and start from `walk.template.js` next to this file. Fill in `BASE`, `ADMIN_STATE` and `SHOTS` and write the steps at the marked place. Save the edited copy to `.playwright-mcp/`, which is outside git, and run it through the `filename` parameter; the tool refuses it from anywhere else.

The login is in a saved-state file in `.playwright-mcp/`, which is outside git. When it has expired, the page redirects to `login`: ask the user for the password, do not write it into the script or the output.

## What to go through

| View | Setting |
|---|---|
| Main | 1280 px, light, `cs` |
| Phone | 390 px, dark, `uk` |
| Keyboard | the main path only with Tab and Enter |

For each view:

- Open the screenshot and look at it. The page text is not enough, you cannot tell missing CSS from it.
- The `errs` field from the template must be empty.
- Also try the participant's path in a clean context without logging in.
- For a time-dependent change, expect to wait for the real moment, or set it as close as possible.

## Common script mistakes

| Mistake | Correct |
|---|---|
| `button[type=submit]` clicks the form in the header | `form:has([name=starts_at]) button[type=submit]` |
| A click without waiting, the old page is read | `await page.waitForLoadState()` after every submit |
| Navigating to the page of a quiz nobody started | First start a run and verify it is open |

Before you blame the app, verify that the script clicked what you meant: print the URL and the start of `main`.

## Report

Write what you went through and what you did not. Mark what you did not see in the browser as verified only by tests. Fix a finding in the app with a test that fails first.
