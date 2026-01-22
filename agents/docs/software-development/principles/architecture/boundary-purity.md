---
id: software-development/principles/architecture/boundary-purity
type: principles
scope: domain
description: Preserve domain intent by isolating transport and UI concerns from core logic.
---

Principle

- Core logic expresses intent in domain terms, never in transport or UI terms.

Rationale

- Boundary purity keeps the core portable across adapters and transports.
- Coupling domain intent to a specific interface makes the system brittle.
- Clear seams allow independent evolution of UI, transport, and domain logic.

Implications

- Boundary translation happens at the edge; core remains interface-agnostic.
- Domain policies live in core, not in adapter-specific conditionals.
- Core types represent domain meaning, not presentation formats.
- Errors are expressed in domain language and mapped at the boundary.
