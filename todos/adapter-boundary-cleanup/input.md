# adapter-boundary-cleanup — Input

Move adapter-specific presentation logic out of adapter_client.py into adapters. Core decides WHO receives, adapters decide HOW to present.

## Boundary Violations to Fix

### Violation 1: Reflection text formatting in core (adapter_client.py lines 624-657)

`broadcast_user_input()` constructs adapter-specific presentation:

```python
# Lines 624-627: Display logic — deciding actor label
default_actor = (
    "TUI" if source.lower() in {InputOrigin.API.value, InputOrigin.TERMINAL.value} else source.upper()
)

# Lines 632-640: Origin label + header construction
display_origin_label = (
    "TERMINAL"
    if source_adapter == InputOrigin.TERMINAL.value
    else (source_adapter.upper() if source_adapter else "UNKNOWN")
)
is_terminal_actor_reflection = source_adapter == InputOrigin.TERMINAL.value and bool(explicit_actor_name)
reflection_header = f"{explicit_actor_name} @ {display_origin_label}:\n\n"

# Lines 648-657: Per-adapter text formatting
def render_reflection_text(adapter: UiAdapter, base_text: str) -> str:
    if not is_terminal_actor_reflection:
        return base_text
    with_header = base_text if base_text.startswith(reflection_header) else f"{reflection_header}{base_text}"
    if adapter.ADAPTER_KEY == InputOrigin.TELEGRAM.value:  # <-- CORE CHECKING ADAPTER TYPE
        if with_header.endswith("---\n"):
            return with_header
        return f"{with_header}\n\n---\n"
    return with_header
```

**What should happen:**

1. Remove ALL presentation logic from `broadcast_user_input()` — no `render_reflection_text`, no `reflection_header`, no `display_origin_label`, no `default_actor`
2. Add `reflection_origin: str | None` field to `MessageMetadata` so adapters know the input source
3. Core passes raw text + metadata (actor_name, actor_id, actor_avatar_url, reflection_origin) to `adapter.send_message()`
4. Each adapter handles its own formatting in `send_message` when reflection metadata is present:
   - **Discord**: Already uses webhook rendering with native username + avatar (discord_adapter.py lines 1430-1505, `_send_reflection_via_webhook`). The "Name @ TERMINAL:" text prefix is redundant for Discord — webhook handles attribution natively.
   - **Telegram**: Should construct its own "Name @ ORIGIN:" header + `---` separator in its `send_message` or a dedicated reflection helper
   - **WhatsApp**: Will decide its own format
5. The `_noop()` helper in `broadcast_user_input` is now dead code — remove it

### Violation 2: QoS scheduler access in break_threaded_turn (adapter_client.py lines 443-453)

```python
for adapter in self.adapters.values():
    scheduler = getattr(adapter, "_qos_scheduler", None)
    if scheduler is not None:
        dropped = scheduler.drop_pending(session.session_id)
```

Core reaches into a private adapter attribute (`_qos_scheduler`) and directly manipulates it.

**What should happen:**

1. Add a `drop_pending_output(session_id: str) -> int` method to `UiAdapter` base class (returns count of dropped items, base implementation returns 0)
2. Adapters that have QoS schedulers override this method to drop pending payloads
3. `break_threaded_turn` calls `adapter.drop_pending_output(session.session_id)` instead of reaching into internals

### Violation 3 (minor): move_badge_to_bottom calls private method

```python
async def move_badge_to_bottom(self, session: "Session") -> None:
    await self._broadcast_to_ui_adapters(session, "move_badge", lambda adapter, s: adapter._move_badge_to_bottom(s))
```

Calls `_move_badge_to_bottom` (private convention). Should be a public method on UiAdapter base class with a no-op default.

## Routing Spec Reference

From `project/spec/session-output-routing`:

- "Reflect to every provisioned UI adapter except the source adapter."
- "Never suppress MCP reflections; they follow the same rule."
- "Adapters own placement and rendering strategy."

From `project/design/architecture/ui-adapter`:

- "No domain policy decisions; UI is translation and presentation only."
- "Decide local presentation strategy (edit-in-place, threaded, or multi-placement) for delivered messages."

## Files to Change

1. `teleclaude/core/adapter_client.py` — Remove presentation logic from broadcast_user_input, add drop_pending_output delegation, fix move_badge
2. `teleclaude/core/models.py` — Add `reflection_origin` field to MessageMetadata
3. `teleclaude/adapters/ui_adapter.py` — Add `drop_pending_output()` base method, make `move_badge_to_bottom()` public
4. `teleclaude/adapters/telegram_adapter.py` — Add reflection formatting in send_message path (header + separator)
5. `teleclaude/adapters/discord_adapter.py` — Already handles reflection via webhook; may need minor cleanup
6. Tests for reflection formatting (currently test the core formatting — need to move to adapter-level tests)

## Key Decisions Already Made

- "Only the adapters decide how to wrap it, what to do with it"
- "There should not be flowing anything to adapters that adapters need to handle themselves"
- Feature flag system (`feature_flags.py`, `experiments.yml`) MUST be preserved
- Each adapter IS its mode — THREADED_OUTPUT class property is the right architecture
- Input reflections are NEVER suppressed based on output mode — routing spec is authoritative
