# UI foundation: design

Status: approved 2026-11-06. Marks: **[user]** decided by the user, **[call]** the author's call, open to correction.

## Why

Every later milestone adds screens: the editor in B2, quiz flow in B3, scoreboards in C4. Today the pages are bare
Pico CSS, settings and actions are mixed on one long quiz page, and nothing says where a new setting belongs. This
milestone fixes layout, navigation, the place of each setting and the base look **[user: as soon as possible]**, so
later screens are built into it instead of being redone in Stage D.

Direction **[user]**: settle layout first, keep it simple, ordinary modern look, mobile first, and everything
configurable where it reasonably can be.

## Roadmap

New milestone **B1.5 UI foundation** before B2 **[call on the name]**. Custom branding (own colours, logo, editable
texts) stays in D1, which builds on what this milestone introduces.

## Goals

1. One navigation model for the administration and the public side, on desktop and phone.
2. A fixed place for every kind of setting, recorded in the architecture docs.
3. A quiz header that puts status next to the action that changes it.
4. The word "run" instead of "round" in the UI.
5. A short translated description on every quiz.
6. Five preset colour palettes, global with a per-quiz override.
7. Public menu with information pages.

## Non-goals

- Custom colours, logo, uploaded images, editable motto and menu texts: D1.
- Questions shown one at a time and a progress indicator: B3 (add the indicator to B3 in `roadmap.md`).
- Reordering questions, "Save and next": B2 or later.
- New features on the run page such as schedules, access codes or scoreboards: Stage C. Only their future place is decided.
- Full privacy notice (FR-35): Stage D. See the note on the privacy page below.

## Anti-goals

- A layout that needs JavaScript to reach any action. Everything works by keyboard and without scripts, as playing does today.
- A primary button that does something the admin cannot see first: publishing still goes through the change overview.
- Inline scripts or styles: the CSP refuses them.
- A palette whose text is hard to read.

## Administration layout

### Top bar **[user]**

Desktop: `Kvízotron` on the left; `Quizzes`, `Settings`, `Admins`, the language switch and `Log out` on the right. There
is no side panel and no bottom bar.

Phone: `Kvízotron` and a menu button. The menu holds the same items, with the language switch **[call]**.

### Language switch **[user]**

A dropdown showing the active flag; opening it lists the other languages with flag and name. Administration offers cs
and en, public pages offer the languages the page has. Flags are small SVG files in the theme, not emoji, because
Windows does not draw flag emoji **[call]**. Each flag has the language name as text for screen readers **[call]**.

### Quiz header **[user]**

Stretches across the full page width, above the tabs. Two rows:

```
 Pub quiz                       [Published revision: 3] [Unpublished changes] [ Publish changes | v ]
 Public address: /q/pub-quiz · languages cs, en                               ( Run 2 is running )
 ---------------------------------------------------------------------------------------------
 Questions   Runs   Revisions   Settings
```

The second-row status sits in a grey rounded area and is status only, with no button of its own **[user]**.

On a small screen the whole header is under a dropdown. Closed, it shows the quiz title and the current tab. Open, it shows
status, the main button, address, run status and tabs, one below the other **[user: under a dropdown; call: main button
inside it too]**.

When no run or revision exists, tags say `Not published`; `Unpublished changes` is not shown next to it **[call]**.

### Main button **[user]**

One button whose label and action follow the quiz state. The arrow opens the listed secondary actions.

| Quiz state | Grey area (label shown) | Main button | Under the arrow |
|---|---|---|---|
| Never started | The quiz is not running | **Start the quiz** | Publish only, Discard changes |
| Finished | Run 2 has ended | **Start again** | Publish only, Discard changes |
| Running, has changes | Run 2 is running | **Publish changes** | Discard changes, End the run |
| Running, no changes | Run 2 is running | **End the run** | none |
| Archived | Archived | **Restore from archive** **[call]** | Duplicate |

- "Has changes" means a draft exists, the same test as today's `has_draft`, even if an edit was later reverted **[call]**.
- `Start the quiz` and `Start again` go to the publication page if the draft has changes, showing the overview. Confirming
  publishes and opens a new run in one transaction, audited as today's two actions **[call]**. Without changes they open
  a new run directly. A quiz never published always goes to the publication page, which lists what is missing, so
  `Start the quiz` never ends in "Publish the quiz first" **[call]**.
- `Publish only` is today's publication without opening a run. `Discard changes` appears only when `can_discard` is true.
- `Publish changes` is today's publication during a run, including the switch policy.
- `End the run` asks for confirmation on the existing confirmation page, because it sits where an admin expects a safe
  button **[call]**. The domain rules do not change.
