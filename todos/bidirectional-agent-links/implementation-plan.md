# Bidirectional Agent Links — Implementation Plan

## Approach

Extend the existing one-shot listener system with a persistent bidirectional link
registry. When `send_message` creates a link, both sessions' `agent_stop` events
trigger output injection into the peer's tmux session. The existing checkpoint
filtering logic is extended to prevent checkpoint responses from crossing links.

The implementation is additive — the one-way listener model continues to work
unchanged for sessions that don't use bidirectional links.

## Files to Change

| File                                     | Change                                       |
| ---------------------------------------- | -------------------------------------------- |
| `teleclaude/core/session_listeners.py`   | Add BidirectionalLink dataclass + registry   |
| `teleclaude/core/agent_coordinator.py`   | Inject linked output on agent_stop           |
| `teleclaude/core/tmux_bridge.py`         | No changes (reuse send_keys_existing_tmux)   |
| `teleclaude/core/tmux_delivery.py`       | Add deliver_link_output function             |
| `teleclaude/mcp/handlers.py`             | Create bidi link on send_message             |
| `teleclaude/mcp/tool_definitions.py`     | Add close_link param to send_message schema  |
| `teleclaude/hooks/receiver.py`           | Extend checkpoint detection for link context |
| `teleclaude/constants.py`                | Add DEFAULT_LINK_TURN_BUDGET constant        |
| `tests/unit/test_session_listeners.py`   | New — link registry unit tests               |
| `tests/unit/test_bidirectional_links.py` | New — integration tests for link flow        |

## Files to Create

| File                                                      | Purpose            |
| --------------------------------------------------------- | ------------------ |
| `docs/project/design/architecture/bidirectional-links.md` | Architecture doc   |
| `docs/project/spec/bidirectional-link-protocol.md`        | Link protocol spec |

## Task Sequence

### Task 1: BidirectionalLink Data Structure

**File**: `teleclaude/core/session_listeners.py`

Add dataclass and registry alongside existing SessionListener:

```python
@dataclass
class BidirectionalLink:
    session_a_id: str           # Initiator
    session_b_id: str           # Responder
    tmux_a: str                 # Initiator's tmux session name
    tmux_b: str                 # Responder's tmux session name
    title_a: str                # Initiator's session title (for framing)
    title_b: str                # Responder's session title (for framing)
    turn_count: int = 0         # Turns consumed
    turn_budget: int = 8        # Maximum turns (backstop)
    created_at: datetime
```

Registry functions:

- `create_link(session_a_id, session_b_id, tmux_a, tmux_b, title_a, title_b, budget) -> BidirectionalLink`
- `get_link_for_session(session_id) -> Optional[BidirectionalLink]` — find link involving this session
- `get_peer_info(session_id) -> Optional[tuple[str, str, str]]` — return (peer_session_id, peer_tmux, peer_title)
- `increment_turn(session_id) -> bool` — increment, return False if budget exhausted
- `sever_link(session_id) -> bool` — remove the link
- `cleanup_session_links(session_id) -> int` — remove all links for a session (on session end)

In-memory storage: `_links: dict[str, BidirectionalLink]` keyed by a stable link ID
(sorted tuple of session IDs).

**Verification**: Unit test creates link, queries by either session ID, increments
turns, severs. Verify cleanup removes link.

### Task 2: Output Injection on Agent Stop

**File**: `teleclaude/core/agent_coordinator.py`

In `handle_agent_stop()`, after existing `_notify_session_listener()` call (line ~302),
add bidirectional link injection:

```python
# After existing listener notification
await self._inject_linked_output(context)
```

New method `_inject_linked_output(context)`:

1. Call `get_link_for_session(session_id)` — if no link, return early.
2. Get agent output from `session.last_feedback_received` (already extracted by
   `_extract_agent_output()` earlier in the handler).
3. **Checkpoint filter**: if output contains `CHECKPOINT_MESSAGE` prefix or is empty,
   skip injection. Do NOT increment turn count.
4. Call `increment_turn(session_id)` — if budget exhausted, sever link and return.
5. Get peer info via `get_peer_info(session_id)`.
6. Frame the output: `[From {peer_title}] {output}`.
7. Call `deliver_link_output(peer_tmux, framed_output)` to inject into peer's tmux.
8. Log at DEBUG: link injection details, turn count, remaining budget.

**Verification**: Two test sessions with a link. Trigger agent_stop on one. Verify
the other's tmux receives the framed output. Verify turn counter incremented.

### Task 3: Checkpoint Filtering for Links

**File**: `teleclaude/core/agent_coordinator.py`

In `_inject_linked_output()`, detect checkpoint content in the output before injection.

Detection logic (reuse from `hooks/receiver.py`):

```python
from teleclaude.constants import CHECKPOINT_MESSAGE

if not output or CHECKPOINT_MESSAGE[:50] in output:
    logger.debug("Skipping link injection — checkpoint response")
    return
```

Also filter empty/whitespace-only output.

**Verification**: Agent stops with checkpoint response. Verify link peer does NOT
receive injection. Verify turn counter is NOT incremented.

### Task 4: Link Creation in send_message

**File**: `teleclaude/mcp/handlers.py`

In `teleclaude__send_message()`, after existing `_register_listener_if_present()`,
add bidirectional link creation:

```python
# After listener registration
await self._create_bidirectional_link(session_id, caller_session_id)
```

New method `_create_bidirectional_link(target_id, caller_id)`:

1. Look up both sessions from DB (need tmux_session_name and title).
2. If either session missing, log warning and return.
3. Check if link already exists between these two sessions — if so, skip.
4. Call `create_link(caller_id, target_id, caller_tmux, target_tmux,
caller_title, target_title, budget=DEFAULT_LINK_TURN_BUDGET)`.
5. Log at INFO: link created between sessions.

