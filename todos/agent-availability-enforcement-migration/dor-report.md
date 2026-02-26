# DOR Report: agent-availability-enforcement-migration

## Draft Assessment (not a formal gate verdict)

### Gate 1: Intent & Success — PASS

The problem statement is explicit (unavailable agents still launching), the
outcome is explicit (single routable-agent policy), and success criteria are
testable across concrete runtime surfaces.

### Gate 2: Scope & Size — PASS (cross-cutting but bounded)

This is intentionally cross-surface (API, daemon, adapters, cron, CLI) because
the regression is cross-surface. Scope is still bounded to one behavior
contract: runtime agent routing enforcement.

### Gate 3: Verification — PASS

Verification path is concrete:

1. targeted unit tests across migrated files
2. end-to-end CLI behavior checks (explicit and implicit selection)
3. daemon log assertions for rejection observability

### Gate 4: Approach Known — PASS (with one policy decision)

The technical path is known and grounded in existing code:

1. availability data source already exists (`db.get_agent_availability`)
2. launch/restart seams are known from `input.md` and validated against code
3. existing helper behavior in `helpers/agent_cli.py::_pick_agent` provides
   proven selection semantics to align runtime code with

One decision remains unresolved: degraded semantics (A/B/C).

### Gate 5: Research Complete — PASS (auto)

No third-party integrations or dependencies are introduced.

### Gate 6: Dependencies & Preconditions — NEEDS DECISION

A hard policy decision is still open and must be locked before implementation:

1. degraded selection semantics (option A, B, or C)

### Gate 7: Integration Safety — PASS

The migration is incremental and merge-safe:

1. central helper can land first
2. call sites can migrate in batches while retaining existing command contracts
3. behavior change is constrained to rejecting non-routable agents

### Gate 8: Tooling Impact — PASS (auto)

No scaffolding/tooling procedure change is required.

## Assumptions

1. Existing availability table and APIs remain authoritative for runtime routing.
2. Mapper default behavior can be safely deferred to runtime handler resolution.
3. Adapter-specific launch flows can consume central routing without UI redesign.

## Open Questions

1. Which degraded policy option should be canonical (A, B, or C)?

## Draft Score

- Score: `6/10`
- Status: `needs_decision`

## Draft Blockers

1. Degraded policy semantics must be selected and locked before build dispatch.
