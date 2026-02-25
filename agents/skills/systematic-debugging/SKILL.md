---
name: systematic-debugging
description: 4-phase root cause debugging methodology. Use when encountering bugs, test failures, or unexpected behavior before proposing fixes.
---

# Systematic Debugging

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

1. **Reproduce**

- Capture exact steps, inputs, environment, and outputs.
- Reproduce consistently before changing code.
- Read full error messages and stack traces; preserve exact details.
- If reproduction is unstable, add instrumentation and gather more evidence.

2. **Bisect**

- Narrow where behavior diverges by comparing known-good and failing paths.
- Use commits, config differences, and boundary-level tracing to isolate the first bad value or violated invariant.
- Validate each step with concrete values, not assumptions.

3. **Isolate**

- Form one falsifiable hypothesis: "Failure occurs because X under Y conditions."
- Run one minimal test or probe to validate it.
- Change one variable at a time.
- If hypothesis fails, reset and form a new one; do not stack guesses.

4. **Fix**

- Write or update a failing test that captures the failure path.
- Implement the smallest change that addresses root cause.
- Verify with targeted tests and relevant project checks.
- If repeated attempts fail, reassess architecture assumptions instead of continuing random patches.

Anti-patterns to reject:

| Anti-pattern                       | Why it fails                             | Correct behavior                  |
| ---------------------------------- | ---------------------------------------- | --------------------------------- |
| "Quick fix now, investigate later" | Locks in symptom hacks                   | Investigate first, then fix       |
| "Looks right" validation           | Surface checks miss bad states           | Trace concrete values end to end  |
| Multiple fixes at once             | No causal signal, higher regression risk | One hypothesis, one change        |
| Trusting comments over behavior    | Comments drift from reality              | Verify comments against execution |
| "Probably" under pressure          | Confidence without evidence              | Require reproduced evidence       |
