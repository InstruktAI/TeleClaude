# Integrate Session Lifecycle into Next Work

## Context

The next-prepare command already implements the session lifecycle principle (self-termination, direct conversation for needs_work, signal sessions, artifact verification). The next-work orchestration command has none of this — it's a bare orchestration loop that always re-dispatches fresh workers for each phase, losing context and creating churn.

## What we want

### 1. Direct conversation for review friction

When review returns REQUEST CHANGES, instead of the current pattern (end builder, dispatch reviewer, end reviewer, dispatch fix worker — context-destroying churn):

- Keep both the reviewer and builder sessions alive
- The orchestrator instructs both to establish a direct link with each other via `telec sessions send <peer_session_id> --direct` (one-time, idempotent)
- They iterate together with mutual observability — reviewer has the assessment, builder has the implementation context
- Heartbeat keeps the orchestrator aware without chattiness
- When they converge, the orchestrator reads the result and ends both

This eliminates context loss that causes multi-round review loops over trivial issues.

### 2. Automated artifact verification gate

Artifact verification should be a mechanical CLI gate, not an AI reasoning task. Something like `telec todo verify-artifacts <slug> --phase build` that checks:

- Expected phase artifacts were committed (git log verification)
- state.yaml fields are consistent
- review-findings.md, bug.md etc. are present and non-placeholder

This runs as part of `telec todo work` automatically before the orchestrator sees the result. The AI never touches it — it either passes or the state machine reports what's missing.

### 3. Session lifecycle awareness

- Add `general/principle/session-lifecycle` to next-work's required reads
- The orchestrator's job stays clean: dispatch, wait, read verdict, manage sessions, next phase
- Orchestrator always ends children (non-negotiable)
- Signal concept for non-recoverable errors requiring human attention

## What we explicitly don't want

- Self-terminating workers (orchestrator always ends children)
- Reading from dead/closed sessions
- AI doing repetitive verification work that can be automated
- Multiple `--direct` sends between the same pair (one-time link establishment only)