- A quiz with problems blocking publication still reaches the publication page, which lists them.
- `Start again` always creates a new run with new results (ADR-0008 and the existing restart rule).

### Tabs **[user]**

`Questions`, `Runs`, `Revisions`, `Settings`. The current page is marked with `aria-current`. Today's "Revisions and rounds" page splits in two.

- **Questions** `/admin/quizzes/{id}/edit`. A list with one row per question: number, text, type name, points, a tag
  `en missing` for each missing translation, and a menu `⋮` with `Delete` **[user: option A]**. `Add question ▾` lists the
  question types. A question opens on its own page; saving returns to the list **[user]**. The type name needs a readable label
  from the plugin (see Contracts).
- **Runs** `/admin/quizzes/{id}/runs` (GET added; POST keeps opening a run). A panel with the running run, if any: QR code,
  address, submitted count. Below it a table: run, status, opened, closed, revisions, submitted, with a link to the run page
  **[user]**. Closing is in the header, so the panel has no button. `/admin/runs/{id}` stays and belongs to this tab **[call]**.
- **Revisions** `/admin/quizzes/{id}/revisions`. A table: number, status, published, questions, maximum score. `⋮` holds
  `Compare with previous` and `Use as new draft` **[user]**.
- **Settings** `/admin/quizzes/{id}/settings` (GET added). Three parts, each saying when its changes apply **[user]**:
  - `Title and languages`: title, description, languages, default language. Participants see them after publishing.
  - `Address and behaviour`: address, highlight on the home page, setting overrides including the palette. Apply immediately. The
    address locks after the first publication, as today.
  - `Kopie a archivace`: `Duplikovat`, `Archivovat`.

  An archived quiz shows none of the forms **[call]**.

Tables become stacked rows on a phone **[user]**.

### Main pages **[user]**

- **Quizzes**: a row per quiz with title and address on the left, the same tags as the quiz header on the right. `New quiz` at the
  top, `Show archived quizzes` below. On a phone, the published revision tag is dropped **[call]**.
- **Settings**: global values grouped by topic. Today the groups are "Running the quiz" and "Look" **[call]**.
- **Admins**: list of logins and the new admin form.

## Where things are set

To be added to `docs/_architecture/modules/api-ui.md` as the rule for later milestones **[call on the rule; placement of the
"Later" items is a proposal]**. Rule: what applies to all quizzes is in `Settings`; to one quiz, in its tabs; to one run, on
the `Runs` tab or run page. A quiz can override a global value. Each page says when a change takes effect.

| Place | Now | Later | Takes effect |
|---|---|---|---|
| Settings | revision switch policy, palette | branding, data retention, modules | Immediately |
| Admins | admin accounts | | Immediately |
| Quiz, Questions | questions, answers, points | scoring, explanation, media, question bank | After publication |
| Quiz, Runs | list of runs, QR code, submitted count | schedule, time limit, access code, repetition, scoreboard, rewards, draw | Immediately |
| Quiz, Revisions | history, comparison, return to an older revision | | After publication |
| Quiz, Settings | title, description, languages (after publication); address, highlight, overrides (immediately); copy, archive | navigation mode, when to reveal answers | By item |

## Public layout

Designed for the phone; on a desktop the same content is a narrow centred column **[call]**.

Background across the whole page in the palette's gradient. Content on a white card, a dark card in dark mode. A large heading
sits directly on the background **[user: combination of options A and C]**.

- **Bar:** `Kvízotron`, the language switch, and the menu. Phone: menu button. Desktop: items in the bar **[call]**.
- **Menu** **[user: basic information and useful things; items accepted]**: `Quizzes`, `How it works`, `About`, `Privacy`.
- **Home page:** the slogan as a large heading **[user]**, with a motto under it. Starting text: "Quizzes and contests without registration,
  right on your phone." **[call]**. Below, one row per quiz with title and description. A featured quiz has a stronger frame.
- **Quiz page:** quiz title and description as the heading, then the question count and `Start` on the full width of the card **[user]**.
- **Playing:** no large heading, so questions start at the top **[call]**. Answers are large rows easy to hit with a thumb; the
  chosen one is filled with the accent colour.
- **Result:** large score, percentage, link back.

Information pages are `/how-it-works`, `/about` and `/privacy`, with fixed translated text in cs, en and uk **[call]**.

`/privacy` text must be true for what the application does now and say that it covers the current version: no registration, no
answers or personal data in logs. FR-35 still requires the complete notice in Stage D **[call]**. The author writes the texts in all three languages. The user reads
cs and en before the merge **[call]**. Nobody reviews uk separately: mistakes get fixed when someone reports them, with no tech debt entry **[user]**.

## Quiz description **[user]**

