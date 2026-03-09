# Input: test-suite-ownership-reset

## User intent

- Stop regression ping-pong caused by unclear test ownership and stale expectations.
- Keep functional/integration coverage while restructuring unit tests for predictability.
- Enforce deterministic test accountability from changed code paths.

## Problem statement

Current tests are hard to map to changed source files, so agents can ship behavior changes without clearly updating the right tests. This creates regressions and repeated reversions.

## Desired outcome

A straightforward testing model where each Python source file has an obvious owning unit test file, functional tests remain the safety net, and commit/checkpoint gates can deterministically require the correct tests for changed paths.
