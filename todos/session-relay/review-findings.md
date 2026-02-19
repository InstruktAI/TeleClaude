# Review Findings: session-relay

**Review round:** 1
**Verdict:** REQUEST CHANGES

---

## Critical

### 1. Duplicate relay prevention only checks caller, not target

**File:** `teleclaude/mcp/handlers.py:618-621`

`_start_direct_relay` guards against duplicate relays by checking only the caller session:

```python
existing = await get_relay_for_session(caller_session_id)
if existing:
    return " Relay already active."
```

If the target is already in a relay with a different session, a second relay is created. Both relays monitor the target's output, causing duplicate delivery to both peers. Additionally, `create_relay` silently overwrites `_relay_by_session[target_session_id]`, orphaning the old relay's reverse lookup while its monitor tasks continue running.

**Fix:** Check both sessions:

```python
existing_caller = await get_relay_for_session(caller_session_id)
existing_target = await get_relay_for_session(target_session_id)
if existing_caller or existing_target:
    return " Relay already active."
```

---

## Important

### 2. No guard in `create_relay` against session already enrolled in another relay

**File:** `teleclaude/core/session_relay.py:69-72`

`create_relay` unconditionally writes to `_relay_by_session` for each participant. If a session is already in another relay, the old entry is silently overwritten. The old relay still exists in `_relays` with running monitor tasks, but is no longer discoverable via `get_relay_for_session`. This is the module-level counterpart to finding #1.

**Fix:** Check for existing enrollment under the lock and raise or return an error:

```python
async with _relay_lock:
    for p in participants:
        if p.session_id in _relay_by_session:
            raise ValueError(f"Session {p.session_id[:8]} already in relay {_relay_by_session[p.session_id][:8]}")
    _relays[relay_id] = relay
    for p in participants:
        _relay_by_session[p.session_id] = relay_id
```

### 3. Missing relay cleanup in session lifecycle (defense-in-depth)

**File:** `teleclaude/core/session_cleanup.py` (unchanged in this branch)

When a session terminates via `cleanup_session_resources` or `terminate_session`, no relay cleanup occurs. The monitor loop handles this reactively (capture_pane fails or returns empty, triggering `stop_relay`), so relays do end. However, there is a ~1s window where the relay is stale, and if `capture_pane` returns a non-empty error string instead of raising, the relay could linger.

**Fix:** Add relay cleanup to `cleanup_session_resources`:

```python
relay_id = await get_relay_for_session(session_id)
if relay_id:
    await stop_relay(relay_id)
```

### 4. No tests for `_start_direct_relay` handler wiring

**File:** `tests/unit/test_session_relay.py`

The handler method `_start_direct_relay` (handlers.py:606-654) has zero test coverage. It contains:

- Duplicate relay prevention (line 619-621)
- DB lookups for both sessions (lines 623-624)
- Null-session guard (lines 625-631)
- Missing tmux name guard (lines 632-634)
- Participant construction with fallback naming (lines 636-648)

This is the integration point that fulfills the primary requirement: "send_message(direct=true) starts a bidirectional relay." None of its branches are tested.

### 5. `_monitor_tasks` should use `init=False`

**File:** `teleclaude/core/session_relay.py:42-44`

The `_monitor_tasks` field is never passed at construction and uses a `noqa: RUF009` suppression. Using `init=False` removes it from the constructor signature, making intent explicit and eliminating the suppression:

```python
_monitor_tasks: dict[str, asyncio.Task[None]] = field(
    init=False, default_factory=dict, repr=False
)
```

---

## Suggestions

### 6. `RelayParticipant` should be `frozen=True`

**File:** `teleclaude/core/session_relay.py:24`

`RelayParticipant` is constructed once and never mutated. Its `session_id` is used as a dictionary key in `baselines` and `_monitor_tasks`. Adding `@dataclass(frozen=True)` prevents accidental mutation.

### 7. No regression test for `send_message(direct=false)` unchanged

**File:** `tests/unit/test_session_relay.py`

Requirements state: "Must not break existing send_message behavior when direct=false." No test verifies that `direct=false` still calls `_register_listener_if_present` and does NOT start a relay. Handler-level tests would catch regressions here.

### 8. No test for `_fanout` delivery failure stopping the relay

**File:** `teleclaude/core/session_relay.py:236-243`

When `send_keys_existing_tmux` returns `False`, `_fanout` calls `stop_relay`. This cleanup path is untested. All `TestFanout` tests mock `return_value=True`.

### 9. Consider renaming `number` to `ordinal`

**File:** `teleclaude/core/session_relay.py:31`

The field name `number` is ambiguous. It serves as a display ordinal in attribution (`"[Alice] (1):"`). `ordinal` or `participant_number` would be clearer.

### 10. Add `__post_init__` validation

**File:** `teleclaude/core/session_relay.py:35`

`SessionRelay` accepts zero participants and empty `relay_id`. Basic validation would catch construction errors at the boundary:

```python
def __post_init__(self) -> None:
    if len(self.participants) < 2:
        raise ValueError("Relay requires at least 2 participants")
```

---

## Fixes Applied

### Critical Issue #1: Duplicate relay prevention

**Commit:** 820113eb
**Fix:** Updated `_start_direct_relay` to check both caller and target sessions for existing relays before creating a new one. Both `existing_caller` and `existing_target` are now checked, preventing duplicate relays when either session is already enrolled.

### Important Issue #2: Guard in create_relay

**Commit:** d3bf9aac
**Fix:** Added validation in `create_relay` under the `_relay_lock` to check if any participant is already enrolled in another relay. Raises `ValueError` with clear message if duplicate enrollment is attempted, preventing silent overwrite of `_relay_by_session` entries.

### Important Issue #3: Relay cleanup in session lifecycle

**Commit:** 76fb657a
**Fix:** Added relay cleanup to `cleanup_session_resources` in `session_cleanup.py`. When a session terminates, the function now calls `get_relay_for_session` and `stop_relay` to proactively clean up any active relay. This is defense-in-depth alongside the reactive monitor loop cleanup.

### Important Issue #4: Handler tests

**Commit:** 1add3cd9
**Fix:** Added comprehensive test coverage for `_start_direct_relay` handler in `test_session_relay.py`:

- Test for duplicate relay prevention (caller already in relay)
- Test for duplicate relay prevention (target already in relay)
- Test for missing caller session in DB
- Test for missing target session in DB
- Test for missing tmux session name
- Test for participant construction with title fallback to session_id prefix

### Important Issue #5: Monitor tasks init=False

**Commit:** a3368b9f
**Fix:** Updated `_monitor_tasks` field in `SessionRelay` dataclass to use `init=False`, making it explicit that this field is never passed at construction and removing the RUF009 suppression.
