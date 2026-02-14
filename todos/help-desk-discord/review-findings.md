# Review Findings: help-desk-discord

**Reviewer**: Claude (Opus 4.6)
**Review Round**: 2
**Date**: 2026-02-14

## Requirements Traceability

| Requirement                                     | Status | Evidence                                                                                                                                                                                                                |
| ----------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ingress: Discord message creates jailed session | PASS   | `_handle_on_message` -> `_resolve_or_create_session` -> `_create_session_for_message` with `origin=discord`, `human_role=customer`. Tested in `test_discord_on_message_creates_session_and_dispatches_process_message`. |
| Identity Mapping: Snowflake -> Customer         | PASS   | `identity.py:126-133` maps `discord` origin to `CUSTOMER_ROLE`. Tested in `test_discord_user_maps_to_customer`.                                                                                                         |
| Threading: Forum Thread (Type 15)               | PASS   | `create_channel` uses `_create_forum_thread` when `help_desk_channel_id` is configured. Tested in `test_discord_create_channel_uses_forum_thread_when_configured`.                                                      |
| Egress: Agent responses to same thread          | PASS   | `send_message` -> `_resolve_destination_channel` routes via `discord_meta.thread_id`. Tested in `test_discord_send_message_routes_to_thread`.                                                                           |
| Multi-Room Support: Concurrent sessions         | PASS   | `_find_session` resolves by `thread_id` first, ensuring session isolation per thread. Architecture correct; reconnection paths untested (see I-5).                                                                      |

## Deferrals

No deferrals.md exists. No silent deferrals detected. PASS.

---

## Important

### I-1: `CUSTOMER_ROLE` constant misplaced and duplicated

**Files**: `identity.py:14`, `discord_adapter.py:460`, `constants.py:46`

`CUSTOMER_ROLE = "customer"` is defined in `identity.py` but the string literal `"customer"` is hardcoded in `discord_adapter.py:460`. Additionally, `CUSTOMER_ROLE` is absent from the `HUMAN_ROLES` tuple in `constants.py:46`, which could cause authorization gaps if code checks `role in HUMAN_ROLES`.

**Fix**: Move to `constants.py`, add to `HUMAN_ROLES`, and use the constant in `discord_adapter.py:460`.

### I-2: `edit_message`/`delete_message` swallow `AdapterError` without logging

**File**: `discord_adapter.py:248-251, 261-263`

Both methods catch `AdapterError` and return `False` with zero logging. Four distinct error conditions ("adapter not started", "channel mapping corrupt", "channel not found", "message_id not numeric") are collapsed into an opaque `False`.

**Fix**: Log the `AdapterError` at WARNING level before returning `False`.

### I-3: `_get_channel` catches all exceptions at DEBUG level

**File**: `discord_adapter.py:550-555`

The `except Exception` block logs at DEBUG level (invisible in production). Discord permission errors, rate limits, and network failures all silently become `None` ("channel not found"), producing misleading downstream error messages.

**Fix**: Log at WARNING level minimum.

### I-4: Bot message filtering (`_is_bot_message`) untested

**File**: `discord_adapter.py:378-388`

This is the ingress security gate that prevents infinite feedback loops. It has three filter branches (no author, `bot=True`, self-user match) and none are tested. A regression would silently create ghost sessions or infinite loops.

**Fix**: Add unit tests for all four branches (bot, self, no-author, normal-user).

### I-5: Multi-room session reconnection untested

**File**: `discord_adapter.py:427-446`

Requirement #5 (multi-room) is architecturally correct but only session _creation_ is tested. The `_find_session()` reconnection paths (match by `thread_id`, fallback to `channel_id + user_id`) have zero coverage. The test mock at `test_discord_adapter.py:140` always returns `[]`.

**Fix**: Add tests for reconnecting to an existing session by thread_id, and for the user_id fallback path.

### I-6: Unrelated test change bundled in branch

**File**: `tests/unit/test_diagram_extractors.py:45-46`

The test assertion change (`feat_transcript_discovery` -> `feat_transcript_path`) is unrelated to the Discord adapter feature. Should be on a separate commit or cherry-picked to main independently.

---

## Suggestions

### S-1: Mixed ID type representation in `DiscordAdapterMetadata`

**File**: `models.py:141-148`

`user_id` is `str` while `guild_id`, `channel_id`, `thread_id` are `int`, even though all four are Discord Snowflake IDs. The `str` choice is driven by `IdentityContext.platform_user_id`, but the asymmetry within a single dataclass is not self-documenting.

### S-2: Duplicate `_parse_optional_int` implementations

**Files**: `discord_adapter.py:311-319`, `config/__init__.py:552-560`

Two slightly different implementations of the same utility. The config version also handles `isinstance(value, int)`. Consider extracting to a shared utility.

### S-3: Redundant `user_id` / `discord_user_id` in channel_metadata

**File**: `discord_adapter.py:360-361`

Both `user_id` and `discord_user_id` are set to the same value. The identity resolver checks both with `or`, so one would suffice.

### S-4: `DiscordClientLike` protocol underspecifies actual contract

**File**: `discord_adapter.py:31-40`

The protocol declares `user`, `event`, `start`, `close` but the adapter also uses `get_channel` and `fetch_channel` via `getattr`. Consider adding these for documentation value.

### S-5: Silent message drop on session resolution failure

**File**: `discord_adapter.py:349-353`

When `_resolve_or_create_session` raises, the message is silently dropped. Consider sending a brief error reply to the Discord channel.

### S-6: Footer methods in `UiAdapter` hardcoded to Telegram

**File**: `ui_adapter.py:132-135, 139-142`

`_get_footer_message_id` and `_store_footer_message_id` only operate for `ADAPTER_KEY == "telegram"`. During output polling for Discord sessions, each update could create orphan footer messages since the footer ID is never stored/retrieved for Discord.

---

## Positive Observations

- Clean adapter structure following the established `UiAdapter` pattern
- Proper use of `importlib.import_module` for lazy discord.py import
- Well-designed `DiscordClientLike` Protocol for testability
- Robust JSON serialization/deserialization with type coercion for snowflakes
- Backward-compatible config changes with sensible defaults and env-var fallbacks
- Good test quality: proper mock isolation, behavioral assertions, deterministic async patterns
- Gateway handler guards (bot filtering, empty message rejection) prevent obvious failure modes
- Defensive config parsing with `getattr` guards for test compatibility

---

## Verdict: APPROVE

The implementation satisfies all five requirements. The adapter correctly follows the UiAdapter contract, integrates cleanly into the adapter lifecycle, and provides proper Discord-specific session management with forum thread support.

No critical bugs found. The Important findings (constant placement, error logging, test gaps) are quality improvements that should be addressed but do not block merge.
