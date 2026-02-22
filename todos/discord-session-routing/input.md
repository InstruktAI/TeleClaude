# Discord Session Routing & Per-Project Forums

## Problem

Discord session management has several interrelated issues:

1. **Channel-based message gating is wrong.** `_is_help_desk_message()` gates on channel ID, dropping messages from admin session threads. The principle should be: anyone who can see a channel can send from it. Authorization belongs at the receiving end (role-based), not at the channel gate.

2. **One-size-fits-all title built centrally.** `adapter_client._send_to_all_ui_adapters()` constructs a single `display_title` via `get_display_title_for_session()` and passes it to all adapters. Adapters don't own their title strategy. The metadata-rich format (`{project}: {agent}-{speed}@{computer} - {description}`) suits Telegram's flat topic list but is wrong for Discord.

3. **All sessions land in a single catch-all forum.** The `discord_project_forum_mirroring` feature flag is off, so every session thread goes into `_all_sessions_channel_id` regardless of project. The per-project forum infrastructure already exists behind the flag.

4. **Thread header message is a placeholder.** Discord forum threads get their first message from `_create_forum_thread(content="Initializing Help Desk session...")`. This is the "topper" -- the persistent first message users scroll up to find. It should carry session metadata (project, agent, speed, IDs). The "footer" concept (moving message below output) does not apply to Discord's threaded model.

## Intended Outcome

### 1. Role-based message acceptance

Replace `_is_help_desk_message()` channel-gating with role-aware logic:

- Admins and members can send messages from any managed channel they can see.
- Customers remain scoped to help desk threads.
- The gate checks the sender's role (admin/member/customer) and the channel context, not just the channel ID.

### 2. Adapter-owned title and header strategies

**Architectural principle:** Core distributes to adapters. Adapters own all presentation logic -- titles, headers, formatting. Core should pass the session object and let each adapter build what it needs.

Current violation: `adapter_client._send_to_all_ui_adapters()` calls `get_display_title_for_session()` centrally and passes the pre-built title to `ensure_ui_channels()`. This must change so each adapter constructs its own title.

Per-adapter strategies:

- **Telegram:** Keeps the current metadata-rich title format (`{project}: {agent}-{speed}@{computer} - {description}`) because the flat topic list needs it for visual identification. The "footer" stays as a moving message below output.
- **Discord (per-project forums):** Title is just the session description (e.g., "Fix auth flow"). The project context is implicit from which forum the thread lives in. Session metadata goes into the thread's first message (the "topper"). No moving footer -- the topper is permanent and users scroll up to find it.
- **Discord (catch-all fallback):** When a session can't be mapped to a project forum, the title is prefixed with the project name: `{project}: {description}`. This preserves discoverability in the flat fallback forum.

### 3. Per-project Discord forums (unlock feature flag)

- Enable `discord_project_forum_mirroring` by default (or remove the flag).
- On startup, `_ensure_project_forums()` creates a forum channel per trusted dir under a "Projects" category.
- Forum IDs are written back to `config.yaml` via `_persist_project_forum_ids()` into each trusted dir's `discord_forum` field. This already works.
- `_all_sessions_channel_id` becomes a fallback for sessions that cannot be mapped to any trusted directory (orphan sessions, sessions without a project path).
- Session routing in `_resolve_target_forum()` checks the session's `project_path` against trusted dirs' `discord_forum` IDs before falling back to `_all_sessions_channel_id`.

### 4. Enriched thread header (topper)

The first message in a Discord forum thread is the permanent header. Currently a placeholder. Should contain:

```
project: TeleClaude | agent: gemini/fast
tc: {session_id}
ai: {native_session_id}
```

This is NOT a footer that moves. It's sent once at thread creation and stays pinned at the top. Users scroll up to find it. The bottom of the thread is always just streaming output.

For Telegram, the same metadata can be added to the existing footer message (`_build_session_id_lines()`), which already shows session IDs.

## Architecture: adapter routing modules

Each adapter should have its own routing logic module, cleanly separated from core. The pattern:

1. **Core (`adapter_client`)**: Distributes operations to registered adapters. Passes the `Session` object. Does NOT build titles, format messages, or make routing decisions.
2. **Adapter routing**: Each adapter decides:
   - Which channel/forum/topic to route to
   - How to build the title
   - How to format the header/footer/topper
   - How to handle incoming messages (role-based acceptance)

Current state: This boundary is _mostly_ clean. The main violation is `get_display_title_for_session()` being called in `adapter_client` before `ensure_ui_channels()`. Title construction should move into each adapter's `ensure_channel()` method.

## Existing code references

| What                   | Where                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------ |
| Feature flag           | `is_discord_project_forum_mirroring_enabled()` in `teleclaude/core/feature_flags.py` |
| Project forums         | `_ensure_project_forums()` at `discord_adapter.py:287`                               |
| Forum persistence      | `_persist_project_forum_ids()` at `discord_adapter.py:414`                           |
| Trusted dir model      | `discord_forum` field on trusted dir config                                          |
| Central title builder  | `build_display_title()` at `session_utils.py:287`                                    |
| Central title caller   | `adapter_client._send_to_all_ui_adapters()` at `adapter_client.py:257`               |
| Display title          | `get_display_title_for_session()` at `session_utils.py:337`                          |
| Channel gate           | `_is_help_desk_message()` at `discord_adapter.py:1019`                               |
| Forum routing          | `_resolve_target_forum()` at `discord_adapter.py:161`                                |
| Thread creation topper | `_create_forum_thread(content=...)` at `discord_adapter.py:1286`                     |
| Footer (Telegram)      | `_build_footer_text()` / `_build_session_id_lines()` at `ui_adapter.py:628-690`      |
| Footer get/store/clear | `_get_footer_message_id()` at `ui_adapter.py:142` (hardcoded to Telegram)            |
| Threaded output        | `send_threaded_output()` at `ui_adapter.py:446`                                      |

## Existing related todos

- `rolling-session-titles` -- complementary (title re-summarization); independent of this work
- `discord-media-handling` -- image/file attachment support; can proceed independently

## Key constraints

- Telegram adapter behavior must not change (metadata-rich titles stay).
- The `_all_sessions_channel_id` catch-all must remain as fallback, not be removed.
- Forum auto-provisioning must be idempotent (already is).
- Thread topper is sent once at creation and never moves. Output always stays at the bottom.
- Core must not construct titles or make adapter-specific presentation decisions.
