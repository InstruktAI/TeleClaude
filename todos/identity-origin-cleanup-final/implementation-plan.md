# Implementation Plan: identity-origin-cleanup-final

## Overview

Eliminate the untyped `channel_metadata` bag from the per-message data path, replace
with typed actor fields, route headless session creation through the command pipeline,
and remove the legacy `resolve_from_terminal()` identity path. Nine requirements (R1-R9)
in one atomic pass — no backward compatibility.

## Task Ordering Rationale

The tasks follow the data flow: model first (R1), then producers (R2, R9), then consumers
(R3, R4, R5), then the orthogonal headless/identity cleanup (R6, R7), then tests and docs
(existing tests, R8). This order means each task builds on the previous: after T1 adds
fields, T2 can populate them; after T2 populates, T3 can read them.

## Build Status

- [x] T1 — Add typed actor fields to `MessageMetadata` and remove the per-message actor bag
- [x] T2 — Move actor normalization to adapter edges
- [x] T3 — Simplify `CommandMapper` to read typed fields directly
- [x] T4 — Migrate Redis wire format to typed actor fields
- [x] T5 — Remove dead `target_computer` injection in Redis transport
- [x] T6 — Route headless session creation through the command pipeline
- [x] T7 — Remove the legacy terminal identity helper and update CLI callers
- [x] T8 — Update existing tests to the typed interfaces
- [x] T9 — Update docs and demo artifacts

## Build Notes

- `ChannelMetadata` was retained in [`teleclaude/core/models/_session.py`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/identity-origin-cleanup-final/teleclaude/core/models/_session.py) as the typed carrier still used by `create_channel` flows. The removed scope was the per-message untyped actor bag on `MessageMetadata`; keeping the separate create-channel type preserves current behavior without reintroducing the deleted message path.

---

## T1 — Add typed actor fields to MessageMetadata and remove channel_metadata (R1)

**What**: Add `actor_id`, `actor_name`, `actor_avatar_url`, `platform_message_id` fields
(all `str | None = None`) to the `MessageMetadata` dataclass in `_session.py`. Delete the
`channel_metadata: dict[str, object] | None = None` field. Delete the `ChannelMetadata`
dataclass (lines 18-22) which is unused outside this field.

**Why**: The typed fields are the new contract. All downstream tasks depend on these fields
existing on `MessageMetadata`. The `ChannelMetadata` class has a single field
(`target_computer`) that is not consumed through `MessageMetadata` — it was only used for
`create_channel` operations and is dead. Removing the untyped dict forces compile-time
errors at every site that still uses it, making the migration self-verifying.

**Files modified**:

- `teleclaude/core/models/_session.py` — add 4 fields, delete `channel_metadata` field, delete `ChannelMetadata` class

**Verification**: Remove xfail markers from `tests/unit/test_adapter_actor_normalization.py`
and `tests/unit/transport/redis_transport/test_target_computer_named_field.py::TestActorContextNamedFields`.
After this task:

From `test_adapter_actor_normalization.py`:

- `TestTelegramAdapterActorNormalization::test_telegram_metadata_carries_typed_actor_fields` -> GREEN
- `TestTelegramAdapterActorNormalization::test_telegram_actor_id_uses_platform_prefix` -> GREEN
- `TestDiscordAdapterActorNormalization::test_discord_metadata_carries_typed_actor_fields` -> GREEN
- `TestDiscordAdapterActorNormalization::test_discord_actor_id_uses_platform_prefix` -> GREEN
- `TestWhatsAppAdapterActorNormalization::test_whatsapp_metadata_carries_typed_actor_fields` -> GREEN
- `TestWhatsAppAdapterActorNormalization::test_whatsapp_actor_id_uses_platform_prefix` -> GREEN
- `TestPlatformIdPrefixConvention::test_platform_prefix_format` -> GREEN

From `test_target_computer_named_field.py::TestActorContextNamedFields`:

- `test_message_metadata_has_typed_actor_fields` -> GREEN
- `test_message_metadata_has_no_channel_metadata_field` -> GREEN

