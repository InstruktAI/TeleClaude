# Input: integration-safety-gates

## Step objective

Introduce immediate guardrails in the existing orchestrator/finalize path to
prevent unsafe apply attempts while preserving the current lifecycle.

## Scope

- Add pre-finalize gate(s) that fail fast when canonical `main` is unsuitable
  for safe apply (dirty working tree and/or problematic divergence state).
- Ensure finalize/apply instructions surface explicit, actionable blocker
  reasons for the orchestrator.
- Keep behavior changes minimal and backward compatible with current workflow.

## Out of scope

- Event persistence model (`review_approved`, `finalize_ready`, `branch_pushed`)
- Integrator queue/lease runtime
- Cutover of merge ownership to a new integrator role
- Blocked-flow UX automation

## Why now

This reduces immediate regression risk in parallel delivery while later slices
introduce the full event-driven singleton integrator architecture.
