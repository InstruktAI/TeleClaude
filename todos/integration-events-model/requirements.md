# Requirements: integration-events-model

## Goal

Persist canonical integration-readiness events and maintain a durable readiness
projection for candidates `(slug, branch, sha)` so later integrator slices can
consume deterministic readiness state instead of transcript-only evidence.

## Why

Current finalize/review signals are split across `state.yaml`, worker
transcripts, and ad-hoc git checks. Without a normalized event model, queue +
lease orchestration cannot be introduced safely in `integrator-shadow-mode`.

## Scope

### In scope

1. Durable persistence for canonical integration events:
   - `review_approved`
   - `finalize_ready`
   - `branch_pushed`
2. Readiness projection for `(slug, branch, sha)` that evaluates the predicate
   from `docs/project/spec/integration-orchestrator.md`.
3. Wiring event recording to existing lifecycle seams (review approval,
   finalize-ready consumption, successful branch push).
4. Internal read API for diagnostics/tests to inspect projection state and
   missing readiness conditions.

### Out of scope

1. Singleton lease acquisition and queue draining runtime (`integrator-shadow-mode`).
2. Integrator-only canonical `main` authority cutover (`integrator-cutover`).
3. `integration_blocked` follow-up todo creation/resume UX (`integration-blocked-flow`).
4. Replacing the finalize safety gates delivered in `integration-safety-gates`.

## Functional Requirements

### FR1: Canonical Event Schema

1. The model MUST persist event records with canonical fields from
   `docs/project/spec/integration-orchestrator.md`.
2. Required fields MUST be validated per event type:
   - `review_approved`: `slug`, `approved_at`, `review_round`, `reviewer_session_id`
   - `finalize_ready`: `slug`, `branch`, `sha`, `worker_session_id`, `orchestrator_session_id`, `ready_at`
   - `branch_pushed`: `branch`, `sha`, `remote`, `pushed_at`, `pusher`
3. Persistence MUST be append-only and replay-safe (idempotent on duplicate
   event identity keys).

### FR2: Deterministic Emission Points

1. `review_approved` MUST be emitted when `telec todo mark-phase <slug> --phase review --status approved`
   succeeds.
2. `finalize_ready` MUST be emitted only after orchestrator consumption of
   worker evidence `FINALIZE_READY: <slug>`.
3. `branch_pushed` MUST be emitted only after a successful push of the
   candidate branch/sha to the configured remote.

### FR3: Readiness Projection

1. Projection MUST evaluate readiness for candidate `(slug, branch, sha)` using:
   - required events present,
   - branch/sha alignment with `finalize_ready`,
   - remote reachability,
   - no superseding newer `finalize_ready` for same slug,
   - candidate sha not already in `origin/main`.
2. Projection MUST expose `READY` vs `NOT_READY` plus machine-readable missing
   predicates/reasons for each candidate.

### FR4: Supersession and Deduplication

1. Newer `finalize_ready` for the same slug MUST supersede older candidate tuples.
2. Repeated event ingestion MUST NOT duplicate ready queue transitions for the
   same `(slug, branch, sha)`.

### FR5: Integration-Safe Incremental Delivery

1. The slice MUST be mergeable independently without enabling singleton
   integrator execution yet.
2. Existing finalize safety checks and lock behavior MUST remain intact.

## Success Criteria

- [ ] Canonical event persistence exists for `review_approved`, `finalize_ready`, `branch_pushed`
- [ ] Event records are validated and idempotent for replay/duplicates
- [ ] Projection computes `READY`/`NOT_READY` for `(slug, branch, sha)` with explicit missing reasons
- [ ] Superseding `finalize_ready` invalidates older candidates for same slug
- [ ] Remote reachability and `origin/main` already-integrated checks are included in readiness logic
- [ ] Deterministic emission points are wired into review/finalize/push lifecycle seams
- [ ] Unit tests cover positive/negative/superseded/idempotency scenarios
- [ ] Existing finalize safety-gate behavior remains green

## Constraints

1. Must comply with `docs/project/policy/single-database.md` (use canonical
   `teleclaude.db`; no side databases in main repo).
2. No new third-party dependencies.
3. Preserve adapter/core boundaries from `docs/project/policy/adapter-boundaries.md`.
4. Do not require daemon/service restarts just to validate unit-level behavior.

## Dependencies & Preconditions

1. `integration-safety-gates` remains delivered and is the required predecessor.
2. Canonical orchestrator finalize flow (`next-finalize` post-completion) stays
   the source for finalize/push evidence handoff.
3. Branch and remote metadata are available at the point where
   `finalize_ready`/`branch_pushed` are recorded.

## Risks

1. **Event drift risk**: field mismatch vs orchestrator spec could invalidate readiness.
2. **False readiness risk**: incomplete branch/sha alignment checks could enqueue wrong candidates.
3. **Operational drift risk**: if finalize instructions and event recording diverge,
   projection accuracy degrades.

## Research

No third-party tooling or new external integration is introduced.
`Research complete` gate is automatically satisfied.
