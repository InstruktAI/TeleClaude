---
name: systematic-debugging
description: 4-phase root cause debugging methodology. Use when encountering bugs, test failures, or unexpected behavior before proposing fixes.
---

# Systematic Debugging

## Required reads

- @~/.teleclaude/docs/software-development/procedure/root-cause-debugging.md

## Purpose

Find root cause before proposing or implementing fixes. Prevent guess-driven changes that hide symptoms and create regressions.

## Scope

Apply to technical failures such as test failures, runtime bugs, build issues, integration problems, and performance regressions.

Core rules:

- Never guess.
- Never patch symptoms before tracing cause.
- Never bundle multiple speculative fixes in one attempt.

## Inputs

- Observed failure evidence: error output, failing tests, logs, or reproducible behavior.
- Current implementation context and recent change history.
- Reproduction steps, or explicit note that reproduction is not yet stable.

## Outputs

- Root cause statement linked to concrete evidence.
- Minimal fix scoped to the verified cause.
- Verification evidence showing failure reproduced and then resolved.
- Brief note of remaining uncertainty or follow-up checks.

## Procedure

Follow the four-phase root cause debugging procedure (Reproduce → Bisect → Isolate → Fix). Full steps and anti-patterns are in the required reads above.
