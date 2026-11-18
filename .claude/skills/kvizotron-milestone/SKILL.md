---
name: kvizotron-milestone
description: Use when starting, designing, planning or closing a roadmap milestone of Kvízotron (A1 to D5), including "co je další krok", "pokračuj" or "spusť brainstorming" when the next step is a milestone.
---

# Kvízotron milestone

It supplements the general `superpowers:*` skills with how milestones are done here. The order: design → plan → build → verification → documents → merge. Each step starts only after agreement with the previous one.

## 1. Design

First read the milestone's row in `docs/_architecture/roadmap.md` and its `FR-xx`, ADRs and `OQ-xx`. Do not ask about what is decided there. An ADR with status `proposed` is decided by the person.

Then **REQUIRED SUB-SKILL:** `superpowers:brainstorming`, with these rules:

- Questions through `AskUserQuestion`, the recommended choice first, with a short example of what each choice means.
- A note on an answer is a decision, even if it differs from the offer. If you cannot tell the choice from it, ask one short question.
- A bare "ano" is not skipping the questions. Build without questions only after an explicit "bez otázek" or "rovnou".
- Security proportionate to a quiz: the simplest mechanism that stops real cheating.
- A new setting: **REQUIRED SUB-SKILL:** `kvizotron-add-setting`.

## 2. Spec

A file in `docs/superpowers/specs/` named `YYYY-MM-DD-<milestone>-<topic>-design.md`, in English, with sections in this order: Why, Goals, Non-goals, Anti-goals, Behaviour, Constraints, Risks, Left to the builder, Verification.

Every decision has a tag: **[user]** the user said it, **[docs]** it is already in `docs/_architecture`, **[call]** your choice, which they may correct. An assumption never gets **[user]**.

After the spec is approved **REQUIRED SUB-SKILL:** `superpowers:writing-plans`. The branch is `feat/<milestone>-<topic>`, the user chooses how it is built.

## 3. Verification before handover

Everything on the merged tree, announce the result with the output:

1. `make quality`
2. `make smoke`. When `kvizotron-browser` is running, with `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543`.
3. **REQUIRED SUB-SKILL:** `kvizotron-browser-walkthrough`, if anything a person sees has changed.
4. **REQUIRED SUB-SKILL:** `kvizotron-check-applied`.
5. A final check of the whole branch by a fresh reviewer, with the output from the previous step. Fix Critical and Important findings with a test that fails first.

## 4. Milestone documents

Go through every point, even if it ends up unchanged:

| Place | What |
|---|---|
| `docs/_architecture/roadmap.md` | the milestone's row, its AC and `Done YYYY-MM-DD` |
| `docs/_architecture/acceptance-criteria.md` | new AC from the next free number; a test must name them, otherwise `tests/test_docs.py` fails |
| `docs/_architecture/adr/README.md` | the new ADR and its row |
| `docs/_architecture/modules/api-ui.md` | URLs and the "Where things are set" table |
| `docs/_architecture/modules/domain.md`, `docs/_architecture/data-model.md` | states and tables |
| `CLAUDE.md` | the list of milestones in the intro, the Status paragraph and "Next is …" |
| `CLAUDE.md` in the affected directories | what was added in them and what to watch out for |
| `.claude/skills/kvizotron-check-integration/flows.md` | a new flow or link |

Deferred minor items are recorded through `make tech-debt-create title="…"`, not by hand, and the user sees them in the final report.

## 5. Handover

List in full the decisions you made for the user and the deferred minor items. At the end offer the options from `superpowers:finishing-a-development-branch` and wait. Merge, push and deleting branches happen only with consent; the repository has no remote.

`kvizotron-browser` is not touched except as `kvizotron-browser-walkthrough` says.
