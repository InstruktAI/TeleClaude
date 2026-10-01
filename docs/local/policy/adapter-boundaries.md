---
description: 'Strict separation between adapters and core logic.'
visibility: 'public'
---

# Adapter Boundaries — Policy

## Rules

- Adapters normalize external inputs into explicit command objects before entering core logic.
- Adapter-specific types and APIs do not enter the core.
- Feedback cleanup is performed only by the adapter that originated the request.
- Outbound adapter traffic is fire-and-forget; adapters broadcast but never block callers.
- Adapters own their external API error handling and translate failures into domain-safe errors.
- Core logic never imports adapter modules or vendor SDKs.
- **Inbound boundary**: adapters enqueue incoming messages via `InboundQueueManager.enqueue()` and return immediately. Delivery logic (tmux send, session gate, broadcast) lives only in `deliver_inbound` (core). Adapters must not call delivery functions directly.
- After successful enqueue, adapters show a platform-native typing indicator. This is the only adapter-side side effect of inbound message receipt.

- **Inbound resolve-or-create seam**: adapters resolve-or-create the bound session for an inbound message through the shared `core/inbound` seam, supplying a thin per-adapter parse-in policy — identity-scoped lookup, create-with-bundled-first-message, metadata reconciliation, and the delivery step. The seam returns whether the session was created on this call (`is_new`): a newly created session's first message is already bundled into its launch intent and is not delivered again, and an existing session's message is delivered unconditionally. No adapter gates inbound delivery on `lifecycle_status`. The seam holds no adapter imports.

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
