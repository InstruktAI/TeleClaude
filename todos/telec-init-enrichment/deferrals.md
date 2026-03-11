# Deferrals: telec-init-enrichment

## Event emission during init

**Depends on:** `event-envelope-schema`
**Outcome:** NOOP

Init currently does not emit structured events (e.g., `init_started`,
`enrichment_completed`). Adding event emission requires the event envelope
schema to be defined and validated first.

**Rationale:** The event-envelope-schema is upstream architecture work not yet
in scope. If that work is requested, event emission will become a natural
follow-up. Marked NOOP to avoid speculative todos.

## Mesh registration during init

**Depends on:** `mesh-architecture`
**Outcome:** NOOP

Init does not register the project with a mesh network. This requires the
mesh architecture to be designed and implemented first.

**Rationale:** The mesh-architecture is upstream infrastructure work not yet
in scope. If that work is requested, mesh registration will become a natural
follow-up. Marked NOOP to avoid speculative todos.
