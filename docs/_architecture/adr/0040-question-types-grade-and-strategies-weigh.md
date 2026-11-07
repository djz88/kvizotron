---
status: accepted
date: 2026-11-06
---

# ADR-0040: Few question types with settings; types grade and strategies weigh

## Context and Problem Statement

FR-15 lists eight types, each as its own module. Most of them are the same question with different settings: one, several or no correct answers, yes/no and pictures are all a choice; pairs and ordering are both matching. Scoring strategies also read the definition, so every strategy would need to know every type.

## Decision Drivers

* An admin chooses one question and sets it up, instead of choosing among similar types
* A strategy must work with a type it has never seen
* Scores add up exactly: three thirds of a point are one point

## Considered Options

* Types `choice` and `matching` with settings, `grade()` on the type, strategies weighing only the grade
* One module per variation, with strategies reading each definition
* One module per variation that shares code in a library

## Decision Outcome

Chosen option: "Types `choice` and `matching` with settings, `grade()` on the type, strategies weighing only the grade", because it needs the least code and gives strategies one small input.

* `QuestionTypePlugin.grade(config, answer) -> ItemGrade(right, wrong, total)`.
* `ScoringStrategyPlugin.evaluate(grade, settings) -> ScoreBreakdown`, `max_score(settings) -> Decimal`.
* Scores are `Decimal`. `partial` computes once with `Fraction` and rounds to 4 places at the end.
* The API passes quiz values a type needs through `public_payload(config, locale, quiz_settings)`; a plugin reads no settings.

The contract stays at version 1.0, because nothing has been released and no other modules exist.

### Consequences

* Good, because yes/no, trick questions and pictures add no modules, and a new strategy works with every type.
* Good, because FR-16's editor, schema and validation stay per type.
* Bad, because `choice` and `matching` hold several behaviours, so their contract tests cover each of them.

## More Information

FR-15 keeps its list of question kinds; [question-types.md](../plugins/question-types.md) says which type provides each.