Also confirm `pyright` catches all broken references to `channel_metadata` on `MessageMetadata`
across the codebase (these become errors that guide T2-T5).

---

## T2 — Move actor normalization to adapter edges (R2, R9)

**What**: Each adapter that currently populates `channel_metadata` dict keys must instead
set typed fields on `MessageMetadata`. Platform-specific ID prefixing moves to the adapter.

Changes per adapter:

- **Telegram `input_handlers.py`** (lines 236-245): Replace `channel_metadata["message_id"]`,
  `channel_metadata["user_id"]`, `channel_metadata["user_name"]` with:

  ```python
  metadata.platform_message_id = str(update.effective_message.message_id)
  metadata.actor_id = f"telegram:{update.effective_user.id}"
  metadata.actor_name = display_name
  ```

- **Telegram `command_handlers.py`** (3 blocks: lines 119-120, 153-154, 194-195): Replace
  `channel_metadata["message_id"]` with `metadata.platform_message_id = str(update.effective_message.message_id)`.
  These commands (agent/resume/restart) only need message_id — no actor extraction downstream.

- **Telegram `callback_handlers.py`** (2 blocks: lines 379-380, 435-436): Replace
  `channel_metadata["user_id"]` with `metadata.actor_id = f"telegram:{from_user.id}"`.

- **Telegram `private_handlers.py`** (lines 265-266): Replace `channel_metadata["message_id"]`
  with `metadata.platform_message_id = str(update.effective_message.message_id)`.

- **Discord `gateway_handlers.py`** (lines 523-534): Replace the `channel_metadata` dict
  construction with typed field assignment on `metadata`:

  ```python
  metadata = self._metadata()
  metadata.platform_message_id = message_id
  metadata.actor_id = f"discord:{getattr(getattr(message, 'author', None), 'id', '')}"
  metadata.actor_name = self._discord_actor_name(author_obj, ...)
  ```

  Note: Lines 535-537 already extract actor fields for `ProcessMessageCommand` directly —
  that extraction stays as-is. The `channel_metadata` dict was only used by the mapper.

- **WhatsApp `whatsapp_handler.py`** (line 151): Replace
  `channel_metadata={"message_id": message_id}` with `platform_message_id=message_id` in
  the `MessageMetadata` constructor.

- **Fanout `_fanout.py`** (lines 330-336, R9): Replace `channel_metadata={...}` with typed
  fields. Drop `actor_role`, `actor_agent`, `actor_computer` — dead data never consumed
  by `_extract_actor()` or any downstream path:
  ```python
  metadata=MessageMetadata(
      origin=sender_origin,
      actor_id=actor_id,
      actor_name=actor_name,
  )
  ```

**Why**: Moving normalization to the adapter edge eliminates the centralized `_extract_actor`
method and makes each adapter self-documenting about what actor data it provides. The
platform-prefix contract (`telegram:{id}`, `discord:{id}`, `whatsapp:{id}`) is preserved in
behavior — only the location changes.

**Files modified**:

- `teleclaude/adapters/telegram/input_handlers.py`
- `teleclaude/adapters/telegram/command_handlers.py`
- `teleclaude/adapters/telegram/callback_handlers.py`
- `teleclaude/adapters/telegram/private_handlers.py`
- `teleclaude/adapters/discord/gateway_handlers.py`
- `teleclaude/hooks/whatsapp_handler.py`
- `teleclaude/core/agent_coordinator/_fanout.py`

**Verification**: After this task, all adapters produce `MessageMetadata` with typed fields
instead of dict. `grep -r "channel_metadata" teleclaude/adapters/ teleclaude/hooks/whatsapp_handler.py teleclaude/core/agent_coordinator/_fanout.py` — zero hits.

For R9 (dead data removal in fanout), confirm this test still passes:

- `tests/unit/transport/redis_transport/test_target_computer_named_field.py::TestDeadDataFieldsGuard::test_message_metadata_rejects_dead_data_fields` -> GREEN

---

## T3 — Simplify CommandMapper: delete \_extract_actor, read typed fields (R3)

