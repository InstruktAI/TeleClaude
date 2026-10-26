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

**Name the mechanism.** State the root cause twice: the instance where this failure
occurred, and the mechanism that produced it. Write the mechanism as a code shape a reader
can confirm or reject at a single site by reading that site. A shape that reading one site
cannot decide is too broad; narrow it before searching.

When a governing design or decision record prescribes the mechanism, name that contract
beside it: the site then does what its design told it to, and the defect lives in the
decision as much as in the code.

**The family census is a lane that ends.** Its full extent is two searches: the diff of
the commit that introduced the mechanism, when provenance named one, and one search of the
codebase for the mechanism's shape. Each site found is recorded with one of three
readings: matching, not matching, or undecided. A matching site is in the family. The
census records it for whoever next owns that site; its reachability, likelihood, and impact
are not investigated, and a match is a lead, not evidence of a defect there
(`sdlc/concept/defect-evidence`, family site). A
not-matching site and a site that reading alone cannot decide stay out. Record the
searches run and every site found with its reading. A short census is a complete one.

**What a named commit touched beyond the mechanism is evidence, not scope.** Record it and
surface it for its own triage; the `preparation-artifact-quality` rule that evidence does
not reallocate ownership governs.

**Backward call-chain tracing:** When the bug manifests deep in the stack, trace backward to find the original trigger:

1. Observe the symptom (error, wrong value, unexpected state).
2. Find the immediate cause (which line, which function).
3. Ask: what called this? What value was passed?
4. Keep tracing up the call chain until you find where the bad value originated.
5. Fix at the source, not at the symptom.

If manual tracing is insufficient, add instrumentation before the problematic operation: log the arguments, `cwd`, environment variables, and `new Error().stack` to expose the full call chain.

**Operation outcome and failure handling.** Establish the operation's expected
outcome under the observed conditions from the applicable contract and the
reported concern. Distinguish a failure to meet that outcome from a defect in
reporting or handling it. Trace the causal dependencies needed to explain each
discrepancy; process and host boundaries do not themselves terminate that
trace. At an unavailable evidence boundary, state what is established and what
remains unknown.

Handling that controls execution, recovery, or resulting state participates in
the operation's causal chain. A presentation-only cause is sufficient only when
evidence establishes that the underlying outcome conforms to the contract
applicable to the observed conditions. A contract requiring an error to be
reported does not establish that the condition producing that error is
correct.

A shared error signature does not establish a shared cause. Evidence from a
different triggering condition supports a reported occurrence only to the
extent that their causal paths are established to coincide.

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
- If 3+ fix attempts fail, STOP. Do not attempt another fix. **First, scan external prior art**: is this a known class of problem with an established solution? Repeated failure against one surface usually means it is the wrong surface — the canonical pattern (reference implementations, current vendor documentation, comparable production architectures) resolves in minutes what local trial-and-error will not. Only then question the architecture: Is the pattern fundamentally sound? Are we persisting through inertia? Each fix revealing new problems in a different place is a signal that the premise is wrong, not the fix. Hold the residue the prior-art scan leaves genuinely unresolved and go idle with it (`general/principle/autonomy`) — never a question the scan would have answered.

### 5. Stop at the cause

The fix is the smallest change that removes the verified root cause, with scenario-bound tests where the project opts into them; every line of it traces to that cause.

What the investigation surfaces beyond the cause (a missing boundary validation, an unguarded dangerous operation) goes into the session's report: what it is, where, and how it surfaced. The session governing the work decides it under `sdlc/policy/todo-creation-discipline`, against the project that owns the code.

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
| Escalating a question a prior-art scan would answer   | Hands the human work the agent should have done   | Scan prior art first; hold only the unsolved residue        |
| "I don't fully understand but this might work"        | Partial understanding guarantees rework           | Say "I don't understand X" and investigate further          |
| Leaving reproduction scaffolding running              | Orphaned load/processes leak compute indefinitely | Spawn in a tracked group; reap in a guaranteed-cleanup path |
| "While I'm here" hardening around the fix             | Unscoped, unreviewed mutations ride the fix       | Fix the cause; report what else surfaced                    |

## See Also

- ~/.teleclaude/docs/sdlc/policy/testing.md — rule 16: correctness synchronizes on observable conditions, never on real-clock sleeps. The authoring constraint this procedure's timing-failure recovery applies.
