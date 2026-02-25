---
name: test-driven-development
description: RED-GREEN-REFACTOR discipline with iron laws. Use when implementing features or bugfixes, before writing implementation code.
---

# Test-Driven Development

## Purpose

Force behavior clarity and regression safety by writing failing tests before production code and implementing only what is required to pass.

## Scope

Use for feature delivery, bug fixes, and behavior-preserving refactors where testable behavior can be defined.

Iron laws:

- No production code without a failing test first.
- No green result without first confirming meaningful red.
- No refactor unless all tests are green.

## Inputs

- Requirement or bug statement translated into observable behavior.
- Existing test harness or minimal executable verification path.
- Current code context and constraints.

## Outputs

- New or updated tests that fail before implementation and pass after implementation.
- Minimal production change that satisfies the test.
- Refactored code that preserves green test state.
- Verification record for the RED, GREEN, and REFACTOR checkpoints.

## Procedure

1. Convert requirement into one focused behavioral assertion.
2. Write a single failing test for that assertion (RED).
3. Run tests and confirm the failure is for the intended reason, not setup noise.
4. Implement the smallest production change to satisfy that test (GREEN).
5. Run tests again and confirm targeted and relevant suite checks are green.
6. Refactor only after green; keep behavior constant and rerun tests (REFACTOR).
7. Repeat cycle for the next behavior increment.

Checkpoint discipline:

- RED checkpoint: failing test observed and understood.
- GREEN checkpoint: test passes with minimal implementation.
- REFACTOR checkpoint: structure improved with no behavior change.

Rationalizations to reject:

| Rationalization                 | Failure mode                                      | Correct response                            |
| ------------------------------- | ------------------------------------------------- | ------------------------------------------- |
| "I will add tests after coding" | Passing tests prove nothing when never seen red   | Start with a failing test                   |
| "It is too small to test"       | Small code still regresses                        | Write a minimal test                        |
| "I manually tested it"          | Manual checks are inconsistent and non-repeatable | Automate expected behavior                  |
| "I already wrote a lot of code" | Sunk-cost pressure blocks correctness             | Delete unverified code and restart with RED |
| "I can optimize while here"     | Mixed concerns hide behavior changes              | Keep GREEN minimal, refactor separately     |
