---
name: kvizotron-check-integration
description: Use when a Kvízotron change touches more than one layer or an existing flow such as playing, revisions, schedule, grading, settings or import, and when asked whether a feature really works end to end.
---

# Check of flows across layers

`tests/test_wiring.py` verifies that the pieces exist. Here we verify that they connect: what one link stores, the next really reads, and a person gets to it through a real URL.

Reading a diff and judging a design do not belong here, that is done by `review-roles`.

## Procedure

1. **Find the affected flows.** From the changed files pick them in `flows.md` next to this file. Nothing fits? The change is either local, and say so, or it creates a new flow, and add it.
2. **Run the flow's tests.** Every flow has a command in `flows.md`. Always the whole flow, not just the file you touched.
3. **Go through the links that changed.** For each one write evidence that the previous link calls it and the next one reads its result:
   - a test that goes through the flow's HTTP URL and would fail if the link were missing,
   - a test that only calls a domain function is not evidence.
4. **Try the path where the link refuses.** Every flow states what can fail. The person must get an understandable response and the data must stay intact.
5. **Go through neighbouring paths.** The preview and the test link should behave the same and count nothing. The private link, the public walkthrough and the archive must handle the new data.
6. **Test missing?** Write it, let it fail and then fix. What cannot be verified, write as **unverified**.

## Output

| Flow | Flow tests | Changed link | Wiring evidence | Refusal | Neighbouring paths |
|---|---|---|---|---|---|

At the end a list of **unverified**, even if it is empty.

## Maintenance

A milestone that adds a flow or a link changes `flows.md` in the same branch. The paths in it are guarded by `tests/test_docs.py`.
