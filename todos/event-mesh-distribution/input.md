# Input: event-mesh-distribution

Phase 6 of the event-platform holder. Depends on `event-platform-core` (pipeline runtime,
envelope schema, visibility field) and `mesh-architecture` (P2P transport layer).

The visibility field is already structural in the envelope (`local`/`cluster`/`public`).
This phase wires the forwarding logic: cluster events ride the existing Redis `messages:{computer}`
transport, public events go to discovered peers. Incoming mesh events hit the local trust
evaluator before entering the pipeline.

Cartridge publishing is the second-order concern: when a node publishes a cartridge as a
`cartridge.published` event, peers receive code-as-data and install with sovereignty-gated
approval (L1/L2/L3). Organic promotion tracking completes the loop.

See `todos/event-platform/implementation-plan.md` → Phase 6 for the high-level scope.
