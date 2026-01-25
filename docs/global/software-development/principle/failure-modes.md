---
description:
  Five AI pitfalls to guard against. Trust code over comments, verify before
  concluding, hunt bugs actively, slow down, trace actual values not patterns.
id: software-development/principle/failure-modes
scope: domain
type: principle
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
- Verify comments against actual behavior.
- Assume the bug exists and hunt the exact failure path.
- Prefer a quick test over speculation.
- Slow down when uncertain; read more files and trace more paths.

## Tensions

- Speed vs correctness.
- Confidence vs evidence.
