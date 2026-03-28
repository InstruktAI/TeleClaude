# identity-origin-cleanup-final — Input

# Eliminate `channel_metadata` — Complete Plan

## Context

The `identity-origin-cleanup` delivery replaced `channel_metadata` with typed origin metadata for **session creation**, but left per-message actor identity still flowing through an untyped `dict[str, object]` bag. Three follow-up tasks (6b, 7, 8) were deferred, scaffolded, then deleted because they were split incorrectly. This plan unifies all remaining work into one pass. No backward compatibility — greenfield.

Additionally, two related architectural debts from the same original scope: daemon headless session creation bypasses the command pipeline, and `resolve_from_terminal()` is a legacy identity path that should be removed.

---

## Part 1: Typed actor fields on MessageMetadata

**File: `teleclaude/core/models/_session.py`**

Add to `MessageMetadata`:
```python
actor_id: str | None = None
actor_name: str | None = None
actor_avatar_url: str | None = None
platform_message_id: str | None = None
```

Delete:
```python
channel_metadata: dict[str, object] | None = None  # line 38
```

Also delete `ChannelMetadata` dataclass (lines 19-21) — unused except as a type.

---

## Part 2: Move actor normalization to adapter edges

Each adapter currently stuffs raw platform data into `channel_metadata` dict, then `CommandMapper._extract_actor()` normalizes it. Instead, each adapter sets typed fields directly on `MessageMetadata`. The normalization logic (platform prefix for actor_id) moves to the adapter.

### Telegram input_handlers.py (lines 235-245)
Before: `metadata.channel_metadata["user_id"] = ...; metadata.channel_metadata["user_name"] = ...`
After:
```python
metadata.platform_message_id = str(update.effective_message.message_id)
metadata.actor_id = f"telegram:{update.effective_user.id}"
metadata.actor_name = display_name
```

### Telegram command_handlers.py (3 blocks: lines 119, 153, 194)
Before: `metadata.channel_metadata["message_id"] = ...`
After: `metadata.platform_message_id = str(update.effective_message.message_id)`

(These are agent/resume/restart commands — no actor extraction happens downstream, only message_id was stored.)

### Telegram callback_handlers.py (2 blocks: lines 379, 435)
Before: `metadata.channel_metadata["user_id"] = str(from_user.id)`
After: `metadata.actor_id = f"telegram:{from_user.id}"`

### Telegram private_handlers.py (line 265)
Before: `metadata.channel_metadata["message_id"] = ...`
After: `metadata.platform_message_id = str(update.effective_message.message_id)`

### Discord gateway_handlers.py (lines 523-534)
Before: Builds `channel_metadata` dict with `message_id`, `user_id`, `discord_user_id`, `user_name`, then `_metadata(channel_metadata=...)`
After: Set typed fields directly:
```python
metadata = self._metadata()
metadata.platform_message_id = message_id
metadata.actor_id = f"discord:{getattr(getattr(message, 'author', None), 'id', '')}"
metadata.actor_name = self._discord_actor_name(author_obj, ...)
metadata.actor_avatar_url = self._discord_actor_avatar_url(author_obj)
```
Note: The adapter already extracts these same values separately at lines 535-537 for `ProcessMessageCommand`. After this change, those lines read from `metadata.*` instead of re-extracting.

### WhatsApp handler (whatsapp_handler.py line 151)
Before: `channel_metadata={"message_id": message_id}`
After: `platform_message_id=message_id`

### Fanout (_fanout.py lines 330-336)
Before: Constructs `channel_metadata={"actor_id": ..., "actor_name": ..., "actor_role": ..., ...}`
After:
```python
metadata=MessageMetadata(
    origin=sender_origin,
    actor_id=actor_id,
    actor_name=actor_name,
)
```
The `actor_role`, `actor_agent`, `actor_computer` keys were never consumed by `_extract_actor` — they're dead data. Delete them.

---

## Part 3: Simplify CommandMapper

**File: `teleclaude/core/command_mapper.py`**

### Delete `_extract_actor()` entirely (lines 58-100)
Its job was to normalize untyped dict keys into actor fields. After Part 2, adapters provide typed fields directly.

### Update `map_telegram_input()` (line 128-131)
Before: calls `_extract_actor(metadata.channel_metadata, ...)`
After: reads `metadata.actor_id`, `metadata.actor_name`, `metadata.actor_avatar_url` directly into `ProcessMessageCommand`.

### Update `map_redis_input()` (lines 170-180)
Remove `channel_metadata` parameter entirely. Actor fields come through typed `MessageMetadata` or are provided separately.
Line 199-200: replace `_extract_actor(channel_metadata, origin)` with reading from a `MessageMetadata` parameter (add `metadata: MessageMetadata` param, or read actor fields from existing params).

