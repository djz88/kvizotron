---
status: superseded by ADR-0036
date: 2026-11-04
---

# ADR-0003: Python with FastAPI, server-rendered Jinja2 and HTMX

## Context and Problem Statement

We need a web stack for public quiz pages, an admin editor and a JSON API, maintainable by a small team.

## Decision Drivers

* Server-side rendering for simple, accessible pages
* Typed contracts (Pydantic)
* Minimal JS build complexity

## Considered Options

* FastAPI + Starlette + Jinja2 + HTMX + small vanilla JavaScript without a build step
* Django
* SPA (React/Vue) + API

## Decision Outcome

Chosen option: "FastAPI + Starlette + Jinja2 + HTMX + small vanilla JavaScript without a build step", because it combines typed APIs with server-rendered HTML and little client code.

### Consequences

* Good, because one language for server, plugins and tests
* Good, because mobile-friendly SSR pages
* Bad, because plain JavaScript has weaker type checking in question editors
* Bad, because rich editors (ordering, matching) still need hand-written JS per question type

### Confirmation

Stage A vertical slice ([../roadmap.md](../roadmap.md)).

## More Information

Python version: [ADR-0022](0022-python-version.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
