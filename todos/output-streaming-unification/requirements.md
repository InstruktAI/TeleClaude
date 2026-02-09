# Requirements: Output Streaming Unification

## Goal

Establish a single, explicit outbound architecture for agent activity streaming that supports Telegram, TUI, and upcoming Web clients without duplicating routing logic or coupling stream payloads to cache snapshots.

## Scope

In scope:

- Canonical internal activity events:
  - `user_prompt_submit`
  - `agent_output_update`
  - `agent_output_stop`
- One routing/fan-out boundary in AdapterClient (or an OutputDistributor it owns).
- Stream consumer path for TUI and Web through shared stream gateway semantics.
- Keep cache/API websocket path for state snapshots only.
- Update architecture documentation to target-state blueprint.

Out of scope:

- Full web UI implementation.
- Authentication/authorization redesign.
- Replacing existing command ingress path.
- Removing fan-out or adapter system.

## Functional requirements

1. Canonical activity stream contract exists in core and is consumed by all outbound consumers.
2. AgentCoordinator emits/coordinates activity events but does not apply UI protocol formatting.
3. AdapterClient/distributor routes activity events to relevant adapters/consumers based on metadata/origin rules.
4. TUI and Web can consume the same activity stream contract (different protocol translation allowed at adapter edge).
5. Cache/API websocket continues to serve state snapshots and low-frequency state updates.
6. High-frequency output chunks do not require cache mutation to reach stream consumers.

## Non-functional requirements

1. Consumer isolation: one slow consumer must not block others.
2. Bounded queue/backpressure strategy per stream consumer.
3. Clear observability: queue depth, drop/coalesce counts, consumer lag/disconnect metrics.
4. Backward-compatibility hygiene policy respected for non-breaking rollout behavior.

## Acceptance criteria

1. Architecture docs clearly separate:
   - state channel,
   - activity stream channel.
2. Canonical event names are documented and used consistently in distributor interfaces.
3. TUI can be wired as output-stream consumer without depending on cache event hacks for rich output.
4. Web adapter path is defined for both:
   - websocket stream consumption,
   - optional SSE translation for AI SDK-compatible streaming.
5. Existing Telegram output behavior remains functional during migration.
