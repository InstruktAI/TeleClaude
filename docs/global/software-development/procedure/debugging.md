---
description: 'Systematic debugging methodology: reproduce, bisect, isolate, fix, harden. Evidence before fixes, root cause before symptoms.'
id: 'software-development/procedure/debugging'
scope: 'domain'
type: 'procedure'
---

# Debugging — Procedure

## Goal

Find root cause before proposing or implementing fixes. Prevent guess-driven changes that hide symptoms and create regressions.

Core rules:

- Never guess.
- Never patch symptoms before tracing cause.
- Never bundle multiple speculative fixes in one attempt.

## Preconditions

- Observed failure evidence: error output, failing tests, logs, or reproducible behavior.
- Current implementation context and recent change history accessible.
- Reproduction steps available, or explicit note that reproduction is not yet stable.

## Steps

### 1. Reproduce

- Capture exact steps, inputs, environment, and outputs.
- Reproduce consistently before changing any code.
- Read full error messages and stack traces; preserve exact details.
- If reproduction is unstable, add instrumentation and gather more evidence before proceeding.

**Multi-component systems:** When the system has multiple components (CI → build → signing, API → service → database), add diagnostic instrumentation at each component boundary before proposing fixes:

- Log what data enters and exits each component.
- Verify environment and config propagation across boundaries.
- Run once to gather evidence showing WHERE it breaks.
- Then investigate that specific component — not the whole system.

### 2. Bisect

- Narrow where behavior diverges by comparing known-good and failing paths.
- Use commits, config differences, and boundary-level tracing to isolate the first bad value or violated invariant.
- Validate each step with concrete values, not assumptions.

**Backward call-chain tracing:** When the bug manifests deep in the stack, trace backward to find the original trigger:

1. Observe the symptom (error, wrong value, unexpected state).
2. Find the immediate cause (which line, which function).
3. Ask: what called this? What value was passed?
4. Keep tracing up the call chain until you find where the bad value originated.
5. Fix at the source, not at the symptom.

If manual tracing is insufficient, add instrumentation before the problematic operation: log the arguments, `cwd`, environment variables, and `new Error().stack` to expose the full call chain.

### 3. Isolate

- Form one falsifiable hypothesis: "Failure occurs because X under Y conditions."
- Run one minimal test or probe to validate it.
- Change one variable at a time.
- If the hypothesis fails, reset and form a new one. Do not stack guesses.

### 4. Fix

- Write or update a failing test that captures the failure path.
- Implement the smallest change that addresses root cause.
- Verify with targeted tests and relevant project checks.

**Fix-count escalation:**

- After each failed fix attempt, return to Step 1 and re-analyze with new evidence.
- If 3+ fix attempts fail, STOP. Do not attempt another fix. Question the architecture instead: Is the pattern fundamentally sound? Are we persisting through inertia? Each fix revealing new problems in a different place is a signal that the premise is wrong, not the fix. Discuss with the human before continuing.

### 5. Harden

After a successful fix, make the bug structurally impossible by adding validation at every layer the data passes through:

1. **Entry point** — Reject obviously invalid input at API boundaries (empty strings, missing required fields, wrong types).
2. **Business logic** — Validate that data makes sense for the specific operation (non-empty path for file operations, valid state for transitions).
3. **Environment guards** — Prevent dangerous operations in specific contexts (refuse destructive ops outside temp directories in tests, refuse prod operations in dev mode).
4. **Instrumentation** — Log context before dangerous operations for forensics (arguments, cwd, stack trace, environment).

Each layer catches what the others miss. A single validation point feels sufficient but gets bypassed by different code paths, refactoring, or mocks.

## Outputs

- Root cause statement linked to concrete evidence.
- Minimal fix scoped to the verified cause.
- Verification evidence showing failure reproduced and then resolved.
- Brief note of remaining uncertainty or follow-up checks.

## Recovery

- If hypothesis fails, discard it cleanly and form a fresh one without carrying forward assumptions.
- If stuck after two hypothesis cycles, step back and audit the architectural assumption that frames the problem. The premise may be wrong.

**Condition-based waiting:** When failures are timing-dependent (flaky tests, race conditions), replace arbitrary timeouts with condition polling:

- Wait for the actual condition you care about, not a guess about how long it takes.
- Always include a timeout with a clear error message.
- If an arbitrary timeout is genuinely needed (testing timed behavior like debounce), document WHY and base it on known intervals, not guesses.

Anti-patterns to reject:

| Anti-pattern | Why it fails | Correct behavior |
| --- | --- | --- |
| "Quick fix now, investigate later" | Locks in symptom hacks | Investigate first, then fix |
| "Looks right" validation | Surface checks miss bad states | Trace concrete values end to end |
| Multiple fixes at once | No causal signal, higher regression risk | One hypothesis, one change |
| Trusting comments over behavior | Comments drift from reality | Verify comments against execution |
| "Probably" under pressure | Confidence without evidence | Require reproduced evidence |
| "Just try changing X" | Guess-driven; no understanding | Form hypothesis, test minimally |
| Proposing fixes before tracing data flow | Treats symptoms, not cause | Complete Steps 1-3 before Step 4 |
| "One more fix attempt" after 2+ failures | Diminishing returns, wrong premise | Stop at 3, question architecture |
| "I don't fully understand but this might work" | Partial understanding guarantees rework | Say "I don't understand X" and investigate further |
