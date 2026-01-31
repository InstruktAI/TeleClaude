---
id: project/policy/adapter-boundaries
type: policy
scope: project
description: Strict separation between adapters and core logic.
---

# Adapter Boundaries — Policy

## Rules

- Adapters normalize external inputs into explicit command objects before entering core logic.
- Adapter-specific types and APIs do not enter the core.
- Feedback cleanup is performed only by the adapter that originated the request.
- Outbound adapter traffic is fire-and-forget; adapters broadcast but never block callers.
- Adapters own their external API error handling and translate failures into domain-safe errors.
- Core logic never imports adapter modules or vendor SDKs.

## Rationale

- Keeps the core testable, stable, and platform-agnostic.
- Prevents external API churn from leaking into domain logic.

## Scope

- Applies to all adapters and their integration points with the core.

## Enforcement

- Review adapter code for boundary violations (raw external types in core paths).
- CI tests must fail if core depends on adapter implementation details.

## Exceptions

- None; boundary violations are treated as regressions.
