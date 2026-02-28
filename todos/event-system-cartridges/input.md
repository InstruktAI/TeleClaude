# Input: event-system-cartridges

Phase 2 of the event processing platform. Full vision is in `todos/event-platform/input.md`.

This sub-todo delivers the intelligence layer: four new cartridges (trust evaluator, enrichment,
correlation, classification) inserted into the system pipeline that `event-platform-core` built.
The pipeline ordering after this phase is: trust → dedup → enrichment → correlation →
classification → projection.

See `todos/event-platform/implementation-plan.md` → Phase 2 for the high-level scope.
