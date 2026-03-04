# Input: reflection-routing-ownership

Move reflection routing decisions from core to adapters. Core broadcasts reflections to ALL adapters unconditionally. Each adapter decides locally how to handle reflections — including those from its own users. Eliminate the `_fanout_excluding` anti-pattern and fix the two bugs it causes (duplicate output, wrong-source reflections).

## Architecture docs updated first

The updated architecture is documented in:
- `docs/project/spec/session-output-routing.md` — Reflection lane contract: broadcast to all, adapter-local routing
- `docs/project/design/architecture/adapter-client.md` — New invariant + flow §4: parallel delivery, no exclusion
- `docs/project/design/architecture/ui-adapter.md` — New invariant + flow §10: adapter-local reflection decision tree

These docs are the source of truth for this work.

## What's wrong today

### Problem 1: Core excludes the source adapter from reflections

`adapter_client.py:_fanout_excluding()` (lines 221-264) skips the source adapter. `broadcast_user_input()` (line 673) calls it with `exclude=source_adapter`. This means when a Discord user sends a message, Discord never receives the reflection — core made that routing decision for it.

**What should happen:** Core broadcasts to all adapters. The Discord adapter receives the reflection and decides locally: "this originated from my user, suppress it" or "route to admin channel." The adapter owns that decision.

### Problem 2: Two broadcast paths create duplicate input and wrong-source reflections

When a Discord user sends a message, two things happen:

1. **PATH A** — `command_handlers.py:deliver_inbound()` (line 967): The adapter path. Sets correct origin (`discord`), broadcasts with correct source, injects into tmux. Currently sequential — should be parallel.

2. **PATH B** — `agent_coordinator.py:handle_user_prompt_submit()` (line 691): The Claude hook path. Fires when tmux receives the input. Broadcasts AGAIN with hardcoded `source=InputOrigin.TERMINAL.value` and constructs a generic `actor_id=f"terminal:{config.computer.name}:{session_id}"`.

The result: two broadcasts per input for adapter-routed messages. The second broadcast has wrong source metadata.

### Problem 3: Echo detection uses a timing heuristic

`handle_user_prompt_submit` lines 769-779 detect the duplicate via `is_recent_routed_echo` — a 20-second timing window comparing text content. This is fragile in an event-based system.

**What should happen:** `deliver_inbound` sets a deterministic marker (e.g., a nonce or flag on the session). The hook handler checks for the marker and skips entirely — no side effects, no broadcast, no break_threaded_turn.

### Problem 4: Execution order bug causes duplicate output

In `handle_user_prompt_submit`, `break_threaded_turn` (line 826) fires BEFORE the echo guard check (line 843). For adapter-routed input:
1. `break_threaded_turn` clears `output_message_id` (line 826)
2. Echo IS detected (line 843), handler returns
3. But the damage is done — `output_message_id` was cleared, so the next output creates a NEW message instead of editing the existing one → duplicate output in Discord/Telegram

### Problem 5: `deliver_inbound` is sequential when it should be parallel

Current order: DB update → broadcast → tmux inject (sequential). The tmux injection is the critical path — it should not wait for reflection broadcast. Per the updated architecture docs:

```
par Parallel delivery
    AC → Inject into tmux (critical path)
    AC → broadcast_user_input (all adapters)
    AC → break_threaded_turn
end
```

### Problem 6: Adapters have no reflection routing logic

Because core was doing the exclusion, adapters never needed to handle reflections from their own users. Once core broadcasts to all:
- Each adapter needs to inspect `reflection_origin` (or equivalent metadata) to decide: suppress (own user), render to admin channel (other source), etc.
- The `MessageMetadata.reflection_origin` field proposed in `adapter-boundary-cleanup` is needed here too.

## Relationship to adapter-boundary-cleanup

`adapter-boundary-cleanup` addresses **presentation** logic in core (text formatting, header construction, per-adapter rendering). This todo addresses **routing** decisions in core (which adapters receive reflections, echo deduplication, execution ordering). They are complementary:

- `adapter-boundary-cleanup`: core formats text → adapters should format text
- `reflection-routing-ownership`: core excludes adapters → core should broadcast to all; adapters route locally

Both should reference `MessageMetadata.reflection_origin` — coordinate the field addition.

## Files involved

### Core (routing changes)
1. `teleclaude/core/adapter_client.py` — Replace `_fanout_excluding` with broadcast-to-all for reflections. `broadcast_user_input()` must send to all adapters including source.
2. `teleclaude/core/agent_coordinator.py` — Fix `handle_user_prompt_submit()`: deterministic echo marker instead of timing heuristic, move echo guard BEFORE `break_threaded_turn`, skip entirely for adapter-routed input.
3. `teleclaude/core/command_handlers.py` — `deliver_inbound()`: set deterministic echo marker, parallelize tmux inject + broadcast + break_threaded_turn.

### Adapters (new reflection routing logic)
4. `teleclaude/adapters/ui_adapter.py` — Base class needs a reflection routing hook or the metadata inspection logic.
5. `teleclaude/adapters/discord_adapter.py` — Implement adapter-local reflection routing: suppress for own-user reflections, render via webhook for others.
6. `teleclaude/adapters/telegram_adapter.py` — Implement adapter-local reflection routing: suppress for own-user, render to admin topic for others.

### Models
7. `teleclaude/core/models.py` — Add `reflection_origin` to `MessageMetadata` (shared with `adapter-boundary-cleanup`).

## Key decisions already made

- Core broadcasts to ALL adapters. No exclusion. Period.
- Each adapter owns its local routing decision for reflections.
- `deliver_inbound` runs tmux injection, broadcast, and break_threaded_turn in parallel.
- Echo deduplication uses a deterministic marker, not a timing heuristic.
- The echo guard must run BEFORE any side effects (`break_threaded_turn`).