**What**: Delete `CommandMapper._extract_actor()` (lines 58-100) and
`CommandMapper._normalize_actor_id()` (lines 51-55). Update all `map_*` methods to read
typed actor fields from `MessageMetadata` directly:

- **`map_telegram_input`** (lines 128-131): Replace `_extract_actor(metadata.channel_metadata, ...)`
  with reading `metadata.actor_id`, `metadata.actor_name`, `metadata.actor_avatar_url` directly
  into `ProcessMessageCommand`.

- **`map_redis_input`** (lines 170-210): Remove the `channel_metadata` parameter entirely.
  Add `metadata: MessageMetadata | None = None` parameter. For the `"message"` case (lines
  198-210), read actor fields from `metadata.*` instead of calling `_extract_actor`. The
  `_messaging.py` caller at line 225 already constructs `MessageMetadata` at line 240 — move
  that construction before the mapper call and pass it in.

- **`map_api_input`** (lines 329-332, 358-361): Remove the `_extract_actor(None, ...)` calls.
  The API path already reads actor fields from `payload.*` directly (lines 323-328, 352-357).
  The `_extract_actor(None, ...)` always returned `(None, None, None)` because the first arg
  is `None` — removing it is a no-op behavior change.

**Why**: After T2, all adapters provide typed fields. The centralized extraction logic that
reads untyped dict keys is dead code. Removing it simplifies the mapper and eliminates the
last consumer of the dict-based actor path. The API path cleanup removes a dead call that
always returned `(None, None, None)`.

**Files modified**:

- `teleclaude/core/command_mapper.py`
- `teleclaude/transport/redis_transport/_messaging.py` (lines 225-245: update caller to
  pass `MessageMetadata` to `map_redis_input` and remove `channel_metadata` from kwargs)

**Verification**: `pyright` passes with no errors on `command_mapper.py`. Method signatures
are internally consistent. Grep for `_extract_actor` and `_normalize_actor_id` — zero hits.

Remove xfail marker from `tests/unit/transport/redis_transport/test_target_computer_named_field.py::TestActorContextNamedFields::test_command_mapper_reads_typed_actor_fields_from_metadata`:

- `test_command_mapper_reads_typed_actor_fields_from_metadata` -> GREEN (verifies mapper reads from typed fields)

---

## T4 — Migrate Redis wire format to typed fields (R4)

**What**: Update the Redis transport to serialize/deserialize typed actor fields individually
instead of a JSON blob.

- **`_snapshot.py` `RedisInboundMessage`** (lines 46-58): Replace
  `channel_metadata: dict[str, object] | None = None` with:

  ```python
  actor_id: str | None = None
  actor_name: str | None = None
  actor_avatar_url: str | None = None
  platform_message_id: str | None = None
  ```

- **`_messaging.py` `_parse_redis_message`** (lines 373-405): Replace the
  `channel_metadata` JSON blob parsing (lines 373-380) with individual field reads:

  ```python
  actor_id = data.get(b"actor_id", b"").decode("utf-8") or None
  actor_name = data.get(b"actor_name", b"").decode("utf-8") or None
  actor_avatar_url = data.get(b"actor_avatar_url", b"").decode("utf-8") or None
  platform_message_id = data.get(b"platform_message_id", b"").decode("utf-8") or None
  ```

  Pass these to `RedisInboundMessage` constructor instead of `channel_metadata`.

- **`_request_response.py` `send_request`** (lines 126-127): Replace
  `json.dumps(metadata.channel_metadata)` with individual field serialization:

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

- **`_adapter.py` `RedisTransportMetadata`** (lines 160-193): Delete the
  `channel_metadata: str | None = None` field (line 171) and all `from_dict` handling for
  it (lines 176-183 channel_meta_val/channel_meta_str logic, line 192 constructor arg).

**Why**: The Redis wire format is the last place where actor data travels as a JSON blob.
Individual fields are simpler to debug, eliminate JSON serialization overhead, and maintain
type safety end-to-end.

**Files modified**:

