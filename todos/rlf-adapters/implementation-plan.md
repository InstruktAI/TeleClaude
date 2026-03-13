# Implementation Plan: rlf-adapters

## Overview

Three large adapter files need structural decomposition using the mixin-based
package pattern. The `telegram/` package (5 submodules, 2,180 lines) is the
established precedent. Each file becomes a package with Mixin classes; the main
adapter class inherits from all mixins and stays as the slim orchestrator.

Order: ui_adapter.py first (base class), then discord_adapter.py (biggest win),
then telegram_adapter.py (incremental addition to existing telegram/ package).

---

## Phase 1: ui_adapter.py → ui/ package

### Task 1.1: Create ui/output_delivery.py (OutputDeliveryMixin)

**File(s):** `teleclaude/adapters/ui/output_delivery.py`

Extract to `OutputDeliveryMixin`:
- `send_output_update` (lines 417–495)
- `_deliver_output` (lines 281–300)
- `_deliver_output_unlocked` (lines 302–332)
- `_try_edit_output_message` (lines 334–363)
- `send_error_feedback` (lines 365–382)
- `_send_footer` (lines 688–721)
- `_build_footer_text` (lines 723–731)
- `format_output` (lines 733–740)
- `_build_output_metadata` (lines 742–754)
- `_build_footer_metadata` (lines 756–761)
- `_build_metadata_for_thread` (lines 684–686)

Mixin requires from host: `client`, `ADAPTER_KEY`, `THREADED_OUTPUT`,
`max_message_size`, `_get_output_message_id`, `_store_output_message_id`,
`_clear_output_message_id`, `_get_footer_message_id`, `_store_footer_message_id`,
`_clear_footer_message_id`, `_cleanup_footer_if_present`, `send_message`,
`edit_message`, `delete_message`.

- [x] Create `teleclaude/adapters/ui/` directory
- [x] Write `teleclaude/adapters/ui/output_delivery.py` with `OutputDeliveryMixin`
- [x] Remove extracted methods from `ui_adapter.py`
- [x] Have `UiAdapter` inherit from `OutputDeliveryMixin`

### Task 1.2: Create ui/threaded_output.py (ThreadedOutputMixin)

**File(s):** `teleclaude/adapters/ui/threaded_output.py`

Extract to `ThreadedOutputMixin`:
- `send_threaded_output` (lines 497–526)
- `_send_threaded_output_unlocked` (lines 528–682)

Mixin requires from host: `THREADED_OUTPUT`, `ADAPTER_KEY`, `max_message_size`,
`THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS`, `_get_char_offset`, `_set_char_offset`,
`_get_output_message_id`, `_store_output_message_id`, `_clear_output_message_id`,
`_cleanup_footer_if_present`, `_get_badge_sent`, `_set_badge_sent`,
`_build_metadata_for_thread`, `_deliver_output_unlocked`, `send_message`, `client`.

- [x] Write `teleclaude/adapters/ui/threaded_output.py` with `ThreadedOutputMixin`
- [x] Remove extracted methods from `ui_adapter.py`
- [x] Have `UiAdapter` also inherit from `ThreadedOutputMixin`

### Task 1.3: Create ui/__init__.py and update ui_adapter.py

**File(s):** `teleclaude/adapters/ui/__init__.py`, `teleclaude/adapters/ui_adapter.py`

- [x] Write `ui/__init__.py` re-exporting `OutputDeliveryMixin`, `ThreadedOutputMixin`
- [x] Update `ui_adapter.py` to inherit from both mixins
- [x] Verify `ui_adapter.py` is under 800 lines (583 lines)

---

## Phase 2: discord_adapter.py → discord/ package

### Task 2.1: Create discord/message_ops.py (MessageOperationsMixin)

**File(s):** `teleclaude/adapters/discord/message_ops.py`

Extract to `MessageOperationsMixin`:
- `_split_message_chunks` (1415–1437)
- `drop_pending_output` (1438–1441)
- `send_message` (1442–1468)
- `_send_single_message` (1469–1487)
- `_send_reflection_via_webhook` (1488–1545)
- `_get_or_create_reflection_webhook` (1546–1576)
- `_discord_actor_name` (1577–1586)
- `_discord_actor_avatar_url` (1587–1593)
- `edit_message` (1594–1615)
- `delete_message` (1616–1628)
- `send_file` (1629–1648)
- `_fit_message_text` (1649–1668)
- `_build_metadata_for_thread` (1669–1673)
- `_fit_output_to_limit` (1686–1698)
- `get_max_message_length` (1699–1701)
- `get_ai_session_poll_interval` (1702–1705)
- `_parse_optional_int` (1706–1715)
- `discover_peers` (1674–1676)
- `poll_output_stream` (1677–1685)

