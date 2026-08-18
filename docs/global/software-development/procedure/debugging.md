---
activation_trigger: 'Use when you encounter a bug, test failure, or unexpected behavior'
description: 'Systematic debugging methodology: reproduce, bisect, isolate, fix. Evidence before fixes, root cause before symptoms, and no hardening beyond the verified cause.'
visibility: 'public'
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
- Reproduction scaffolding is ephemeral: tear down every process, background load, server, or container the reproduction spawns the instant its evidence is captured. Spawn it in a tracked group and reap it in a guaranteed-cleanup path (`trap` / `finally` / process-group kill) — never as detached children that outlive the session. Load generators (CPU saturation, concurrency, `-n auto` contention) leak compute indefinitely once orphaned.

**Multi-component systems:** When the system has multiple components (CI → build → signing, API → service → database), add diagnostic instrumentation at each component boundary before proposing fixes:

- Log what data enters and exits each component.
- Verify environment and config propagation across boundaries.
- Run once to gather evidence showing WHERE it breaks.
- Then investigate that specific component — not the whole system.

### 2. Bisect

- Narrow where behavior diverges by comparing known-good and failing paths.
- Use commits, config differences, and boundary-level tracing to isolate the first bad value or violated invariant.
- Validate each step with concrete values, not assumptions.

**Provenance check (unconditional — every bug, before mechanism analysis):** A bug's
first question is _since when is this reachable_. The trigger is that the artifact is a
bug, never the reporter's phrasing.

1. Identify the files involved in the failing path.
2. Anchor on the mechanism: `git log --oneline -S<symbol> -- <files>`, or `-G<pattern>`
   for a shape rather than a symbol, to find where it entered. This is the cheap move and
   it settles most bugs.
3. If the anchor does not settle it, run one range scan — `git log --oneline -- <files>`
   over the window the symptom makes plausible.
4. For each candidate commit, `git diff <commit>^..<commit> -- <files>` to inspect
   exactly what changed.
5. Cross-reference each diff against the failure: does it explain the broken behavior,
   or does it explain why the behavior became reachable?
6. Record the outcome as exactly one of the three verdicts below.

**The three provenance verdicts.** Each carries its own evidence; none is satisfied by
assertion:

- **Regression** — a commit turned working behavior into the failure. Name it and quote
  the diff hunk that did it. The fix targets that change, never a workaround elsewhere.
- **Latent** — the mechanism was always wrong and something made it newly reachable.
  Name both halves with the same evidence Regression carries: the commit that introduced
  the mechanism, and the change that opened the path to it. Treat the reachability change
  as a regression in the reachability path.
- **Provenance not established** — the search ran and did not settle it. Record what was
  searched: which files, which commit range, which pathspecs and `-S`/`-G` terms.

**Provenance is a lane that ends.** The anchor and one range scan are its full extent. A
search that has run both without settling records **Provenance not established** and moves
on to mechanism analysis. That verdict is the scheduled exit, not a confession, and
reaching it costs the diagnosis nothing — the mechanism is still found, and the recorded
search tells the next reader where not to look again. Widening the range until some commit
appears is not diligence; it is this lane spending hours that belong to the fix.

**Supplied commits are candidates, not the boundary of the search.** Test a driver's
candidate commits inside the first-bad search. Eliminating every supplied candidate does
not complete the provenance check; run the search whether or not they survive.

**A named commit's siblings are evidence, not scope.** Record what else a named commit
touched and surface it for its own triage. It never widens the present fix; the
`preparation-artifact-quality` rule that evidence does not reallocate ownership governs.

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
- If 3+ fix attempts fail, STOP. Do not attempt another fix. **First, scan external prior art**: is this a known class of problem with an established solution? Repeated failure against one surface usually means it is the wrong surface — the canonical pattern (reference implementations, current vendor documentation, comparable production architectures) resolves in minutes what local trial-and-error will not. Only then question the architecture: Is the pattern fundamentally sound? Are we persisting through inertia? Each fix revealing new problems in a different place is a signal that the premise is wrong, not the fix. Escalate to the human only the residue the prior-art scan leaves genuinely unresolved — never a question the scan would have answered.

