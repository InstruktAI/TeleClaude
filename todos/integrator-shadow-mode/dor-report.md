# DOR Report: integrator-shadow-mode

## Gate Verdict (formal)

### Gate 1: Intent & Success -- PASS

Problem and intended outcome are explicit: run singleton lease+queue integration
logic in shadow mode, record deterministic outcomes, perform zero canonical
`main` mutations. Seven success criteria are concrete and testable.

### Gate 2: Scope & Size -- PASS

Scope is atomic for this slice: shadow runtime only, no cutover, no blocked-flow
follow-up automation. Cross-cutting touches (DB schema via migration 024, daemon
background task wiring, next-machine regression) are explicitly called out and
justified. Fits a single focused AI session.

### Gate 3: Verification -- PASS

Verification path is explicit: unit tests for lease exclusivity and queue
FIFO/dedup, integration tests for shadow outcomes (`would_integrate`,
`would_block`, `superseded`), regression tests for finalize apply, operational
log checks via `instrukt-ai-logs`.

### Gate 4: Approach Known -- PASS

The approach builds on established codebase patterns:

1. Migration system (`teleclaude/core/migrations/`; next migration is 024).
2. Daemon background task wiring (`_queue_background_task`, `_track_background_task`).
3. Existing finalize lock pattern (`release_finalize_lock` in `core/next_machine/core.py`)
   as prior art for lease semantics.
4. Durable queue/outbox patterns used by notification outbox and hook outbox.

### Gate 5: Research Complete -- PASS (auto)

No new third-party tool/library integration.

### Gate 6: Dependencies & Preconditions -- PASS

`integration-events-model` dependency is properly tracked in `roadmap.yaml`
(field: `after: [integration-events-model]`). The interface contract that
shadow-mode consumes is fully specified in `project/spec/integration-orchestrator`:
canonical event fields, readiness predicate, queue semantics, and lease defaults.

The events-model's pending architectural decisions (`decide-branch-publish-source`,
`decide-finalize-event-write-surface`) concern implementation surface (where
events are written), not the readiness/projection interface consumed by
shadow-mode. The contract between the two slices is stable at the spec level.

This is a BUILD scheduling dependency (shadow-mode cannot build until
events-model delivers), not a DOR readiness gap.

### Gate 7: Integration Safety -- PASS

Shadow mode is explicitly additive and observation-only. Entry/exit boundaries
are explicit (config-toggleable shadow runtime, no cutover in this slice).
Rollback is containment-first: disable shadow runtime, retain existing finalize
path. Legacy finalize apply behavior is preserved per requirement R6.

### Gate 8: Tooling Impact -- PASS (auto)

No scaffolding/tooling procedure changes required.

### Plan-to-Requirement Fidelity -- PASS

All requirements trace cleanly to plan tasks:

| Requirement                            | Plan tasks              |
| -------------------------------------- | ----------------------- |
| R1 (shadow runtime lifecycle)          | 1.1, 1.3                |
| R2 (singleton lease + durable queue)   | 1.2, 1.3, 2.1           |
| R3 (readiness and supersession parity) | 1.3, 1.4, 2.1           |
| R4 (shadow-only execution contract)    | 1.1, 1.2, 1.3, 2.1, 2.2 |
| R5 (observability and audit trail)     | 1.2, 1.3, 1.4, 2.2      |
| R6 (legacy path containment)           | 1.1, 1.5, 2.1           |
| R7 (verification coverage)             | 2.1, 2.2, 2.3           |

No contradictions between plan and requirements. Plan respects
`project/policy/single-database`, `project/policy/adapter-boundaries`, and
`project/policy/data-modeling`.

## Score: 8/10

Status: `pass`

## Resolved Blockers

1. ~~Formal gate phase has not run~~ -- completed in this assessment.
2. ~~integration-events-model dependency unclear~~ -- dependency is BUILD-scheduling,
   not DOR-readiness. Interface contract is stable at spec level.

## Assumptions

1. `integration-events-model` will expose stable projection access for
   `review_approved`, `finalize_ready`, `branch_pushed`, and supersession checks
   per `project/spec/integration-orchestrator`.
2. Shadow persistence lives in the existing single database file without violating
   `project/policy/single-database`.
3. Existing finalize contract tests remain authoritative for pre-cutover regression
   detection.

## Open Questions (non-blocking)

1. Minimum parity window/threshold for shadow-to-cutover promotion
   (`integrator-cutover` scope, not this slice).
2. Retention period for shadow outcome records used in parity analysis
   (can be decided during implementation or deferred to cutover).