- [x] Write `teleclaude/adapters/discord/message_ops.py`
- [x] Remove extracted methods from `discord_adapter.py`

### Task 2.2: Create discord/channel_ops.py (ChannelOperationsMixin)

**File(s):** `teleclaude/adapters/discord/channel_ops.py`

Extract to `ChannelOperationsMixin`:
- `store_channel_id` (171–186)
- `ensure_channel` (193–221)
- `_resolve_target_forum` (223–243)
- `_match_project_forum` (245–253)
- `_resolve_forum_context` (255–297)
- `_build_thread_title` (299–313)
- `_is_customer_session` (316–318)
- `_build_thread_topper` (320–333)
- `create_channel` (1305–1339)
- `update_channel_title` (1340–1360)
- `close_channel` (1361–1378)
- `reopen_channel` (1379–1396)
- `delete_channel` (1397–1413)
- `_is_forum_channel` (2699–2701)
- `cleanup_stale_resources` (2706–2722)
- `_cleanup_forum_threads` (2723–2771)
- `_thread_ownership` (2772–2792)

- [x] Write `teleclaude/adapters/discord/channel_ops.py`
- [x] Remove extracted methods from `discord_adapter.py`

### Task 2.3: Create discord/infra.py (InfrastructureMixin)

**File(s):** `teleclaude/adapters/discord/infra.py`

Extract to `InfrastructureMixin`:
- `_validate_channel_id` (339–347)
- `_ensure_discord_infrastructure` (349–459)
- `_ensure_category` (461–506)
- `_find_category_by_name_robust` (508–554)
- `_build_project_forum_map` (556–570)
- `_resolve_project_from_forum` (572–573)
- `_resolve_parent_forum_id` (575–582)
- `_extract_forum_thread_result` (585–594)
- `_build_session_launcher_view` (596–599)
- `_post_or_update_launcher` (601–679)
- `_resolve_interaction_forum_id` (681–700)
- `_pin_launcher_message` (702–717)
- `_pin_launcher_thread` (719–735)
- `_ensure_project_forums` (737–761)
- `_sync_project_forum_positions` (763–809)
- `_ensure_team_channels` (810–849)
- `_find_or_create_private_text_channel` (850–896)
- `_build_private_overwrites` (897–931)
- `_ensure_channel_private` (932–958)
- `_resolve_guild` (959–976)
- `_find_or_create_category` (977–1008)
- `_find_or_create_forum` (1009–1046)
- `_find_or_create_text_channel` (1047–1088)
- `_persist_project_forum_ids` (1089–1122)
- `_persist_discord_channel_ids` (1123–1148)

- [x] Write `teleclaude/adapters/discord/infra.py`
- [x] Remove extracted methods from `discord_adapter.py`

### Task 2.4: Create discord/gateway_handlers.py (GatewayHandlersMixin)

**File(s):** `teleclaude/adapters/discord/gateway_handlers.py`

Extract to `GatewayHandlersMixin`:
- `_register_cancel_slash_command` (1716–1739)
- `_register_gateway_handlers` (1740–1760)
- `_handle_on_ready` (1761–1813)
- `_handle_discord_dm` (1814–1897)
- `_handle_discord_invite_token` (1898–1962)
- `_handle_on_message` (1963–2070)
- `_emit_close_for_thread` (2071–2119)
- `_handle_thread_delete` (2120–2132)
- `_handle_thread_update` (2133–2157)
- `_is_bot_message` (2158–2169)
- `_is_managed_message` (2170–2202)
- `_get_managed_forum_ids` (2203–2212)
- `_is_help_desk_thread` (2213–2227)

- [x] Write `teleclaude/adapters/discord/gateway_handlers.py`
- [x] Remove extracted methods from `discord_adapter.py`

### Task 2.5: Create discord/input_handlers.py (InputHandlersMixin)

**File(s):** `teleclaude/adapters/discord/input_handlers.py`

Extract to `InputHandlersMixin`:
- `_extract_audio_attachment` (2233–2244)
- `_extract_file_attachments` (2245–2256)
- `_handle_voice_attachment` (2257–2304)
- `_handle_file_attachments` (2305–2362)
- `_resolve_or_create_session` (2363–2395)
- `_is_thread_channel` (2396–2399)
- `_extract_channel_ids` (2400–2409)
- `_find_session` (2410–2433)
- `_handle_launcher_click` (2434–2476)
- `_handle_cancel_slash` (2477–2511)
- `_create_session_for_message` (2512–2553)
- `_update_session_discord_metadata` (2554–2584)
- `_resolve_destination_channel` (2585–2617)
- `_fetch_destination_message` (2618–2632)
- `_get_channel` (2633–2650)
- `_create_forum_thread` (2651–2670)
- `create_escalation_thread` (2671–2698)