- `teleclaude/core/models/_snapshot.py`
- `teleclaude/transport/redis_transport/_messaging.py`
- `teleclaude/transport/redis_transport/_request_response.py`
- `teleclaude/core/models/_adapter.py`

**Verification**: Remove xfail markers from `tests/unit/transport/redis_transport/test_redis_wire_format_typed_fields.py`.
After this task:

- `TestRedisInboundMessageTypedFields::test_redis_inbound_message_has_typed_actor_fields` -> GREEN
- `TestRedisInboundMessageTypedFields::test_redis_inbound_message_has_no_channel_metadata` -> GREEN
- `TestParseRedisMessageTypedFields::test_parse_redis_message_reads_individual_actor_fields` -> GREEN
- `TestParseRedisMessageTypedFields::test_parse_redis_message_handles_missing_actor_fields` -> GREEN
- `TestParseRedisMessageTypedFields::test_parse_redis_message_does_not_parse_channel_metadata_blob` -> GREEN
- `TestRedisTransportMetadataNoChannelMetadata::test_redis_transport_metadata_has_no_channel_metadata` -> GREEN
- `TestRedisTransportMetadataNoChannelMetadata::test_redis_transport_metadata_from_dict_ignores_channel_metadata` -> GREEN

---

## T5 — Remove dead target_computer injection in Redis transport (R5)

**What**: Delete the `target_computer` injection block in `_messaging.py`
`_handle_incoming_message` (lines 247-250):

```python
if parsed.initiator:
    metadata.channel_metadata = metadata.channel_metadata or {}
    metadata.channel_metadata["target_computer"] = parsed.initiator
```

**Why**: This code mutates `metadata.channel_metadata` to inject `target_computer`, but the
value already flows through `RedisTransportMetadata.target_computer` via a separate path.
The `_forward_stop_to_initiator` method reads `target_computer` from the session's
`origin_metadata.redis.target_computer`, which is populated by `RedisTransportMetadata` —
not from `channel_metadata`. After T1 removed `channel_metadata` from `MessageMetadata`,
this block is a compile error. After T3 restructured `_handle_incoming_message`, the
`metadata` construction no longer includes `channel_metadata`. This task removes the dead
block explicitly.

**Files modified**:

- `teleclaude/transport/redis_transport/_messaging.py`

**Verification**: Grep for `target_computer.*channel_metadata` — zero hits. The
`target_computer` still flows correctly via `RedisTransportMetadata`. Confirm these tests
still pass (they already pass and guard against regression):

From `test_target_computer_named_field.py::TestTargetComputerNamedField`:

- `test_redis_transport_metadata_has_target_computer_field` -> GREEN
- `test_handle_incoming_message_does_not_inject_target_computer_into_dict` -> GREEN
- `test_redis_mapper_does_not_produce_channel_metadata` -> GREEN

---

## T6 — Route headless session creation through command pipeline (R6)

**What**: Replace direct `db.create_headless_session()` calls with `CreateSessionCommand`
dispatched through the command service.

- **`daemon_hook_outbox.py` `_ensure_headless_session`** (lines 430-443): Replace
  `resolve_from_terminal()` + `db.create_headless_session()` with:

  ```python
  from teleclaude.core.models._adapter import TerminalOriginMetadata
  email = read_current_session_email()
  cmd = CreateSessionCommand(
      project_path=project_path or "",
      title=title,
      origin=InputOrigin.TERMINAL.value,
      origin_metadata=TerminalOriginMetadata(email=email) if email else None,
      system_role="worker",
      launch_intent=SessionLaunchIntent(
          kind=SessionLaunchKind.AGENT,
          agent=agent_str,
      ),
  )
  result = await get_command_service().create_session(cmd)
  ```

  Identity resolution happens inside the command handler via the standard `resolve()` path,
  which reads `origin_metadata` from the command. For terminal-origin sessions, the
  `TerminalOriginMetadata(email=...)` pattern applies.

- **`sessions_actions_routes.py` `_revive_session`** (lines 149-161): Same pattern — replace
  `db.create_headless_session()` with `CreateSessionCommand` through command service. The
  `identity` object is already available in scope from the API auth layer and provides the
  email for `TerminalOriginMetadata`.

