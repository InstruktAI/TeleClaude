# Input: integration-orchestrator-rollout

## Goal

Adopt an event-driven singleton integrator model so parallel work can continue at
high throughput while canonical `main` integration remains serialized, auditable,
and low-risk.

## Rollout shape

Implement in five ordered slices:

1. `integration-safety-gates`
2. `integration-events-model`
3. `integrator-shadow-mode`
4. `integrator-cutover`
5. `integration-blocked-flow`

## Operating constraints

- Local-first development remains the default.
- Workers may continue using worktrees/feature branches.
- Canonical `main` merges/pushes should be integration-owned.
- Avoid big-bang changes; each slice should be shippable and verifiable.
