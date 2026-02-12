# Input: tdd-enforcement-single-test-contract

## User intent

- Move to strict TDD.
- Stop coders from changing tests after coding starts.
- Use one unified mechanism for all execution paths; avoid special-case logic.
- Prevent regressions caused by agents adjusting tests to fit code.

## Problem statement

Current behavior allows builders/fixers to edit tests in the same implementation lane, which weakens regression guarantees and blurs ownership boundaries.

## Desired outcome

One deterministic workflow where test intent is captured before implementation, approved, then treated as a locked contract during build/fix.
