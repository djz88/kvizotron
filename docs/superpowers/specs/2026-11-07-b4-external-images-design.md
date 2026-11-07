# B4 External images and the settings chain: design

Status: approved 2026-11-07. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

Admins want to use a picture from the web without downloading and uploading it by hand (`FR-21`). A copy keeps a published quiz stable and private, so it is the default. Some organisers still want the picture served from its source, so the choice is theirs.

While deciding where that choice lives, the user set a rule for the whole project: every setting is inherited global → quiz → question unless someone decides otherwise. Modules must face that decision, and a test enforces it.

## Goals

1. An image takes a file or an `https://` address, wherever an image can be added today (question and option images of type Výběr, in quizzes and banks).
2. Two modes decide what a participant gets: `copy` (default) or `external`. The mode is inherited global → quiz → question **[user]**.
3. The source address of a copy stays visible to admins only **[user]**.
4. A quiz that loads images from elsewhere tells its admin when a check of those addresses failed, at most once an hour **[user]**.
5. Every module declares its settings, and a declared setting has all three levels unless a narrower scope is declared with a reason. Tests fail otherwise **[user]**.
6. `show_sources`, `shuffle_options` and `none_option` gain a question level **[user]**.

## Non-goals

- Per-image mode. The lowest level is the question, one value for all its images **[user]**.
- A question level for `navigation_mode`, `reveal_moment`, `reveal_level`, `shuffle_questions`, `color_palette`, `revision_switch_policy`. They stay global and quiz, each with its reason **[user]**.
- Installation modes "no network / normal" that derive security settings. Recorded as a new `TD-NNN` through `make tech-debt-create` **[user]**.
- A scheduler or job process. The check runs when an admin opens a quiz **[user]**.
- Noticing that an external picture changed. The check asks only whether a usable image is still there **[call]**.
- Addresses in CSV import: B5 (`AC-13`) **[docs]**.
- Images in type Přiřazení: it has none today **[call]**.

## Anti-goals

- A participant sees the source address of an image shown as a copy.
- A published revision changes because a setting changed: a quiz or global mode changes only where the picture is loaded from, and never a revision's content.
- Saving a question silently drops an address or loses the rest of the form.
- A server-side fetch reaches an internal address while the switch is off, including through a redirect or a name that resolves differently the second time.
- A failed check blocks a quiz or a participant.

## Images

### Data

An image in a question definition: `{"asset": id | null, "source": "https://…" | absent, "alt": {locale: text}}`. An uploaded file has no `source`. The name is not `url`, because `with_media_urls` already writes the address to show under `url` **[call]**. Alternative texts and their publication check stay as they are **[docs]**.

### Entering an address

In the shared image fields (`choice/admin.html`, macro `image_fields`), next to the file input, an address input. A file sent with an address wins, and the address is cleared **[call]**. Unchanged address with an existing copy: nothing is fetched, so a copy never changes on its own **[user]**. A changed address, or one still without a copy: fetched on save.

Always refused with a message, keeping the form: anything but a well-formed `https://` address, including embedded credentials **[call]**.

### First verification

Saving an address always fetches it, whatever the mode **[user]**. Success stores a copy through the same processing and limits as an uploaded file ([ADR-0028](../../_architecture/adr/0028-upload-limits.md)), so a later mode change needs no fetch **[call]**.

When it fails, the *effective* mode at that moment decides **[user]**:

- `copy`: refused with a message, keeping the form, like a bad file.
- `external`: saved without a copy (`asset: null`), with a warning on the saved page. Every later save of the question tries again **[call]**.

The effective mode here is the value the form submits for the question, then the quiz, then global. A bank question has no quiz: question, then global. So with global `copy`, a bank question whose address fails is refused until it is set to `external` on the question, even if it will be drawn into an `external` quiz. Publication then checks against each quiz's own mode, as below **[call]**.

A fetch refused because the address is internal counts as a failed verification. So an intranet picture still works as `external` with the switch off: the browser loads it and the server never does **[call]**.

