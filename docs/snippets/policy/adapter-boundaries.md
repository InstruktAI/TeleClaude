---
id: policy/adapter-boundaries
type: policy
scope: project
description: Strict separation between UI/Transport adapters and core logic.
---

## Rule

- Adapters normalize external inputs into explicit command objects before entering core logic.
- Adapter-specific types and APIs do not enter the core.
- Adapter/core interaction happens through defined Python Protocols only.
- Feedback cleanup is performed only by the adapter that originated the request.
- Outbound UI adapter traffic is fire-and-forget; adapters broadcast but never block callers.

## Rationale

- Keeps the core testable, stable, and platform-agnostic.
- Prevents external API churn from leaking into domain logic.

## Scope

- Applies to all UI and transport adapters and their integration points with the core.

## Enforcement or checks

- Review adapter code for boundary violations (raw external types in core paths).
- Enforce protocol-based interfaces at adapter/core boundaries.

## Exceptions or edge cases

- None; boundary violations are treated as regressions.
