# Review Findings: discord-session-routing

## Requirements Traceability

| SC   | Status | Evidence                                                                                                                                                                            |
| ---- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SC-1 | PASS   | `_is_managed_message()` includes project forums via `_get_managed_forum_ids()`. Non-customer messages accepted from any managed forum.                                              |
| SC-2 | PASS   | Customer gating at discord_adapter.py:999 — `_is_customer_session(session) and not self._is_help_desk_thread(message)`.                                                             |
| SC-3 | PASS   | `ensure_channel(session)` signature updated in `UiAdapter`, `TelegramAdapter`, `DiscordAdapter`. `adapter_client._route_to_ui()` no longer calls `get_display_title_for_session()`. |
| SC-4 | PASS   | `_resolve_target_forum()` → `_match_project_forum()` routes to per-project forums via `_project_forum_map`.                                                                         |
| SC-5 | PASS   | `_resolve_target_forum()` falls back to `_all_sessions_channel_id`.                                                                                                                 |
| SC-6 | PASS   | `_build_thread_topper()` produces structured metadata (project, agent/speed, tc/ai IDs). Passed as `content` to `_create_forum_thread()` at discord_adapter.py:562.                 |
| SC-7 | PASS   | `TelegramAdapter.ensure_channel()` calls `get_display_title_for_session()` internally at telegram_adapter.py:213. Behavior unchanged.                                               |
| SC-8 | PASS   | 1847 tests pass, lint clean (0 errors, 0 warnings). 3 pre-existing config CLI failures unrelated to this branch.                                                                    |

## Paradigm-Fit Assessment

- **Data flow**: Follows established adapter pattern. Title construction moved into adapter-owned `ensure_channel()` where each adapter determines its own title strategy. Core (`adapter_client`) no longer makes adapter-specific presentation decisions.
- **Component reuse**: Reuses `_is_customer_session()`, `get_short_project_name()`, `_parse_optional_int()` patterns. No copy-paste duplication found.
- **Pattern consistency**: New methods follow existing naming conventions (`_build_*`, `_is_*`, `_resolve_*`, `_match_*`). Inline imports consistent with existing circular-dependency avoidance pattern.

## Critical

None.

## Important

1. **Stale docstring references removed feature flag** — `discord_adapter.py:232`: `_ensure_discord_infrastructure()` docstring still says "behind discord_project_forum_mirroring flag" but the flag was removed in this branch. Comments must describe the present, not the past.

## Suggestions

1. **Dead `display_title` computation in `_execute_on_lane`** — `adapter_client.py:591`: `get_display_title_for_session(session)` is still called and passed to `recover_lane_error()`, but no `recover_lane_error` implementation uses it after this refactor (Telegram's recovery now calls `ensure_channel(session)` without title). The implementation plan acknowledged this call (Task 1.2: "if it exists for the same purpose") and scoping it out was reasonable. Worth cleaning as a follow-on to remove the async DB call and the vestigial `display_title` parameter from the `recover_lane_error` signature chain.
2. **`_get_managed_forum_ids()` rebuilds set per message** — `discord_adapter.py:1110`: Constructs a new set on every call from `_is_managed_message()`. Could be cached and invalidated when `_project_forum_map` changes. Low priority — message volume is moderate and the set is small.

## Why No Critical/Blocking Issues

1. **Paradigm-fit verified**: All new methods follow established adapter patterns. Title construction is now adapter-owned (Discord builds context-aware titles, Telegram builds metadata-rich titles). No bypassing of the data layer.
2. **Requirements validated**: All 8 success criteria traced to specific code locations and verified.
3. **Copy-paste duplication checked**: `_is_help_desk_thread` and `_is_managed_message` share a similar channel-check pattern but serve distinct purposes (narrow help-desk check vs broad managed-forum check) — not duplication.
4. **Security boundary verified**: The replacement of `_is_help_desk_message` with `_is_managed_message` + `_is_help_desk_thread` correctly maintains customer isolation. The managed forum set is a superset of the old check, and the additional role-based gate at line 999 restricts customers to help desk threads.

## Verdict

**APPROVE**

The implementation cleanly addresses all requirements across 6 focused commits. The stale docstring (Important #1) should be fixed but does not block delivery.
