# origin-metadata-rename — Implementation Plan

## Overview

Complete naming convergence by replacing the deprecated `channel_metadata` field
with `origin_metadata` across the command pipeline. This is not a mechanical
search-and-replace — `channel_metadata` is an active behavioral path that carries
actor identity through adapters, the `CommandMapper`, Redis transport, and fanout
reflection. The rename must preserve all behavioral contracts at each layer.

Two phases: model + pipeline rename, then adapter + transport propagation.

---

## Phase 1: Model and Command Pipeline

### Task 1.1: Remove `channel_metadata` from `MessageMetadata` (R4)

**What:** Remove the deprecated `channel_metadata` field from `MessageMetadata`
(`teleclaude/core/models/_session.py:38`). All callers must use `origin_metadata`
instead.

**Why:** `MessageMetadata` currently has both `channel_metadata` (deprecated,
`dict[str, object] | None`) and `origin_metadata` (`Mapping[str, object] | None`).
The dual fields create ambiguity about which carries the authoritative data. Callers
currently write to `channel_metadata` in the adapter layer but the session creation
path reads from `origin_metadata`. Removing the deprecated field forces a single
consistent path.

**Behavioral impact:** Every caller that currently sets `metadata.channel_metadata`
must be updated to set `metadata.origin_metadata` instead. The downstream consumers
that read `channel_metadata` (primarily `CommandMapper._extract_actor`) must be
updated to read `origin_metadata`.

**Files:**

- Modify `teleclaude/core/models/_session.py` — remove `channel_metadata` field

**Verification:**

- Remove xfail from `tests/unit/core/models/test__session.py::test_message_metadata_no_channel_metadata_field` —
  verify `MessageMetadata` does not have a `channel_metadata` attribute.
- Pre-commit hooks pass (will initially fail until downstream callers are updated in
  subsequent tasks).

---

### Task 1.2: Rename `_extract_actor` parameter and update CommandMapper (R4)

**What:** Rename the `channel_metadata` parameter of `CommandMapper._extract_actor`
(line 59 of `command_mapper.py`) to `origin_metadata`. Update all callers within
`CommandMapper`: `map_telegram_input` (line 129), `map_redis_input`, `map_api_input`.

**Why:** `_extract_actor` is the core function that extracts actor identity
(`actor_id`, `actor_name`, `actor_avatar_url`) from the per-request metadata dict.
It reads `user_id`, `discord_user_id`, `telegram_user_id`, `phone_number`,
`user_name`, `display_name`, `actor_id`, `actor_name`, and `actor_avatar_url` from
the dict. This is behavioral code — the dict keys it reads define what actor identity
the system extracts. The parameter rename must not change the dict keys it reads or
the values it returns.

**Files:**

- Modify `teleclaude/core/command_mapper.py` — rename parameter, update
  `map_telegram_input` to read `metadata.origin_metadata` instead of
  `metadata.channel_metadata` (line 129)

**Verification:**

- Remove xfail from `tests/unit/core/test_command_mapper.py::test_extract_actor_reads_origin_metadata` —
  verify `_extract_actor` extracts correct actor identity from an `origin_metadata`
  dict containing `user_id`, `user_name`, etc.
- Remove xfail from `tests/unit/core/test_command_mapper.py::test_map_telegram_message_uses_origin_metadata` —
  verify `map_telegram_input` for "message" event passes `metadata.origin_metadata`
  to `_extract_actor`.
- Pre-commit hooks pass.

---

### Task 1.3: Rename `RedisTransportMetadata.channel_metadata` to `origin_metadata` (R4)

**What:** Rename the `channel_metadata` field on `RedisTransportMetadata`
(`teleclaude/core/models/_adapter.py:171`) to `origin_metadata`. Update `from_dict`
to accept both old and new key for backward compatibility with existing DB/Redis data.

**Why:** `RedisTransportMetadata` is serialized to JSON for Redis transport. Existing
data in Redis may contain the `channel_metadata` key. The `from_dict` method must
accept both keys during a transition period; `to_dict` writes only `origin_metadata`.

**Behavioral impact:** `from_dict` currently reads `raw.get("channel_metadata")`.
After the rename, it reads `raw.get("origin_metadata")` first, then falls back to
`raw.get("channel_metadata")` for backward compatibility.

**Files:**

- Modify `teleclaude/core/models/_adapter.py` — rename field, update `from_dict`
  deserialization with backward-compatible key lookup
- Modify `teleclaude/core/models/_snapshot.py` — update if referencing
  `channel_metadata`

**Verification:**

- Remove xfail from `tests/unit/core/models/test__adapter.py::test_redis_transport_metadata_origin_metadata_field` —
  verify `RedisTransportMetadata` has `origin_metadata` field, not `channel_metadata`.
- Remove xfail from `tests/unit/core/models/test__adapter.py::test_redis_transport_metadata_backward_compat_deserialization` —
  verify `RedisTransportMetadata.from_dict({"channel_metadata": "..."})` still
  deserializes correctly into the `origin_metadata` field.
- Remove xfail from `tests/unit/core/models/test__adapter.py::test_redis_transport_metadata_to_dict_uses_new_key` —
  verify `to_dict()` output contains `origin_metadata`, not `channel_metadata`.
