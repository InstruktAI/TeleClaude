# Review Findings: help-desk-discord

**Reviewer**: Claude (Opus 4.6)
**Review Round**: 1
**Date**: 2026-02-14

## Requirements Traceability

| Requirement                                     | Status | Evidence                                                                                                                      |
| ----------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Ingress: Discord message creates jailed session | PASS   | `_handle_on_message` -> `_resolve_or_create_session` -> `_create_session_for_message` with `origin=InputOrigin.DISCORD.value` |
| Identity Mapping: Snowflake -> Customer         | PASS   | `identity.py:126-133` maps `discord` origin to `CUSTOMER_ROLE`                                                                |
| Threading: Forum Thread (Type 15)               | PASS   | `create_channel` uses `_create_forum_thread` when `help_desk_channel_id` is configured                                        |
| Egress: Agent responses to same thread          | PASS   | `send_message` -> `_resolve_destination_channel` routes via `discord_meta.thread_id`                                          |
| Multi-Room Support: Concurrent sessions         | PASS   | `_find_session` resolves by `thread_id` first, ensuring session isolation per thread                                          |

## Deferrals

No deferrals.md exists. No silent deferrals detected. PASS.

---

## Important

### I-1: `CUSTOMER_ROLE` literal duplicated in adapter

**File**: `discord_adapter.py:461`

The adapter hardcodes `"human_role": "customer"` as a string literal in `_create_session_for_message` channel_metadata, while `identity.py:14` defines `CUSTOMER_ROLE = "customer"` as a constant. These must stay in sync manually. Should reference the constant.

### I-2: Test coverage thin on error paths

**Files**: `tests/unit/test_discord_adapter.py`

The test suite covers the three critical happy paths (ingress, forum thread creation, egress) but omits:

- Bot message filtering (`_is_bot_message` -- the ingress security gate)
- Empty/whitespace message guard
- Missing token startup validation
- `_resolve_destination_channel` error branches (no client, no channel mapping, channel not found)

These are not blocking for initial merge but should be addressed in a follow-up before the feature goes live.

---

## Suggestions

### S-1: Mixed ID type representation in `DiscordAdapterMetadata`

**File**: `models.py:141-148`

`user_id` is `str` while `guild_id`, `channel_id`, `thread_id` are `int`, even though all four are Discord Snowflake IDs. The `str` choice is driven by the identity system (`IdentityContext.platform_user_id` is `str`), but the asymmetry within a single dataclass is not self-documenting. Consider adding a comment explaining the rationale, or unifying to `int` with boundary conversion.

### S-2: Duplicate `_parse_optional_int` implementations

**Files**: `discord_adapter.py:311-319`, `config/__init__.py:552-560`

Two slightly different implementations of the same utility. The config version also handles `isinstance(value, int)`. Consider extracting to a shared utility.

### S-3: Redundant `user_id` / `discord_user_id` in channel_metadata

**File**: `discord_adapter.py:360-361`

Both `user_id` and `discord_user_id` are set to the same value in the channel_metadata dict. The identity resolver (line 127) checks both with `or`, so one would suffice.

### S-4: `store_channel_id` heuristic could benefit from a docstring

**File**: `discord_adapter.py:101-115`

The logic for distinguishing channel_id from thread_id based on whether the value differs from `_help_desk_channel_id` is correct for the forum model but non-obvious. A brief docstring would help future maintainers.

### S-5: `CUSTOMER_ROLE` not in `HUMAN_ROLES` closed set

**File**: `identity.py:14` vs `constants.py` `HUMAN_ROLES` tuple

Any code validating roles against `HUMAN_ROLES` will reject `"customer"`. Consider either adding it to `HUMAN_ROLES` or documenting the two-tier model (internal vs external roles).

---

## Positive Observations

- Clean adapter structure following the established `UiAdapter` pattern
- Proper use of `importlib.import_module` for lazy discord.py import
- Well-designed `DiscordClientLike` Protocol for testability
- Robust JSON serialization/deserialization with type coercion
- Backward-compatible config changes with sensible defaults
- Good test quality: proper mock isolation, meaningful assertions, async patterns
- Logging at appropriate levels throughout

---

## Verdict: APPROVE

The implementation satisfies all five requirements. The adapter correctly follows the UiAdapter contract, integrates cleanly into the adapter lifecycle, and provides proper Discord-specific session management with forum thread support. No critical bugs found. The Important findings are quality improvements that should be addressed but do not block merge.