- **`db/_sessions.py` `create_headless_session`** (lines 141+): After both callers are
  migrated, delete this method. It has no production callers.

- **Test migration**: Tests in `tests/unit/core/db/test__sessions.py` (lines 43, 85, 367)
  that directly call `create_headless_session()` must be updated to test session creation
  through the command pipeline instead, since the method is deleted.

**Why**: The command pipeline is the established pattern for session creation. Routing
headless sessions through it ensures identity resolution, event emission, and metadata
persistence follow the same path as all other session types. This eliminates a bypass
path that skipped event-bus emissions and identity normalization.

**Files modified**:

- `teleclaude/daemon_hook_outbox.py`
- `teleclaude/api/sessions_actions_routes.py`
- `teleclaude/core/db/_sessions.py`
- `tests/unit/core/db/test__sessions.py`

**Verification**: Remove xfail markers from `tests/unit/test_daemon_headless_pipeline.py`.
After this task:

- `TestDaemonHeadlessViaCommandPipeline::test_ensure_headless_session_does_not_call_db_directly` -> GREEN
- `TestDaemonHeadlessViaCommandPipeline::test_headless_session_does_not_call_resolve_from_terminal` -> GREEN

Grep for `create_headless_session` in `teleclaude/` — zero hits.

---

## T7 — Remove resolve_from_terminal and update CLI callers (R7)

**What**: Delete `IdentityResolver.resolve_from_terminal()` (lines 162-167 in `identity.py`).
Update the three CLI callers to use `resolve_by_email(read_current_session_email())` instead —
this is the exact logic that `resolve_from_terminal` wraps, inlined.

- **`teleclaude/cli/telec/handlers/docs.py`** (lines 79, 117): Replace
  `get_identity_resolver().resolve_from_terminal().person_role` with:

  ```python
  email = read_current_session_email()
  effective_role = get_identity_resolver().resolve_by_email(email).person_role if email else None
  ```

  Import `read_current_session_email` from `teleclaude.cli.session_auth`.

- **`teleclaude/cli/config_cli.py`** (line 63): Same pattern — replace with
  `resolve_by_email(read_current_session_email())`.

- **`teleclaude/cli/cartridge_cli.py`** (line 55): Same pattern.

**Why**: `resolve_from_terminal()` is a convenience wrapper that reads the terminal auth
email and resolves it. The three callers can do this directly. Removing the method
eliminates a legacy API surface that encouraged bypassing the standard `resolve()` path.
The `read_current_session_email()` function is already imported/available in the CLI
layer (`session_auth` module).

**Files modified**:

- `teleclaude/core/identity.py`
- `teleclaude/cli/telec/handlers/docs.py`
- `teleclaude/cli/config_cli.py`
- `teleclaude/cli/cartridge_cli.py`

**Verification**: Remove xfail markers from `tests/unit/test_daemon_headless_pipeline.py`
(the remaining CLI tests):

- `TestResolveFromTerminalRemoved::test_identity_resolver_has_no_resolve_from_terminal` -> GREEN
- `TestCliCallersAlternativePath::test_docs_handler_resolves_identity_without_resolve_from_terminal` -> GREEN
- `TestCliCallersAlternativePath::test_config_cli_resolves_identity_without_resolve_from_terminal` -> GREEN
- `TestCliCallersAlternativePath::test_cartridge_cli_resolves_identity_without_resolve_from_terminal` -> GREEN

Grep for `resolve_from_terminal` in `teleclaude/` — zero hits.

---

## T8 — Update existing tests to use typed fields (R1-R5 test impact)

**What**: Update all existing test files that reference `channel_metadata` to use typed
fields instead. These are non-xfail tests that break after T1-T5:

- **`tests/unit/adapters/telegram/test_input_handlers.py`**: Update `_metadata()` helper
  and assertions that reference `channel_metadata` dict keys to use typed fields.

- **`tests/unit/adapters/telegram/test_callback_handlers.py`**: Same pattern — update
  `channel_metadata` dict assertions to typed field assertions.

