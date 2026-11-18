# English-First Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every developer- and agent-facing text in the repository is English; Czech stays only in `README.cs.md` and in user-facing texts (UI translations, tests that assert them).

**Architecture:** A translation of existing files, task by task by area, with the rule written into `CLAUDE.md`. Meaning, IDs, paths, code identifiers, commands and links stay exactly as they are; only the language changes.

**Tech Stack:** Markdown, Makefile, shell, Python (stdlib tools), pytest.

**Spec:** the owner's decisions in chat on 2026-11-18: "everything primarily English; Czech optional for README.md or where user-facing things are"; README: English `README.md` plus Czech `README.cs.md`; older dated specs and plans in `docs/superpowers/` are translated too.

## Global Constraints

- Translate meaning faithfully; do not add, drop or "improve" content. Keep every ID (`FR-xx`, `AC-xx`, `ADR-NNNN`, `OQ-xx`, `TD-NNN`), path, code identifier, command, URL, table structure and heading order.
- Keep Czech where it is user-facing or quoted: gettext UI strings and `.po` files, UI labels quoted as UI text (e.g. a tab name shown to users — give the English meaning in parentheses only if the sentence needs it), the app name **Kvízotron**, people's names, sample content meant for Czech users, and tests that assert Czech UI text.
- Terms: `QuizRun` is "run" (never "round"/"kolo"); Kvízotron keeps its diacritics in prose, `kvizotron` in identifiers.
- No local paths or LAN addresses (`tests/test_docs.py`, `tools/private_traces.py`).
- A file that becomes English stays one file (no parallel Czech copy), except README.
- `make lint` and `make test` stay green; `tests/test_docs.py` rules hold (skill names `kvizotron-*`, AC naming, links).
- Commits: message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; no `Claude-Session` line. Never touch Docker stacks `kvizotron-browser` or `kvizotron-tmp`.

## Review Focus

1. A translated rule that changed meaning (e.g. MUST vs SHOULD, "always VELKÁ" tiers, forbidden actions) — reviewers compare against the Czech original in git.
2. A heading or phrase another file, script or test refers to by its Czech text (e.g. `(CLAUDE.md, Pravidla)` in `tools/private_traces.py`, "už existuje" in `tests/test_private_traces.py`) — renamed together.
3. User-facing Czech accidentally translated (UI strings, sample data, test assertions on UI text).
4. Lost content in long files (root and module `CLAUDE.md`, `flows.md`).
5. The dev-workflow profile tiers in `CLAUDE.md` ("Always VELKÁ" list) keep the tier names the global skills use (`MALÁ`, `STŘEDNÍ`, `VELKÁ`).

The file list to work from: every tracked file outside `tests/`, `.po`/`.mo` and `locale/` that contains Czech, as printed by
`git ls-files | xargs grep -lP "[ěščřžůťďňĚŠČŘŽŮŤĎŇ]"` (each task names its share).

---

### Task 1: The root rule, README and the root CLAUDE.md

**Files:** `CLAUDE.md` (`AGENTS.md` is a symlink to it), `README.md` (→ English), new `README.cs.md` (the current Czech README, kept current, each linking the other at the top), `tools/private_traces.py` (the "(CLAUDE.md, Pravidla)" reference → the new English section name), `tests/test_private_traces.py` docstring.

- [ ] Translate `CLAUDE.md` whole. Replace the documentation-language bullet with: "Everything in the repository is in English: code, comments, docs, agent instructions, skills, Makefile help and tool messages. Czech stays only in `README.cs.md` and in user-facing texts (UI translations cs/uk and the tests that assert them)." Keep the dev-workflow profile tier names `MALÁ`/`STŘEDNÍ`/`VELKÁ` as they are (the global skills read them).
- [ ] `README.md` in English with a line at the top linking `README.cs.md`; `README.cs.md` with the Czech text and a link back.
- [ ] Rename references to translated section names; run `uv run pytest tests/test_docs.py tests/test_private_traces.py -q`.
- [ ] Commit `docs: English root instructions and README, Czech README.cs.md`.

### Task 2: Module CLAUDE.md files

**Files:** `app/CLAUDE.md`, `app/api/CLAUDE.md`, `app/domain/CLAUDE.md`, `app/contracts/CLAUDE.md`, `app/kernel/CLAUDE.md`, `app/plugins/CLAUDE.md`, `app/providers/CLAUDE.md`, `app/plugins/*/CLAUDE.md` (rewards, results, participants, drawings and any other with Czech), `tests/CLAUDE.md`, `tools/CLAUDE.md`.

- [ ] Translate each whole; keep every file name, function name, ADR/AC reference and the order of bullets.
- [ ] Run `uv run pytest tests/test_docs.py -q`; commit `docs: English module instructions`.

### Task 3: Agent tooling in .claude/

**Files:** `.claude/review-profile.md`, `.claude/skills/kvizotron-*/SKILL.md`, `.claude/skills/kvizotron-check-integration/flows.md`, `.claude/hooks/guard_docker_volumes.py` (messages and comments) and the tests that assert its messages (`tests/test_agent_hooks.py`, if any).

- [ ] Translate; skill `name:` fields stay; each skill `description:` becomes English with the same triggers (Czech trigger phrases the owner types, such as "co je další krok", "pokračuj", may stay quoted as triggers).
- [ ] Run `uv run pytest tests/test_docs.py tests/test_agent_hooks.py -q`; commit `docs: English skills, review profile and hook messages`.

### Task 4: Build, deploy and tool messages

**Files:** `Makefile` (help texts, echoes, comments), `deploy/load.sh`, `deploy/smoke.sh`, `deploy/Caddyfile`, `deploy/compose.yaml`, `deploy/.env.example`, `Dockerfile`, `.gitignore`, `.pre-commit-config.yaml`, `.github/dependabot.yml`, `tools/tech_debt.py` (messages, comments), `app/settings.py` and template comments (`app/api/jinja2/admin/login.html`, `admin/base.html`, `app/plugins/questions/text/jinja2/text/admin.html`) only where the Czech is a comment, `app/providers/csv_io/sample/csv-format.md` (translate if it documents the format for developers; keep if it is sample content for Czech users — say which in the report); tests asserting these messages (e.g. `tests/test_makefile.py`, `tests/test_private_traces.py` "už existuje", tech-debt tool tests).

- [ ] Translate messages and comments; update the asserting tests to the English text.
- [ ] Run `make lint && make test`; commit `chore: English build, deploy and tool messages`.

### Task 5: Architecture docs and dated specs and plans

**Files:** every file under `docs/` that still contains Czech prose: `docs/_architecture/**` (often only a quoted UI label — keep those, translate prose), and all `docs/superpowers/specs/*.md` and `docs/superpowers/plans/*.md` with Czech (largest: `specs/2026-11-16-review-findings.md`, `specs/2026-11-06-ui-foundation-design.md`).

- [ ] Translate prose; keep quoted UI copy (e.g. cs/en copy tables in plans), owner quotes may be translated with the meaning kept.
- [ ] Run `uv run pytest tests/test_docs.py -q`; commit `docs: English architecture notes, specs and plans`.
