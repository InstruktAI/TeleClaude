# DOR Report: prepare-quality-runner

## Assessment

- **Score:** 7 (draft)
- **Verdict:** needs_work
- **Assessed at:** 2026-02-28T16:00:00Z
- **Schema version:** 1

## Actions taken

- Rewrote `requirements.md` to align with event-driven architecture from `input.md`.
  Previous version described a batch scanner; new version describes a notification handler.
- Rewrote `implementation-plan.md` to match notification handler architecture.
  Previous version described standalone modules; new version describes handler + scorer +
  improver modules integrated with notification service.
- Created `demo.md` with four scenarios covering the handler's behavior.
- Fixed `state.json` references to `state.yaml` throughout.

## Remaining gaps

1. **Dependency not yet built.** The notification-service todo has DOR pass but build
   is pending. This handler cannot be built until the notification service ships.
   This is a known blocking dependency in `roadmap.yaml`.

2. **Handler registration mechanism unclear.** The notification-service implementation
   plan describes a processor with push callbacks, but the exact handler registration
   API (how a handler subscribes to specific event types) is not yet specified in the
   notification-service requirements. The prepare-quality-runner plan assumes a
   registration interface that may need refinement when the notification service is built.

3. **Scorer implementation approach.** The plan describes a structured rubric with point
   allocations, but whether this scoring happens via AI assessment (LLM-driven) or
   deterministic heuristics is not specified. The current DOR assessment in
   `next-prepare-gate` uses AI judgment. The plan should clarify whether the handler
   replicates this or uses a different approach.

## Blockers

- Notification-service build completion (roadmap dependency).
- Handler registration API specification (depends on notification-service implementation).

## Draft assessment

This todo is well-scoped and the architectural direction is clear. The main risk is the
dependency on notification-service — both for the handler registration mechanism and for
the event types it consumes. Once notification-service ships, the remaining gaps can be
resolved and this todo should reach DOR pass.
