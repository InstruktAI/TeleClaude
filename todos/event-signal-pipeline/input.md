# Input: event-signal-pipeline

Phase 4 of the event processing platform. Full vision is in `todos/event-platform/input.md`.

This sub-todo delivers three-stage feed aggregation as domain-agnostic utility cartridges:
ingest (pull + normalize), cluster (group + detect bursts), synthesize (deep read + produce
artifact). Each stage is an independent cartridge that emits a signal taxonomy event, so
downstream domain pipelines subscribe to synthesis output rather than raw feed noise.

See `todos/event-platform/implementation-plan.md` → Phase 4 for the high-level scope.
