# Implementation Plan: project-aware-bug-routing

## Overview

- Build one routing-first bug flow with minimal process overhead.
- Keep normal flow untouched unless slug starts with `bug-`.
- Make each bug handling cycle atomic: fix -> independent review -> pass/fail.

## Phase 1: Route Split

### Task 1.1: Prefix route selector

- [ ] Add a single route decision point:
  - `bug-*` => bug route
  - everything else => existing route
- [ ] Ensure normalized slug parsing so route decision is deterministic.

### Task 1.2: Bug intake routing

- [ ] Keep bug intake usable without mandatory project-name input.
- [ ] Support explicit TeleClaude override flag.
- [ ] Reuse one shared routing resolution so intake and runner cannot drift.

## Phase 2: Atomic Bug Loop

### Task 2.1: Fix step

- [ ] Runner picks one bug and marks it in progress atomically.
- [ ] Dispatch fixer session for that bug scope only.
- [ ] Capture produced commit identifier for review.

### Task 2.2: Independent review step

- [ ] Dispatch reviewer in a different session/identity from fixer.
- [ ] Reviewer evaluates only the bug diff/commit scope.
- [ ] Record verdict as `pass` or `needs_fix` with short reason.

### Task 2.3: Retry behavior

- [ ] On `needs_fix`, dispatch another fixer attempt (not same reviewer).
- [ ] Increment attempt counter and repeat review.
- [ ] Enforce retry ceiling with deterministic fallback to `needs_human`.

## Phase 3: Landing Safety

### Task 3.1: Landing guardrails

- [ ] Prevent completion/landing without explicit review `pass`.
- [ ] Prevent self-approval paths.
- [ ] Keep landing path safe and serialized according to existing mainline policy.

### Task 3.2: Blocked bug handling

- [ ] Mark exhausted/conflicted items as `needs_human`.
- [ ] Write blocked items to one simple human-facing report.
- [ ] Continue processing remaining bugs instead of stalling the runner.

## Phase 4: State Contract

### Task 4.1: Minimal state fields

- [ ] Persist per-bug: status, attempt, fixer identity, reviewer identity, commit, verdict, reason, timestamp.
- [ ] Write state transitions atomically to avoid racey or partial outcomes.

### Task 4.2: Operational visibility

- [ ] Expose concise status signals suitable for operators and follow-up automation.
- [ ] Ensure repeated runs resume correctly from persisted state.

## Phase 5: Validation

### Task 5.1: Targeted tests

- [ ] Route split test: `bug-*` vs non-`bug-*`.
- [ ] Guard test: reviewer must differ from fixer.
- [ ] Guard test: no landing without review pass.
- [ ] Retry test: failed review loops to another fixer and eventually `needs_human` at limit.
- [ ] Intake test: no mandatory project-name requirement + TeleClaude override behavior.

### Task 5.2: Documentation updates

- [ ] Document bug route behavior and atomic fix/review contract.
- [ ] Document blocked-items report semantics and operator expectations.
