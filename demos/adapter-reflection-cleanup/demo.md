# Demo: adapter-reflection-cleanup

## Validation

```bash
# Verify _fanout_excluding is gone from reflection paths
! grep -n '_fanout_excluding' teleclaude/core/adapter_client.py | grep -i 'broadcast_user_input\|reflection'
```

```bash
# Verify no adapter-type checks in broadcast_user_input
! grep -n 'ADAPTER_KEY\|InputOrigin.TELEGRAM\|render_reflection_text\|display_origin_label' teleclaude/core/adapter_client.py
```

```bash
# Verify reflection_origin exists on MessageMetadata
grep -n 'reflection_origin' teleclaude/core/models.py
```

```bash
# Verify adapter-local suppression exists
grep -n 'reflection_origin' teleclaude/adapters/telegram_adapter.py teleclaude/adapters/discord_adapter.py
```

```bash
# Verify public adapter methods exist on base class
grep -n 'def drop_pending_output\|def move_badge_to_bottom\|def clear_turn_state' teleclaude/adapters/ui_adapter.py
```

```bash
# Verify no private _qos_scheduler access from core
! grep -n '_qos_scheduler' teleclaude/core/adapter_client.py
```

```bash
# Verify parallel gather in deliver_inbound
grep -n 'asyncio.gather' teleclaude/core/command_handlers.py
```

```bash
# All tests pass
make test
```

## Guided Presentation

### Step 1: Core is now a dumb pipe

Open `teleclaude/core/adapter_client.py` and show `broadcast_user_input`. It sends
raw text + MessageMetadata (with `reflection_origin`) to every adapter via
`_broadcast_to_ui_adapters`. No exclusion, no formatting, no adapter-type checks.

**Observe:** The function is short. No `render_reflection_text`, no headers, no
`ADAPTER_KEY` comparisons. Just metadata construction and broadcast.

**Why it matters:** Core no longer makes routing or presentation decisions for adapters.

### Step 2: Adapters own their reflections

Open `teleclaude/adapters/telegram_adapter.py` — show the reflection handling path.
When `metadata.reflection_origin == self.ADAPTER_KEY`, it suppresses. Otherwise it
constructs its own attribution header and separator.

Open `teleclaude/adapters/discord_adapter.py` — same origin check, same suppression.
Cross-source reflections render via the existing webhook path.

**Observe:** Each adapter makes its own decision. Different formatting per platform.
No core involvement.

**Why it matters:** Architecture alignment — adapters own presentation and routing.

### Step 3: Parallel delivery

Open `teleclaude/core/command_handlers.py` and show `deliver_inbound`. After the DB
update, tmux injection, broadcast, and break_threaded_turn run in parallel via
`asyncio.gather`.

**Observe:** Tmux injection no longer waits for broadcast to complete.

**Why it matters:** Matches architecture flow §4. Tmux is the critical path.