- [x] Write `teleclaude/adapters/discord/input_handlers.py`
- [x] Remove extracted methods from `discord_adapter.py`

### Task 2.6: Create discord/relay_ops.py (RelayOperationsMixin)

**File(s):** `teleclaude/adapters/discord/relay_ops.py`

Extract to `RelayOperationsMixin`:
- `_forward_to_relay_thread` (2797–2816)
- `_handle_relay_thread_message` (2817–2834)
- `_deliver_to_customer` (2835–2843)
- `_is_agent_tag` (2845–2854)
- `_handle_agent_handback` (2855–2876)
- `_collect_relay_messages` (2877–2921)
- `_sanitize_relay_text` (2922–2932)
- `_compile_relay_context` (2933–2951)

- [x] Write `teleclaude/adapters/discord/relay_ops.py`
- [x] Remove extracted methods from `discord_adapter.py`

### Task 2.7: Update discord/__init__.py and discord_adapter.py

**File(s):** `teleclaude/adapters/discord/__init__.py`, `teleclaude/adapters/discord_adapter.py`

- [x] Update `discord/__init__.py` to re-export all new mixin classes
- [x] Update `discord_adapter.py` to inherit from all new mixins (keeping UiAdapter last)
- [x] Verify `discord_adapter.py` is under 800 lines (329 lines)
- [x] Also include per-adapter output overrides still remaining in discord_adapter.py:
  - `_get_output_message_id` (1153–1158)
  - `_store_output_message_id` (1159–1164)
  - `_clear_output_message_id` (1165–1170)
  - `send_typing_indicator` (1171–1193)
  - `send_output_update` (1194–1239) - override
  - `_handle_session_status` (1240–1273) - override
  - `_handle_session_updated` (1274–1304) - override

---

## Phase 3: telegram_adapter.py incremental decomposition

### Task 3.1: Create telegram/lifecycle.py (LifecycleMixin)

**File(s):** `teleclaude/adapters/telegram/lifecycle.py`

Extract to `LifecycleMixin`:
- `_ensure_started` (591–596)
- `bot` property (597–609)
- `start` (723–852)
- `_run_startup_housekeeping` (853–918)
- `stop` (919–935)

- [x] Write `teleclaude/adapters/telegram/lifecycle.py`
- [x] Remove extracted methods from `telegram_adapter.py`
- [x] Export from `telegram/__init__.py`

### Task 3.2: Create telegram/private_handlers.py (PrivateHandlersMixin)

**File(s):** `teleclaude/adapters/telegram/private_handlers.py`

Extract to `PrivateHandlersMixin`:
- `_register_simple_command_handlers` (332–354)
- `_handle_cancel_command` (356–359)
- `_handle_private_start` (360–445)
- `_handle_private_text` (446–528)
- `_handle_simple_command` (539–590)
- `delete_message` (529–538)

- [x] Write `teleclaude/adapters/telegram/private_handlers.py`
- [x] Remove extracted methods from `telegram_adapter.py`
- [x] Export from `telegram/__init__.py`

### Task 3.3: Move additional methods to telegram/channel_ops.py

**File(s):** `teleclaude/adapters/telegram/channel_ops.py`, `teleclaude/adapters/telegram_adapter.py`

Move from telegram_adapter.py into channel_ops.py:
- `_send_or_update_menu_message` (1146–1183)
- `_get_session_from_topic` (1184–1232)
- `_require_session_from_topic` (1233–1276)
- `discover_peers` (1277–1290)
- `create_topic` (1291–1297)
- `get_all_topics` (1298–1308)
- `send_message_to_topic` (1309–1342)
- `poll_output_stream` (1343–1365)
- `drop_pending_output` (1366–end)

- [x] Add methods to `telegram/channel_ops.py`
- [x] Remove extracted methods from `telegram_adapter.py`

### Task 3.4: Verify telegram_adapter.py size and update __init__.py

**File(s):** `teleclaude/adapters/telegram/__init__.py`, `teleclaude/adapters/telegram_adapter.py`

- [x] Verify `telegram_adapter.py` is under 800 lines (626 lines)
- [x] Update `telegram/__init__.py` to re-export `LifecycleMixin`, `PrivateHandlersMixin`
- [x] Add new mixin inheritance to `TelegramAdapter`

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Add or update tests for the changed behavior
- [x] Run `make test` — 139 passed

### Task 4.2: Quality Checks

- [x] Run `make lint` — all changed adapter files pass ruff; pre-existing guardrail violations in 18 unrelated files are non-blocking
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — no deferrals