### 5. Stop at the cause — hardening is new scope

The fix ends at the smallest change that removes the verified root cause, plus the test that proves it gone. Validation layers, guards, defensive defaults, fallbacks, or extra instrumentation beyond that are new scope, never part of the fix.

When the investigation surfaces a structural weakness worth closing (a missing boundary validation, an unguarded dangerous operation), record it as a deferral or file a new todo (`telec todo create` / `telec bugs report`) citing the evidence, against the project that owns the code per `software-development/policy/todo-creation-discipline`. The human decides whether that work happens; it never rides the fix.

A bug report is a handoff. Its reporter owns the `input` and may keep revising it while the bug is unclaimed — observations, findings, hypotheses and corrections all belong there. The `investigation` and `diagnosis` artifacts belong to the diagnose phase; a reporter never writes them. Reporter conclusions travel inside the input as evidence and leads.

Remove all diagnostic instrumentation added during Steps 1–3 before committing; keep a log line only where the logging policy independently justifies it.

## Outputs

- Root cause statement linked to concrete evidence.
- Minimal fix scoped to the verified cause.
- Verification evidence showing failure reproduced and then resolved.
- Brief note of remaining uncertainty or follow-up checks.

## Recovery

- If hypothesis fails, discard it cleanly and form a fresh one without carrying forward assumptions.
- If stuck after two hypothesis cycles, step back and scan external prior art before auditing further: this class of problem may already be solved, and the failing hypotheses may be fighting a canonical mechanism rather than a local bug. Then audit the architectural assumption that frames the problem. The premise may be wrong.

**Timing-dependent failures (flaky tests, race conditions).** A failure that surfaces only under load and passes in isolation usually means correctness is coupled to a real-clock margin — a fixed sleep or a shrunk timeout raced against event-loop scheduling that parallel contention perturbs. Trace it to that coupling, then remove it by synchronizing on the observable condition rather than a guessed delay. The constraint governing how code and tests must do this — and why real-time-coupled tests flake under parallel load — lives in the testing policy (see `## See Also`).

Anti-patterns to reject:

| Anti-pattern                                          | Why it fails                                      | Correct behavior                                            |
| ----------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------- |
| "Quick fix now, investigate later"                    | Locks in symptom hacks                            | Investigate first, then fix                                 |
| "Looks right" validation                              | Surface checks miss bad states                    | Trace concrete values end to end                            |
| Multiple fixes at once                                | No causal signal, higher regression risk          | One hypothesis, one change                                  |
| Trusting comments over behavior                       | Comments drift from reality                       | Verify comments against execution                           |
| "Probably" under pressure                             | Confidence without evidence                       | Require reproduced evidence                                 |
| "Just try changing X"                                 | Guess-driven; no understanding                    | Form hypothesis, test minimally                             |
| Proposing fixes before tracing data flow              | Treats symptoms, not cause                        | Complete Steps 1-3 before Step 4                            |
| "One more fix attempt" after 2+ failures              | Diminishing returns, wrong premise                | Stop at 3, scan prior art, then question architecture       |
| Deeper local trial-and-error on an unfamiliar problem | Reinvents a solved mechanism — fragile and slow   | Scan reference implementations before building              |
| Escalating a question a prior-art scan would answer   | Hands the human work the agent should have done   | Scan prior art first; escalate only the unsolved residue    |
| "I don't fully understand but this might work"        | Partial understanding guarantees rework           | Say "I don't understand X" and investigate further          |
| Leaving reproduction scaffolding running              | Orphaned load/processes leak compute indefinitely | Spawn in a tracked group; reap in a guaranteed-cleanup path |
| "While I'm here" hardening around the fix             | Unscoped, unreviewed mutations ride the fix       | Fix the cause only; defer or file structural work           |

## See Also

- ~/.teleclaude/docs/software-development/policy/testing.md — rule 16: correctness synchronizes on observable conditions, never on real-clock sleeps. The authoring constraint this procedure's timing-failure recovery applies.
