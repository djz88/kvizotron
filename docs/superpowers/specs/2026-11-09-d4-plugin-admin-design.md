# D4 Plugin admin: enabling modules, what they set, and where a value differs

Marks: **[user]** decided by the user in this design, **[docs]** already in `docs/_architecture`, **[call]** the designer's choice, open to correction.

## Why

The kernel can enable and disable a plugin, check dependencies and refuse a plugin in use, but only through `manage.py modules`. An organiser has no way to see which modules exist, to turn a question type off, or to find out why a change is refused. Settings are spread over the global, quiz and question pages, so nobody can see where a quiz departs from the global value. D4 gives that one page. It also closes the gaps that make disabling unsafe today: some plugins can be disabled although the application cannot work without them, and several pages raise an unhandled error once a plugin is off.

## Goals

- An admin sees every installed module with its kind, version and state. **[docs]**
- An admin can enable or disable a plugin, and is told in plain words why a change is refused. **[docs]**
- For each module, an admin sees the settings it adds, where each is changed, and in which quiz or question the value differs from the global one. **[user]**
- After a plugin is disabled, every page still answers: nothing ends in an error page. **[docs]**

## Non-goals

- Enabling a plugin for one quiz only. Disabling applies to the whole installation; the manifests' `activation_scope` stays unused. **[user]**
- Editing a setting's value on the plugin pages. Each setting keeps its one place. **[user]**
- The table `plugin_configuration` and any per-module configuration form. No module needs one; the first that does adds it. **[user]** **[docs]**
- A command that removes a module and reverses its migrations. Recorded in `TECH_DEBT.md`. **[user]**
- Installing modules from the UI, or changing a provider. **[docs]**
- Roles among admins. There are none in the application. **[call]**
- Overrides inside question banks. They are not part of a quiz until drawn. **[call]**

## Anti-goals

- A disabled plugin that makes a page of a past or running quiz answer 500. **[docs]**
- A second place to change a setting. **[user]**
- A kernel that knows what a quiz is: it must not import `app/domain`. **[docs]**
- A rule that exists in the page but not in `manage.py modules`. **[call]**

## Behaviour

### The list

A new page, **Modules** (`/admin/plugins`), in the admin navigation, shows all modules, plugins first. Each row has the translated name, kind, version, state and a link to its detail. **[call]**

- A plugin that can be switched has a button "Disable" or "Enable". The change applies at once, needs no confirmation because it can be undone, and is audited with the admin as actor (`plugin.enabled`, `plugin.disabled`, already written by the kernel). **[call]**
- A provider shows "changes on restart" and no button. **[docs]**
- A plugin that cannot be disabled now shows the short reason in the row instead of a button. **[call]**

### What can be disabled

- Switchable: the five question types, `rewards.threshold`, `drawings.manual`. **[user]**
- `theme.default`: only while another theme is enabled. The guard `last_theme_usage` exists and stays, its reason gets translated. **[user]** **[docs]**
- Always locked, because the application asks for them by name: `flow.basic`, `participants.basic`, `results.local`, `scoring.basic`. **[user]** These are not protected today and `manage.py modules disable` succeeds on them; after D4 it refuses. **[call]** An installation where one of them is already disabled keeps running as it does now and can enable it. **[call]**
- Enabling is refused while a capability the plugin requires has no enabled provider; disabling is refused while another enabled module requires what only this plugin provides. Already in `lifecycle`; D4 shows the reason. **[docs]**

### Refusal because of use

- A plugin is in use, and cannot be disabled, when a scheduled or open run plays its question type or scoring strategy, or when a live run's reward rule calls it. Open runs and reward rules are checked today; a scheduled run is new, otherwise it would open later with a disabled type. **[call]**
- A refusal on the detail page lists each quiz and run with a link to it. A run with a test link is named as such. **[call]**
- Reasons are shown in the admin's language; `manage.py` prints the same reasons. **[call]**

### Detail of a module

`/admin/plugins/<module id>` shows the description, what the module requires and which enabled modules depend on it, the state and the reason for any lock, and its settings. **[call]**

For each setting declared in the manifest: its label, the global value by its translated label, and a link to the page where it is changed. **[user]** Below it, "Different elsewhere": every quiz with a quiz override that differs from the global value, and every question whose own value differs from the global value, by quiz and question number, each linking to the place it is set. **[user]**