- **`tests/unit/core/models/test__adapter.py`**: Update tests for `RedisTransportMetadata`
  that test the `channel_metadata` field — remove those tests since the field is deleted.

- **`tests/unit/mirrors/test_generator.py`**: Update snapshot/mirror tests that reference
  `channel_metadata`.

- **`tests/unit/transport/redis_transport/test_target_computer_named_field.py`**: Update to
  verify `target_computer` flows through `RedisTransportMetadata` without `channel_metadata`.

- **`tests/unit/transport/redis_transport/test__adapter_noop.py`**: Update if it references
  `channel_metadata` on `RedisTransportMetadata`.

- **`tests/unit/transport/redis_transport/test__messaging.py`**: Update message parsing tests
  to use typed fields instead of JSON blob.

- **`tests/unit/cli/telec/handlers/test_docs.py`** (lines 57, 95): Update mock resolvers
  from `resolve_from_terminal=lambda: ...` to `resolve_by_email=lambda email: ...` pattern,
  matching the new CLI caller behavior from T7.

**Why**: These tests break after the production changes in T1-T7. Updating them maintains
test coverage for the existing behavior with the new typed interface.

**Files modified**:

- `tests/unit/adapters/telegram/test_input_handlers.py`
- `tests/unit/adapters/telegram/test_callback_handlers.py`
- `tests/unit/core/models/test__adapter.py`
- `tests/unit/mirrors/test_generator.py`
- `tests/unit/transport/redis_transport/test_target_computer_named_field.py`
- `tests/unit/transport/redis_transport/test__adapter_noop.py`
- `tests/unit/transport/redis_transport/test__messaging.py`
- `tests/unit/cli/telec/handlers/test_docs.py`

**Verification**: `make test` passes. Grep for `channel_metadata` in `tests/` — zero hits
(excluding xfail spec file docstrings that describe the pre-migration state).

---

## T9 — Update documentation (R8)

**What**: Update all documentation files that reference `channel_metadata`,
`resolve_from_terminal()`, or `create_headless_session()`:

- **`docs/project/spec/session-identity-truth.md`**: Update the origin data model section
  to reference typed actor fields instead of `channel_metadata`.

- **`docs/project/design/architecture/session-lifecycle.md`**: Update lifecycle flow to
  reflect that actor data flows through typed `MessageMetadata` fields.

- **`docs/project/design/architecture/layer-ownership.md`**: Update edge layer description
  to reflect adapter-edge normalization.

- **`demos/identity-origin-cleanup/demo.md`**: Update to reflect completion of the full
  cleanup (channel_metadata eliminated).

- **`demos/agent-session-auth/demo.md`**: Update if it references `channel_metadata`.

- **`todos/edge-session-creation/input.md`**: Update references to `channel_metadata`.

- **`todos/session-memory-extraction/input.md`**: Same.

**Why**: Stale documentation that references removed code creates confusion. The docs must
reflect the current system state.

**Files modified**:

- `docs/project/spec/session-identity-truth.md`
- `docs/project/design/architecture/session-lifecycle.md`
- `docs/project/design/architecture/layer-ownership.md`
- `demos/identity-origin-cleanup/demo.md`
- `demos/agent-session-auth/demo.md`
- `todos/edge-session-creation/input.md`
- `todos/session-memory-extraction/input.md`

**Verification**: Grep for `channel_metadata` in `docs/`, `demos/` — zero hits.
Grep for `resolve_from_terminal` in `docs/` — zero hits.
Grep for `create_headless_session` in `docs/` — zero hits.

---

## Final Verification

After all tasks:

1. `make lint` passes (pyright + ruff)
2. `make test` passes — all xfail specs pass with markers removed
3. `grep -r "channel_metadata" teleclaude/ tests/ docs/ demos/` — zero hits
4. `grep -r "resolve_from_terminal" teleclaude/ tests/` — zero hits
5. `grep -r "create_headless_session" teleclaude/ tests/` — zero hits (excluding schema/migration artifacts)
6. All success criteria from requirements.md are satisfied
