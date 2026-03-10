---
description: 'Five AI pitfalls to guard against. Trust code over comments, verify before concluding, hunt bugs actively, slow down, trace actual values not patterns.'
id: 'software-development/principle/failure-modes'
scope: 'domain'
type: 'principle'
visibility: 'public'
---

# Failure Modes — Principle

## Principle

Never trust surface reads. Trace real behavior with concrete values before concluding anything.

## Rationale

These recurring failures produce incorrect conclusions:

- **Comment over-trust**: comments rot; code is the source of truth.
- **Surface validation**: "looks right" is not evidence; trace with real inputs.
- **Bug denial**: user-reported bugs are real until disproven by investigation.
- **Speed bias**: rushing replaces reasoning with pattern-matching.
- **Pattern projection**: familiar constructs can still behave incorrectly.

## Implications

- Always walk the code with concrete values.
- Keep the active objective current.
- When code, tests, comments, plans, or prior conclusions disagree, ascertain what is leading and what is stale before changing anything.
- A failing test proves there is a mismatch. Existing code proves there is current behavior. Neither one alone proves intended behavior.
- Treat mismatch as investigation work: trace the real behavior, determine the intended behavior for the active objective, then fix the stale side of the mismatch.
- Verify comments against actual behavior.
- Assume the bug exists and hunt the exact failure path.
- Prefer a quick test over speculation.
- Slow down when uncertain; read more files and trace more paths.

## Tensions

- Speed vs correctness.
- Confidence vs evidence.
