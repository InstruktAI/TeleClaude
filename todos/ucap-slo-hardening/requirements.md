# Requirements - ucap-slo-hardening

## Goal

Harden the unified adapter pipeline with production-grade observability, SLO-based delivery
monitoring, and observer lane retry policies before broad production rollout.

## Scope

### In scope

- Structured metrics for output delivery success/failure per adapter.
- SLO thresholds for UI adapter delivery rate (percentage-based, rolling window).
- Observer lane retry policy for transient failures on non-origin UI adapters.
- Alerting integration for SLO breach detection.

### Out of scope

- Changes to the core routing contract (AdapterClient invariants).
- New adapter types.

## Success Criteria

- [ ] Delivery metrics are emitted and queryable per adapter, per session.
- [ ] SLO threshold ≥99% delivery rate per UI adapter is defined and alerting is wired.
- [ ] Observer retry policy is implemented and covered by tests.
- [ ] No regression in existing UCAP test suite.

## Constraints

- Must not modify the core routing contract (AdapterClient.\_route_to_ui, \_broadcast_to_ui_adapters).
- Must not affect origin adapter fail-fast behavior.

## Risks

- Retry policy on observer lane may mask persistent failures if not bounded (max 1 retry).
- Metrics overhead on high-throughput sessions: instrument async, not inline.

## Background

Follows from `ucap-cutover-parity-validation` pilot. Pilot used lightweight criteria
(no missing outputs, ≤1 duplicate per session). This todo promotes to production-grade
SLOs required before broad rollout. Production rollout must not precede this todo.