- New field `quiz.description` (locale → text), required for every selected language, up to 300 characters **[call on the limit]**.
- Handled like the title: on the quiz row until publication, in the revision snapshot, in the change overview and in the hash behind
  `snapshot_hash`; restored on return or discard; copied on duplicate.
- A missing description blocks publication with a problem such as "The description is missing in language en."
- A migration adds the field. Existing quizzes and their immutable revisions are unchanged: they show no description until the next
  publication, which then requires it **[call]**.

## Colours **[user: all configurable, five presets to switch between]**

- New setting `color_palette` in the existing settings catalogue, with a global value and quiz override (FR-50, audited).
- Five presets; the global default is **Blue and teal** **[call]**. The first three were shown to the user; the last two are **[call]**:

| Value | Name | Main | Second | Accent | Dark |
|---|---|---|---|---|---|
| `blue_teal` | Blue and teal | `#1769e0` | `#10a5a5` | `#ffb020` | `#0f2a52` |
| `indigo_pink` | Indigo and pink | `#4b3fe4` | `#e0417f` | `#ffc400` | `#1e1b5e` |
| `violet_orange` | Violet and orange | `#6a2bd9` | `#f0702a` | `#ffd23f` | `#2c1457` |
| `green_blue` | Green and blue | `#0e7c5a` | `#1769a8` | `#ffc400` | `#0c2f2a` |
| `red_plum` | Red and plum | `#c2263f` | `#6d2a78` | `#ffc400` | `#35142f` |

- These values are the starting point. Every text and background pair must reach WCAG AA, in light and dark mode: adjust the hex values
  rather than lower the bar. A test computes it **[user: well visible; call: AA and the test]**.
- A quiz's public pages use its resolved palette. Home and information pages use the global one. The administration uses the global
  one, on white surfaces with a dark bar and the main colour on buttons **[call]**.
- Implemented as `data-palette` on the page and token blocks in `theme.css`, because the CSP refuses inline styles.
- Light or dark follows the device **[call]**. System fonts, nothing downloaded **[call]**.
- Custom colours arrive in D1 as a further choice in the same place.

## Terminology

The UI says **běh** (en "run", uk chosen by the builder with a natural word) for `QuizRun` **[user]**. All catalogues and source strings
change; so does `Revize a kola`. Code names stay. Docs use "run" in new text, and one line in `domain.md` says older docs use "round"
for the same thing **[call]**. The end of the playing window, when deadlines arrive in C1, is not called a "deadline" in Czech ("termín").

## Contracts

- `QuestionTypePlugin` gains a translated readable label for the list and the add menu, in the contract suite and `docs/plugin-api.md` **[call]**.
- `ThemePlugin` keeps its shape: palette tokens are in the theme's stylesheet, and a test checks that each catalogue value has a block **[call]**.
- The five palette values are a constant in the domain settings catalogue for now. FR-14 says admins configure only what the current theme
  offers; v1.0 has one theme, so this holds today. The branding contract in D1 moves the list to the theme, and `roadmap.md` says so **[call]**.

## Constraints

- Views stay thin; rules live in `app/domain/`, including which main button applies to which state, so it can be tested without HTML **[call]**.
- New admin strings in cs and en, public strings in cs, en and uk.
- Docs in English, each fact in one place. Update `roadmap.md`, `api-ui.md`, `domain.md`, `data-model.md`, `theme-default.md`, `plugin-api.md`,
  `CLAUDE.md`. New `FR-xx` and `AC-xx` take the next free numbers. New ADR only if the builder finds a decision of that weight.
- Verified in Docker: `make quality`, `make smoke`, and a browser walkthrough at phone and desktop width, in light and dark mode, by keyboard.

## Acceptance

- Every admin and public action is reachable by keyboard and without JavaScript, at 360 px and at desktop width, with no horizontal page scroll.
- The main button shows the right label and action in each row of its table; `Start the quiz` with changes shows the overview, then publishes and opens a run together.
- If opening the run fails, the publication is not kept either.
- A quiz without a description in a selected language cannot be published; an existing published quiz keeps working unchanged.
- A palette override on a quiz changes only that quiz's public pages; deleting it returns to the global value; saving creates no draft.
- All five palettes pass the contrast test in both modes.
- No user-visible "kolo" or "round" remains in the catalogues.

## Left to the builder

Template structure, CSS, exact labels not fixed above, how dropdowns work without JavaScript, URL names not listed, how type labels are
translated, and the uk word for "run".

## Mockups

Screens are in `.superpowers/brainstorm/1092193-1793975001/content/`, which is not in git: `quiz-header-v6.html`, `questions-tab.html`
(option A), `other-tabs.html`, `main-pages.html`, `public-combined.html`, `colors.html`.