- Pre-commit hooks pass.

---

## Phase 2: Adapter and Transport Propagation

### Task 2.1: Update Telegram adapters (R4, R5)

**What:** Update all Telegram adapter files that set `metadata.channel_metadata` to
use `metadata.origin_metadata` instead.

**Why:** The Telegram adapters populate `channel_metadata` with per-message identity
data (`message_id`, `user_id`, `user_name`) that flows to `CommandMapper._extract_actor`.
After Task 1.1 removes the field from `MessageMetadata`, these assignments would fail.
The behavioral contract: actor identity extracted from Telegram messages must remain
identical after the rename.

**Files:**

- Modify `teleclaude/adapters/telegram/input_handlers.py` — lines 236-245, change
  `metadata.channel_metadata` to `metadata.origin_metadata`
- Modify `teleclaude/adapters/telegram/callback_handlers.py` — same pattern
- Modify `teleclaude/adapters/telegram/command_handlers.py` — same pattern
- Modify `teleclaude/adapters/telegram/private_handlers.py` — same pattern

**Verification:**

- Remove xfail from `tests/unit/adapters/telegram/test_input_handlers.py::test_message_sets_origin_metadata` —
  verify that processing a Telegram message populates `metadata.origin_metadata`
  (not `channel_metadata`) with `message_id`, `user_id`, `user_name`.
- Remove xfail from `tests/unit/adapters/telegram/test_callback_handlers.py::test_callback_sets_origin_metadata` —
  same pattern for callback handler.
- Pre-commit hooks pass.

---

### Task 2.2: Update Discord gateway and WhatsApp handler (R4, R5)

**What:** Update Discord gateway handler and WhatsApp handler dispatch path to use
`origin_metadata` instead of `channel_metadata`.

**Why:** Discord gateway (`_fanout.py:330`) constructs `MessageMetadata` with
`channel_metadata` containing actor reflection data (`actor_id`, `actor_name`,
`actor_role`). WhatsApp handler (`whatsapp_handler.py:151`) constructs
`MessageMetadata` with `channel_metadata={"message_id": ...}`. Both must use
`origin_metadata` after the field removal.

**Files:**

- Modify `teleclaude/adapters/discord/gateway_handlers.py` — rename
  `channel_metadata` to `origin_metadata` in `MessageMetadata` construction
- Modify `teleclaude/hooks/whatsapp_handler.py` — in `_dispatch_whatsapp_command`
  (line 149-152), change `channel_metadata=` to `origin_metadata=`
- Modify `teleclaude/core/agent_coordinator/_fanout.py` — line 330, change
  `channel_metadata=` to `origin_metadata=` in reflection metadata construction

**Verification:**

- Remove xfail from `tests/unit/hooks/test_whatsapp_handler.py::test_dispatch_uses_origin_metadata` —
  verify `_dispatch_whatsapp_command` constructs `MessageMetadata` with
  `origin_metadata`, not `channel_metadata`.
- Pre-commit hooks pass.

---

### Task 2.3: Update Redis transport (R4, R5)

**What:** Update Redis transport messaging to use the renamed
`RedisTransportMetadata.origin_metadata` field.

**Why:** The Redis transport messaging layer (`_messaging.py:230`) reads
`parsed.channel_metadata` and constructs `MessageMetadata` with
`channel_metadata=parsed.channel_metadata`. After the model rename, it must use
`origin_metadata`. The `_request_response.py` module may also reference the field.

**Files:**

- Modify `teleclaude/transport/redis_transport/_messaging.py` — update references
  to `channel_metadata` to use `origin_metadata` (lines 230, 241, 249)
- Modify `teleclaude/transport/redis_transport/_request_response.py` — update if
  referencing `channel_metadata`

**Verification:**

- Remove xfail from `tests/unit/transport/redis_transport/test__messaging.py::test_redis_message_uses_origin_metadata` —
  verify that processing a Redis message constructs `MessageMetadata` with
  `origin_metadata`, not `channel_metadata`.
- `grep -r "channel_metadata" teleclaude/` returns zero production code hits (final
  sweep after all tasks complete).
- Pre-commit hooks pass (lint, typecheck, full test suite).

---

## Risks

- **RedisTransportMetadata backward compatibility:** Renaming could break
  deserialization of existing Redis/DB data. Mitigation: `from_dict` accepts both
  key names (Task 1.3).

- **Actor extraction regression:** `_extract_actor` reads specific dict keys from the
  metadata dict. The rename changes the parameter name and where callers source the
  dict, but must not change the dict keys or values. Tests verify actor identity
  extraction produces identical results.

- **Fanout reflection metadata:** The fanout constructs `channel_metadata` with
  `actor_role: "system"` for cross-session reflection. This is behavioral — the
  presence of `actor_role` in the metadata affects how the reflected message is
  attributed. Test coverage must verify reflection metadata propagation.

## Dependencies

- `edge-http-migration` — HTTP callers must be migrated first so that the WhatsApp
  handler is already using the internal HTTP client (not directly constructing
  `CreateSessionCommand` with `origin_metadata`).