**Verification**: send_message from A to B. Verify link registry contains a link
between A and B. Send again — verify no duplicate link created.

### Task 5: Link Termination — close_link Parameter

**Files**: `teleclaude/mcp/handlers.py`, `teleclaude/mcp/tool_definitions.py`

Add `close_link: bool = False` parameter to `send_message` tool definition.

In handler:

1. If `close_link=True`, deliver the message to the target session.
2. Sever the link after delivery.
3. Return confirmation that link was closed.

**Verification**: Create link. Send message with close_link=true. Verify message
delivered AND link severed. Subsequent agent_stop does NOT inject.

### Task 6: Link Cleanup on Session End

**File**: `teleclaude/core/agent_coordinator.py` (or session lifecycle code)

When a session is ended (via `end_session` or session cleanup), call
`cleanup_session_links(session_id)` to remove any active links.

This parallels existing `cleanup_caller_listeners(session_id)`.

**Verification**: Create link between A and B. End session A. Verify link is
removed. Agent_stop on B does NOT attempt injection into dead session.

### Task 7: Delivery Function

**File**: `teleclaude/core/tmux_delivery.py`

Add `deliver_link_output()` alongside existing `deliver_listener_message()`:

```python
async def deliver_link_output(
    tmux_session: str,
    framed_output: str,
) -> bool:
    """Deliver bidirectional link output to a peer session via tmux."""
    return await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_session,
        text=framed_output,
        send_enter=True,
    )
```

**Verification**: Call with a valid tmux session. Verify text appears in the pane.

### Task 8: Remote/Cross-Computer Links

**File**: `teleclaude/core/agent_coordinator.py`

Extend `_forward_stop_to_initiator()` logic: when a remote session stops AND has
a bidirectional link, forward the output (not just the stop notification) via Redis.

The receiving computer extracts the output from the Redis payload and injects it
into the local peer's tmux session.

This mirrors how stop notifications currently cross computers, but carries the
output payload.

**Verification**: Cross-computer test. Session on computer A linked to session on
computer B. B stops. Verify A receives B's output via Redis forwarding.

### Task 9: Unit Tests — Link Registry

**File**: `tests/unit/test_session_listeners.py` (extend existing)

Tests:

- `test_create_link` — creates link, verifies fields
- `test_get_link_for_session` — query by either session ID
- `test_get_peer_info` — returns correct peer
- `test_increment_turn` — counts correctly, returns False at budget
- `test_sever_link` — removes link, get returns None
- `test_cleanup_session_links` — removes all links for a session
- `test_no_duplicate_link` — creating same link twice is idempotent

### Task 10: Integration Tests — Link Flow

**File**: `tests/unit/test_bidirectional_links.py` (new)

Tests:

- `test_agent_stop_injects_to_peer` — mock agent_stop, verify tmux injection
- `test_checkpoint_not_injected` — checkpoint output filtered
- `test_turn_budget_severs_link` — budget exhaustion severs
- `test_close_link_parameter` — explicit close works
- `test_session_end_cleans_link` — session end severs link
- `test_empty_output_not_injected` — empty/whitespace filtered
- `test_existing_listeners_still_work` — one-way model unaffected

### Task 11: Heartbeat Prompting Update

**File**: Documentation + agent system prompt updates

Update the heartbeat policy documentation to include:

- Intent types: anchor, check, wait
- The anchoring rule (always have a work timer)
- Game rules for absorption without response
- Timer implementation (echo intent && sleep N)
- Anti-chattiness rules for linked exchanges

This is a prompting/documentation change, not a code change. The timer mechanism
already exists (background bash). The intent is carried by the echo output.

### Task 12: Architecture Documentation

**Files**: `docs/project/design/architecture/bidirectional-links.md`,
`docs/project/spec/bidirectional-link-protocol.md`

Document:

- Link registry design and lifecycle
- Event flow (agent_stop → filter → inject)
- Checkpoint filtering contract
- Turn budget semantics
- Cross-computer forwarding
- Intentional heartbeat protocol

## Risks and Mitigations

| Risk                                | Mitigation                                     |
| ----------------------------------- | ---------------------------------------------- |
| Agents loop despite prompting       | Turn budget backstop severs link automatically |
| Checkpoint echo across links        | Explicit filter on CHECKPOINT_MESSAGE prefix   |
| Memory leak from uncleaned links    | cleanup_session_links on every session end     |
| Output too large for tmux injection | Truncate to UI_MESSAGE_MAX_CHARS before inject |
| Cross-computer latency              | Async Redis forwarding (existing pattern)      |
| Feature branch diverges from main   | Keep changes additive, no breaking refactors   |

## Assumptions

1. The existing `send_keys_existing_tmux()` reliably injects text into agent sessions.
2. `session.last_feedback_received` contains the agent's final output at agent_stop.
3. The checkpoint message prefix is stable and detectable via string matching.
4. In-memory link storage (no DB persistence) is acceptable for this experiment.
5. Agents will follow intentional heartbeat prompting with reasonable reliability
   (the same discipline level as checkpoint behavior).

## Build Order

Tasks 1-3 form the core (link registry + injection + filtering).
Task 4 wires it into the MCP tool.
Tasks 5-6 handle lifecycle.
Task 7 is the delivery plumbing.
Task 8 extends to cross-computer.
Tasks 9-10 verify everything.
Tasks 11-12 document the protocol.

Sequential dependency: 1 → 2 → 3 → 4 → 5 → 6 (core chain).
Task 7 can parallel with 2. Tasks 9-10 can start after 6. Tasks 11-12 after 10.
Task 8 can follow after 4.