- The comparison is against the global value, not the value of the quiz. **[user]** The global value is the resolved one (`settings.resolve(key)`), so an unset global counts as the default. **[call]**
- Only the levels a setting declares in `scopes` are examined: a setting with `["global", "quiz"]` has no question rows, and a global-only setting has no "Different elsewhere" section at all. **[call]**
- Links are decided by level, not by the manifest: the global value links to the global settings page, a quiz override to that quiz's settings page, a question value to that question in the quiz editor. **[call]**
- A quiz is read in its current form: its draft if it has one, otherwise its latest published revision. Archived quizzes are left out. **[call]**
- A stored value no longer offered counts as none, as on the other levels (`question_value`). **[call]**
- Only settings declared by modules are listed. Settings of the application itself, such as navigation, are not on these pages. **[call]**
- A long list shows the first 50 and the total count. **[call]**
- A module with no settings says so. **[call]**

### After a plugin is disabled

- A disabled question type or scoring strategy is not offered for a new question, in a bank or on import. Import refuses such a row with its usual row message. **[docs]**
- A draft that still holds such a question opens, and the question can be seen and removed. Publication refuses through the existing publication problems, which already catch `LookupError`. **[docs]** Preview refuses with a message naming the question and the module; `app/domain/preview.py` and `app/api/admin_preview.py` catch only `UnknownPort` today, so they must also handle `ModuleDisabled`. **[call]**
- Anything that reads stored content keeps working: statistics, the comparison of runs, grading, results, walkthrough and exports of past runs use the port with `include_disabled=True`. `run_stats` does not today. **[docs]**
- With `rewards.threshold` off, threshold and draw-with-minimum rules are not offered and saving one is refused with a message. With `drawings.manual` off, draw rules are not offered and a draw is refused with a message. Pages showing existing rules and draw history still open. **[call]**
- A page of a question type whose module is uninstalled no longer answers 500 (TD-017): such a question is left out, as `_own_answers` in `app/api/public.py` does. **[docs]**

## Constraints

- The kernel gains a function that returns the reasons a module cannot change state, without raising, used by both `set_enabled` and the page. Domain and API contribute through `register_usage_check`. A reason carries translatable text and optionally a target for a link, without the kernel knowing what that target is. **[call]**
- The locked modules are declared by a new optional manifest field or a constant in `app/contracts`, not by a list in the kernel of module ids. **[call]**
- Manifests gain a translatable `name` and short `description`, optional in the schema so the plugin API stays within `>=1.0,<2.0`; a module without a name is shown by its id. All 17 modules in this repository fill them in, from the module's own catalogue, and a test in this repository checks that. **[call]**
- Pages require the admin login, changes are POST with CSRF. A module id in a URL is checked against the installed modules, an unknown one is 404. **[call]**
- UI texts in cs, en and uk. "běh", not "kolo". **[docs]**
- Docs in English. New ADR-0057 covers the locks, the reasons and the decision not to add `plugin_configuration`; `docs/_architecture/modules/kernel.md`, ADR-0038's pointer and the docstring of `app/domain/settings.py` are corrected. **[docs]**
- No new setting. **[call]**

## Risks

- Check and write are not one transaction: a run opened in the same moment a plugin is disabled can slip through. Its attempts still work, because playing reads with `include_disabled=True`. Accepted. **[call]**
- Reading all current quizzes for "Different elsewhere" on each detail page costs time on a large installation. Target is about 50 participants and a modest number of quizzes; the list is built only on the detail page. **[call]**

## Left to the builder

- Exact shape of a reason object and the manifest field for locks.
- URL names, the order of rows, and layout of the detail page.
- Which module owns each translated text, within the existing catalogue rules.
- How a link to a question is formed, given the existing editor routes.

## Verification

New acceptance criteria from AC-120, each named by a test:

- AC-120 List: all modules appear with kind, version and state; a provider has no switch.
- AC-121 Switch: an admin disables and enables a question type; the change applies without restart and is audited; the page requires login and CSRF.
- AC-122 Locks: `flow.basic`, `participants.basic`, `results.local` and `scoring.basic` refuse in the page and in `manage.py`; the last theme refuses, a theme with another enabled does not.
- AC-123 In use: a scheduled or open run or a live reward rule blocks disabling, and the detail lists it with a link, in the admin's language.
- AC-124 Settings: the detail lists the module's settings with the global value and the link to change it.
- AC-125 Different elsewhere: a quiz override and a question value differing from global are listed, an equal one is not, archived quizzes are left out, the draft wins over the published revision.
- AC-126 After disabling: the type is not offered; a draft holding it opens and publication refuses with a message; statistics, comparison, grading, results, walkthrough and exports of a past run still answer; with the rewards or draw plugin off their pages open and new rules are refused.
- AC-127 Missing module: the public page and the walkthrough of an ended quiz whose question type is uninstalled answer without error (TD-017).

`make quality`, `make smoke`, and `kvizotron-browser-walkthrough` on a new quiz in `kvizotron-browser`. Any plugin disabled during the walkthrough is enabled again at the end, as that stack's global state must stay as it was.