### What a participant gets

The API resolves the source, as it already builds addresses (`with_media_urls`) **[docs]**. Plugins see no mode and no settings.

| Effective mode | Has copy | Participant gets |
|---|---|---|
| `copy` | yes | `/media/<id>` |
| `external` | yes | the address |
| any | no | the address |

The source address is removed from the public payload unless it is what gets shown. A copy-mode picture must not reveal it in markup **[user]**.

The mode is resolved at render time and not frozen on the attempt: a change only moves where the same picture comes from **[call]**. The question-level value is part of the question, so it lives in the revision.

If an external picture fails to load, the browser shows its alternative text. Nothing else is added **[call]**.

### Publication

Publication is blocked when an image has no copy and the effective mode for that quiz is `copy`, including questions in draw pools **[user]**. The message names the question and says to save it again or change the mode. A later change of the quiz or global setting does not touch a published quiz: such an image keeps loading from its address, and the warning below shows it **[call]**.

### Admin view

- The editor shows the address and a preview: the copy if there is one, else the address. It marks an image with no copy.
- The change overview lists an added or changed address (`revision_diff`, `_image_rows`).

### Security

Fetch **[call]**, in the media provider, using the standard library unless the plan justifies a dependency:

- Limits: 10 s in total, 15 MB read, at most 3 redirects. Each redirect is checked again and must stay `https://`. Certificates are always verified. Sends a generic client name and no cookies.
- With the switch off, every address the name resolves to must be globally routable, and the connection goes to that checked address, so a name cannot resolve differently the second time.

Switch: global setting `allow_internal_image_addresses`, default off **[user]**. Any admin can turn it on, so a stolen admin account could also use it to reach the internal network; the settings page says so in one line, and the change is audited as every setting is **[call]**.

Browser **[call]**:

- `img-src` gains `https:` on all pages. It is simpler than per-page policies, and page text is already escaped.
- Images get `referrerpolicy="no-referrer"`.

Privacy **[call]**: the public privacy page and `docs/privacy.md` say that a quiz may load images from another server, which then sees the participant's IP address.

### Hourly check

- **Trigger [user]:** an admin opens a quiz. The page loads first, then HTMX posts to a check address **[call]**, so the page never waits. Nothing runs if the quiz has no external images or was checked within the hour.
- **Scope:** images loaded from an address for this quiz, from its draft and its current published revision, including draw pools. Copies are not checked **[user]**.
- **Budget [call]:** 3 s per address, 10 s per request. What does not fit waits for the next opening. It takes one of the worker's 8 threads, so participants are not held up.
- **Result [call]:** stored per address with its time. The quiz header shows a warning with the number of failed images and the time of the last check, and the publish page lists them. No failure, no warning. It never blocks publication.

## Settings chain

### The rule

- Every setting declares its scopes. The default is `global`, `quiz`, `question` **[user]**.
- A narrower scope needs a written reason in the declaration, or the test fails **[user]**.
- Every module manifest has a required `settings` field. No settings means an explicit `[]`, so a module cannot have skipped the question **[user]**. This applies to plugins and providers alike, since the first real user is the media provider **[call]**.
- `settings` lists what a module owns. The existing `settings_requirements` ([ADR-0034](../../_architecture/adr/0034-module-requirements-on-settings.md)) lists what a module needs from settings. Both stay, ADR-0034 is not superseded, and ADR-0042 states the difference **[call]**.
- Whoever adds a setting decides where it fits. An agent asks the user unless the task already says **[user]**.

A setting is a value inherited along this chain. Question content such as points, scoring strategy or sources is not a setting **[call]**.

### Shape

`SettingDefinition` gains `scopes` and `scope_reason`. A manifest entry adds what the admin form needs: key, choices, default, scopes, reason, and label texts in the module's own catalogue. Manifests stay plain data, since they load before Django **[docs]**. Module settings join the catalogue at start-up, and a duplicate key is a start-up error **[call]**. They come and go with their module: without an enabled media provider, its two settings and the address input are not offered, and images keep today's message that they cannot be stored **[call]**.

