---
status: accepted
date: 2026-11-04
---

# ADR-0018: Locales cs/en/uk with per-quiz required languages

## Context and Problem Statement

Audience is Czech, English and Ukrainian speaking; not every quiz needs all languages.

## Decision Drivers

* Complete translations for published languages
* Shared results across languages
* Language-safe text normalisation

## Considered Options

* Platform locales cs/en/uk; admin selects required locales per quiz; publish blocked if incomplete
* All three always required
* Free-form locales

## Decision Outcome

Chosen option: "Platform locales cs/en/uk; admin selects required locales per quiz; publish blocked if incomplete", because it balances coverage and authoring effort.

### Consequences

* Good, because admin UI cs/en, public UI cs/en/uk
* Bad, because diacritics normalisation must be locale-aware (Ukrainian)

### Confirmation

[AC-03](../acceptance-criteria.md).

## More Information

FR-03, FR-04, FR-20.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