**Decision: add `metadata: MessageMetadata | None = None` parameter to `map_redis_input`**, same pattern as `map_telegram_input` and `map_api_input`. The Redis messaging mixin already constructs a `MessageMetadata` at line 240 — move that construction before the `CommandMapper.map_redis_input()` call and pass it in.

### Update `map_api_input()` (lines 329, 358)
Already passes `None` to `_extract_actor`. After deletion, reads actor fields from `metadata.*` and `payload.*` directly (which it already does for payload — lines 323-328). No behavior change needed, just remove the `_extract_actor(None, ...)` calls.

---

## Part 4: Update Redis transport wire format

### _messaging.py — `_parse_redis_message()` (lines 373-399)
Before: Parses `b"channel_metadata"` JSON blob from stream.
After: Parse individual typed fields from stream:
```python
actor_id = data.get(b"actor_id", b"").decode("utf-8") or None
actor_name = data.get(b"actor_name", b"").decode("utf-8") or None
actor_avatar_url = data.get(b"actor_avatar_url", b"").decode("utf-8") or None
platform_message_id = data.get(b"platform_message_id", b"").decode("utf-8") or None
```

Update `RedisInboundMessage` (`_snapshot.py:47-57`) to carry typed fields instead of `channel_metadata`:
```python
actor_id: str | None = None
actor_name: str | None = None
actor_avatar_url: str | None = None
platform_message_id: str | None = None
```
Delete `channel_metadata` field.

### _messaging.py — `_handle_incoming_message()` (lines 224-251)
Before: `channel_metadata=parsed.channel_metadata` passed to mapper and metadata
After: Build `MessageMetadata` with typed fields from `parsed.*`, pass to mapper.

The `target_computer` injection hack (lines 249-250):
```python
metadata.channel_metadata = metadata.channel_metadata or {}
metadata.channel_metadata["target_computer"] = parsed.initiator
```
This is consumed by `_forward_stop_to_initiator` which reads `session.get_origin_section("redis").get("target_computer")`. The `parsed.initiator` value is already available in the `RedisInboundMessage` — it does NOT flow through `channel_metadata` to the session. It's written to the session's `origin_metadata.redis.target_computer` via `RedisTransportMetadata`. So this hack is dead code that does nothing — the `metadata.channel_metadata` it mutates is never persisted. Delete it.

### _request_response.py — `send_request()` (lines 126-127)
Before: `json.dumps(metadata.channel_metadata)`
After: Serialize typed fields individually:
```python
if metadata.actor_id:
    data[b"actor_id"] = metadata.actor_id.encode("utf-8")
if metadata.actor_name:
    data[b"actor_name"] = metadata.actor_name.encode("utf-8")
if metadata.actor_avatar_url:
    data[b"actor_avatar_url"] = metadata.actor_avatar_url.encode("utf-8")
if metadata.platform_message_id:
    data[b"platform_message_id"] = metadata.platform_message_id.encode("utf-8")
```

### _adapter.py — `RedisTransportMetadata` (line 171)
Delete `channel_metadata: str | None = None` field and all `from_dict` handling for it (lines 176-183, 192).

---

## Part 5: Route headless session creation through command pipeline

### daemon_hook_outbox.py (line 430-443)
Before: `resolve_from_terminal()` then `db.create_headless_session()` directly.
After: Build `CreateSessionCommand` and dispatch through command service:
```python
from teleclaude.types.commands import CreateSessionCommand
cmd = CreateSessionCommand(
    project_path=project_path or "",
    title=title,
    origin=InputOrigin.TERMINAL.value,
    system_role="worker",
    # ... other fields from current create_headless_session call
)
result = await get_command_service().create_session(cmd)
```
Remove `resolve_from_terminal()` call — identity propagates via `initiator_session_id` on the command.

### sessions_actions_routes.py (line 149-158) — revive endpoint
Same pattern: replace `db.create_headless_session()` with `CreateSessionCommand` through command service.

### db._sessions.py — `create_headless_session()` method
After both callers are migrated, this method has no production callers. Delete it. Update DB tests that test it directly (`test__sessions.py` lines 43, 85, 367) to test through the command pipeline instead.

---

## Part 6: Remove `resolve_from_terminal()`

**File: `teleclaude/core/identity.py`**
Delete the `resolve_from_terminal()` method.

**CLI callers to update (3 files):**
- `teleclaude/cli/telec/handlers/docs.py`
- `teleclaude/cli/config_cli.py`
- `teleclaude/cli/cartridge_cli.py`

These call `resolve_from_terminal()` to get the current user's identity for CLI operations. Replace with the terminal auth path: read from `telec auth whoami` / `TELEC_SESSION_TOKEN` / `TELEC_AUTH_EMAIL` environment variable — whichever the CLI already uses elsewhere. Need to check the exact alternative during implementation.

