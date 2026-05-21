---
description: 'Five named failure patterns to recognize and refuse: comment over-trust, surface validation, bug denial, speed bias, pattern projection.'
id: 'general/concept/failure-modes'
scope: 'global'
type: 'concept'
visibility: 'public'
---

# Failure Modes — Concept

## What

A named vocabulary for the recurring failure patterns AI agents drift into. Each pattern shares the same root: the agent treats surface signals (comments, "looks right", familiar shape, prior conclusion) as evidence of behavior, rather than tracing the actual behavior. Naming the pattern is the first step in refusing it.

The five patterns:

- **Comment over-trust** — taking comments, docstrings, or doc references as authoritative when code is the source of truth. Comments rot; code runs.
- **Surface validation** — concluding "this looks right" without tracing the code with concrete inputs. Visual match is not behavioral match.
- **Bug denial** — discounting a user-reported bug because the code "couldn't" produce that outcome. User-reported bugs are real until disproven by investigation.
- **Speed bias** — substituting pattern-matching for reasoning under time pressure. Familiar shape is not analyzed shape.
- **Pattern projection** — assuming familiar constructs behave the way they usually do. The construct is correct only against today's wiring; verify the wiring.

When code, tests, comments, plans, or prior conclusions disagree, the failure-mode lens is what tells you which one is leading and which is stale. A failing test proves a mismatch — not that the test is correct. Existing code proves current behavior — not intended behavior. Only investigation, framed by the named pattern, resolves which side of the mismatch to fix.

## Why

A vocabulary lets the agent (and the reviewer) name the failure before it lands. *"I'm doing surface validation right now"* is a sentence the agent can think; *"I am about to be wrong"* is not. The named pattern is the catch handle — without it the impulse passes unexamined.

The patterns also map to specific corrections: comment over-trust → read the code; surface validation → trace with concrete values; bug denial → assume the bug exists and hunt the path; speed bias → slow down, verify more; pattern projection → check the wiring against the construct.

The corrective discipline (return to sources, verify before concluding) is owned by `general/principle/grounding`. The active investigation steps are owned by `software-development/procedure/debugging`. This concept names *what to recognize*; the principle and procedure say *what to do about it*.