The nine existing settings stay in the domain catalogue. Where a module setting's key lives is otherwise left to the builder.

`settings.resolve(key, quiz=None, question=None)` returns: question value, else quiz value, else global, else default. A stored value no longer offered is skipped, as today **[docs]**. A question value is stored in the question's `settings` only when set, so a question follows the quiz by default **[call]**.

A plugin still reads no settings; the API passes what it needs **[docs]**.

### Settings in this milestone

| Setting | Scopes | Owner |
|---|---|---|
| `external_image_mode` (`copy`, `external`) | global, quiz, question | media provider |
| `allow_internal_image_addresses` (off, on) | global only: it guards the server, not a quiz | media provider |
| `show_sources` | global, quiz, question | domain |
| `shuffle_options` | global, quiz, question | domain |
| `none_option` | global, quiz, question | domain |
| the other six | global, quiz, each with its reason | domain |

The reasons for the six are written by the builder from what each setting does: all apply to the attempt or the quiz as a whole **[user]**.

### Admin UI

The global page, quiz page and question editor offer each setting according to its scopes. On a question: a select in the common settings, with a first option following the quiz and naming the current value **[call]**. A question-level setting is offered only on types it affects: `none_option` and `external_image_mode` on Výběr, `shuffle_options` on types that shuffle, `show_sources` on all. How a type states this is left to the builder, through its contract **[call]**.

Changing a question-level value is a change of the question, so it creates a draft and appears in the change overview **[call]**.

### Tests that enforce it

In `tests/contracts/`, run over every discovered module and the domain catalogue:

- A manifest without `settings` fails.
- A setting with fewer scopes than the default and no reason fails.
- A setting with a question or quiz scope that its page does not offer fails, so a declaration cannot exist without the working override. The test reads the real form or rendered page, never a second declared list **[call]**.
- An unknown scope fails.

Written down in: a new ADR, root `CLAUDE.md`, `app/plugins/CLAUDE.md`, `app/providers/CLAUDE.md`, `docs/plugin-api.md`.

## Documents

- ADR-0042: settings inherited global → quiz → question, declared by every module.
- ADR-0043: external images: a copy by default, an inherited mode, first verification, and the fetch rules.
- `providers/media-local.md`, `data-model.md`, `security.md`, `privacy.md`, `roadmap.md`, `acceptance-criteria.md`, root `CLAUDE.md`: updated.

New acceptance criteria, Stage B, from AC-38:

- **AC-38 Address:** a valid address stores a copy. The participant's page shows `/media/<id>` and contains no source address. Editing the question without changing the address fetches nothing.
- **AC-39 Modes:** with global `copy`, quiz `external`, question `copy`, the participant gets the copy; removing the question value gives the address. Changing the quiz value creates no draft.
- **AC-40 Failed verification:** in `copy` the form returns with its data and a message; in `external` the question saves without a copy and warns. Publishing in `copy` is then blocked and names the question.
- **AC-41 Internal addresses:** with the switch off, an internal address and a redirect to one are never fetched; with it on, they are.
- **AC-42 Check:** an unreachable external image shows a warning on the quiz; a second opening within the hour runs no check; a copy-mode quiz runs none and shows none.
- **AC-43 Settings rule:** a module without a `settings` field, or with a narrower scope and no reason, fails the contract tests. Each scope of each setting is offered on its page, and question beats quiz beats global.
- **AC-44 Question level:** `show_sources`, `shuffle_options` and `none_option` set on one question change that question only. With no question values, an existing quiz behaves as before.

## Left to the builder

Names of fields, routes and tables not given above; the storage of check results; how a type states which settings it affects; layout of the address input within the existing image fields, keeping it collapsed and consistent; automated tests use a local fake, never the network. Verification in Docker, as usual, without touching `kvizotron-browser` data.
