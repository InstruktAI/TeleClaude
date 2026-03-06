# Input: conversation-projection-unification

Unify the core output projection route so every output producer and consumer derives from the same session truth instead of inventing separate semantics.

## Problem

Today the system has multiple producers and consumers of session output, but no single core projection route that all of them share:

1. Poller-driven standard output pushes tmux snapshots through `AdapterClient.send_output_update()`
2. `GET /sessions/{id}/messages` uses `extract_messages_from_chain(... include_tools=False, include_thinking=...)`
3. `/api/chat/stream` replays raw transcript entries through `convert_entry()`
4. threaded transcript rendering uses `render_agent_output()` / `render_clean_agent_output()`
5. mirrors/search are designed around the same "conversation-only" truth but do not yet share a canonical projector

The result is semantic drift and duplicated logic:

- standard poller output has one path
- web history hides internal tool transcript blocks
- web live SSE surfaces those same internal tool blocks as generic tool UI
- threaded transcript output has its own rendering rules again
- future mirror/search work is aiming at the same truth from yet another entry point

These are different projections of the same underlying session truth. That is the architectural bug.

## Required outcome

Create one canonical **core output projection route** that every producer/consumer uses.

That route must expose at least these projection families:

- `terminal_live`
  - source: tmux poller snapshots/diffs
  - consumers: existing adapter push path such as Telegram's edited-message UX
- `conversation`
  - source: transcript chain
  - consumers: web history, web live SSE, threaded transcript output, mirror/search

That route must own:

- normalization
- visibility policy
- traversal/cursor logic
- incremental/delta behavior for live consumers
- serializer inputs for API/web and existing adapter push calls
- the canonical handoff point between output producers and transports

## Rollout priority

The web lane is the clearest visible regression, but it is not the architecture owner.

Recommended rollout:

1. define the shared core projection route
2. cut standard poller-driven output production over to it
3. cut transcript-driven threaded output production over to it
4. cut web history and web live SSE over to it
5. cut mirror/search consumers over to it

Adapters themselves stay unchanged. Core producers stop bypassing each other.

## Hard constraints

1. Do **not** change Telegram, Discord, or TUI adapter implementations in this todo.
2. Do **not** change threaded mode behavior in this todo. It is already working and is the regression bar.
3. Adapter-facing delivery APIs stay stable. Unification happens underneath them in core projection code.
4. Telegram's tmux-live edited-message UX remains intact; only the core projection route beneath it is in scope.
5. Internal tool transcript blocks must not leak into web chat content unless they are explicitly classified as user-visible widgets/tools.

## Scope boundary

This todo is about **projection unification**, not adapter routing or presentation ownership.

It does **not** absorb:

- `adapter-boundary-cleanup`
- `reflection-routing-ownership`
- Telegram output QoS / footer / topic behavior
- Discord threaded pagination behavior

It **does** establish the reusable core projection route that all current and future consumers must use without changing adapter code.

## Concrete divergence to remove

### Web history path

- `teleclaude/api_server.py:get_session_messages`
- filtered structured messages from transcript chain

### Web live path

- `teleclaude/api/streaming.py:_stream_sse`
- raw transcript entry replay via `teleclaude/api/transcript_converter.py:convert_entry`

### Existing threaded transcript path

- `teleclaude/core/agent_coordinator.py:trigger_incremental_output`
- custom renderers `render_agent_output` / `render_clean_agent_output`

### Existing standard adapter push path

- `teleclaude/core/polling_coordinator.py` → `AdapterClient.send_output_update()`
- tmux snapshot payload delivered directly to adapters

These should no longer be independently deciding how session output is projected before transport. They should all consume the same core route.

## Relationship to existing roadmap items

- `web-frontend-test-bugs` tracks the symptom and should reference this todo as evidence, not as the owner.
- `history-search-upgrade` should reuse the shared conversation projection route once it exists.
- `adapter-boundary-cleanup` and `reflection-routing-ownership` stay separate; they solve routing/presentation ownership, not transcript projection drift.
