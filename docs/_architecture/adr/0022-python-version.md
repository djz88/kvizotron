---
status: accepted
date: 2026-11-05
---

# ADR-0022: Python version baseline

## Context and Problem Statement

The spec asks for the "current supported stable branch at start of development" without naming it.
The version pinned in the Docker image and CI must be explicit.

## Decision Drivers

* Length of the upstream support window
* Availability of wheels for dependencies (web framework, ORM, argon2-cffi)
* Risk at the start of Stage A

## Considered Options

* Python 3.15 from the start
* Python 3.14 in production with a non-blocking CI job on 3.15
* Python 3.13

## Decision Outcome

Chosen option: "Python 3.15 from the start", because it has the longest support window (until
2031-10) and avoids an early upgrade.

### Consequences

* Good, because no planned branch upgrade before or soon after v1.0
* Bad, because the branch is only one month old (first release 2026-10-09)
* Bad, because wheel availability for all dependencies has not been verified yet; missing wheels would slow image builds

### Confirmation

Before Stage A starts, verify that every pinned dependency installs and passes tests on 3.15. If a
required dependency is unavailable, fall back to 3.14 and record it by superseding this ADR.
The version is pinned in the Dockerfile and CI.

Result on Python 3.15.2 (2026-11-05): the dependencies pinned in milestone A1 install and pass tests.
Dependencies of later milestones are verified when they are added. pre-commit runs on Python 3.14,
because its dependency PyYAML has no 3.15 wheel; it is a development tool and is not part of the application.

## More Information

Resolves [OQ-01](../open-questions.md). Status of versions: https://devguide.python.org/versions/
