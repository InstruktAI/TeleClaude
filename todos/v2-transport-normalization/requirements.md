# Requirements

## Problem
External inputs are handled inconsistently across REST/Redis/Telegram, with transport-specific metadata and payload shapes leaking into core handlers. REST and Redis are treated like adapters, which muddles responsibility and makes it hard to enforce a clean internal contract.

## Goals
1) Normalize all external inputs into **internal command models** before hitting core handlers.
2) Treat REST and Redis as **transports only** (parse/validate/map, no adapter behavior).
3) Unify handler signatures to accept internal command models, not transport payloads.
4) Keep behavior and ordering intact (no command outbox/event pipeline yet).
5) Keep response envelopes (request_id or similar) where already expected by clients.

## Non-Goals (for this phase)
- No command outbox / event pipeline.
- No WebSocket/SSE replacement work.
- No removal of Telegram adapter semantics (Telegram remains a UI adapter).

## Constraints
- No breaking changes to user-facing behavior.
- Must preserve ordering guarantees (welcome message precedes output updates).
- Minimal churn: do not change unrelated logic.

## Acceptance Criteria
- All external entry points map to internal command models via a single normalization layer.
- REST/Redis code paths no longer branch on adapter-specific behavior in core handlers.
- Core handlers accept typed internal commands (or a normalized request object) consistently.
- Tests updated/added to cover normalization layer and ensure no behavior regressions.