---

## Part 7: Update tests

### Tests that directly reference `channel_metadata`:
- `tests/unit/adapters/telegram/test_input_handlers.py` — `_metadata()` returns `MessageMetadata(channel_metadata=dict(kwargs))` → update
- `tests/unit/adapters/telegram/test_callback_handlers.py` — same pattern
- `tests/unit/core/models/test__adapter.py` — tests `RedisTransportMetadata` channel_metadata field
- `tests/unit/mirrors/test_generator.py` — snapshot/mirror tests
- `tests/unit/transport/redis_transport/test_target_computer_named_field.py` — tests target_computer in Redis metadata
- `tests/unit/transport/redis_transport/test__adapter_noop.py`
- `tests/unit/transport/redis_transport/test__messaging.py` — tests message parsing

### xfail test spec:
- `tests/unit/test_daemon_headless_pipeline.py` — remove `xfail` marker, tests should pass after Part 5.

### CLI test:
- `tests/unit/cli/telec/handlers/test_docs.py` — tests `resolve_from_terminal` usage

---

## Part 8: Update documentation

### Files referencing `channel_metadata`:
- `docs/project/spec/session-identity-truth.md` — update origin data model section
- `docs/project/design/architecture/session-lifecycle.md`
- `docs/project/design/architecture/layer-ownership.md` — edge layer description
- `demos/identity-origin-cleanup/demo.md`
- `demos/agent-session-auth/demo.md`
- `todos/edge-session-creation/input.md`
- `todos/session-memory-extraction/input.md`

Update all references from `channel_metadata` to the typed fields or remove if describing the old pattern.

---

## File change summary

| File | Action |
|------|--------|
| `teleclaude/core/models/_session.py` | Add 4 typed fields, delete `channel_metadata` field, delete `ChannelMetadata` class |
| `teleclaude/core/command_mapper.py` | Delete `_extract_actor()`, update 3 map methods to read typed fields |
| `teleclaude/adapters/telegram/input_handlers.py` | Set typed fields instead of dict |
| `teleclaude/adapters/telegram/command_handlers.py` | Set typed fields instead of dict (3 blocks) |
| `teleclaude/adapters/telegram/callback_handlers.py` | Set typed fields instead of dict (2 blocks) |
| `teleclaude/adapters/telegram/private_handlers.py` | Set typed fields instead of dict |
| `teleclaude/adapters/discord/gateway_handlers.py` | Set typed fields instead of dict, simplify duplicate extraction |
| `teleclaude/hooks/whatsapp_handler.py` | Set typed field instead of dict |
| `teleclaude/core/agent_coordinator/_fanout.py` | Set typed fields, delete dead keys |
| `teleclaude/transport/redis_transport/_messaging.py` | Parse typed fields, delete channel_metadata parsing, delete target_computer hack |
| `teleclaude/transport/redis_transport/_request_response.py` | Serialize typed fields individually |
| `teleclaude/core/models/_snapshot.py` | Replace `channel_metadata` with typed fields on `RedisInboundMessage` |
| `teleclaude/core/models/_adapter.py` | Delete `channel_metadata` from `RedisTransportMetadata` |
| `teleclaude/daemon_hook_outbox.py` | Route through `CreateSessionCommand`, remove `resolve_from_terminal()` |
| `teleclaude/api/sessions_actions_routes.py` | Route revive through `CreateSessionCommand` |
| `teleclaude/core/db/_sessions.py` | Delete `create_headless_session()` |
| `teleclaude/core/identity.py` | Delete `resolve_from_terminal()` |
| `teleclaude/cli/telec/handlers/docs.py` | Replace `resolve_from_terminal()` with auth path |
| `teleclaude/cli/config_cli.py` | Replace `resolve_from_terminal()` with auth path |
| `teleclaude/cli/cartridge_cli.py` | Replace `resolve_from_terminal()` with auth path |
| 7+ test files | Update to typed fields, remove xfail markers |
| 5+ doc files | Update references |

**~32 files total.**

---

## Verification

1. `make lint` — pyright + ruff pass
2. `make test` — full test suite passes, xfail specs now pass
3. `grep -r "channel_metadata" teleclaude/ tests/ docs/ demos/` — zero hits
4. `grep -r "resolve_from_terminal" teleclaude/ tests/` — zero hits
5. `grep -r "create_headless_session" teleclaude/ tests/` — zero hits (except potential DB migration/schema comments)
6. Manual: daemon restart, create session via Telegram, verify actor identity resolves correctly
7. Manual: cross-computer message delivery via Redis, verify actor fields serialize/deserialize
