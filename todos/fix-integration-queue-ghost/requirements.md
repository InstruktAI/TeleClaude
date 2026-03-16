# Requirements: fix-integration-queue-ghost

## Goal

Fix the integration pipeline so that finalized candidates are discovered and merged by the
integrator state machine. The current state-driven scanner skips `handed_off` candidates
that are younger than the lease TTL, making every candidate invisible to the integrator
that the event chain spawns.

## Scope

### In scope

- Remove `IntegrationQueue` enqueue from daemon wiring (`_build_integration_trigger`)
- Make the worktree scanner accept `handed_off` candidates unconditionally (the lease
  prevents concurrent processing; the TTL guard is redundant)
- Update tests for changed scanner and daemon behavior

### Out of scope

- Removing `IntegrationQueue` class or shadow runtime (still referenced by tests)
- Removing `IntegrationTriggerCartridge` (still needed for spawn callback)
- Changes to the `ReadinessProjection` (observability value, no harm)

## Success Criteria

- [ ] Integrator state machine finds `handed_off` candidates when scanning worktrees
- [ ] Daemon no longer enqueues into `queue.json`
- [ ] Existing integration tests pass
- [ ] `fix-ci-release-credentials` can be integrated after this fix lands

## Constraints

- Must not break the spawn/wake path — the event chain must still trigger the integrator
- Must not break the lease-based concurrency guard

## Risks

- Shadow runtime tests may need mock adjustments if queue behavior changes
