---
id: principles/architecture/boundary-purity
type: principles
scope: project
description: Preserve domain intent at system boundaries by isolating transport and UI concerns from core logic.
requires:
  - ../../../architecture.md
---

Principle
- Core logic expresses intent in domain terms, never in transport or UI terms.

Rationale
- Boundary purity keeps the core portable across adapters and transports.
- Coupling domain intent to a specific interface makes the system brittle and harder to evolve.

Implications
- Adapters translate external inputs into explicit internal commands at the boundary.
- Core emits domain events; distribution is handled outside core without leaking transport details back in.
- Domain decisions and policies are expressed in core, not in adapter-specific conditionals.

Tensions
- Convenience shortcuts that embed UI or transport metadata in core logic violate this principle.
- When the boundary translation is unclear, prefer adding explicit command or event types over leaking interface details.
