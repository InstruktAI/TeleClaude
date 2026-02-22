# Requirements: discord-session-routing

## Goal

Fix Discord session routing so that sessions land in per-project forums with adapter-appropriate titles, role-based message acceptance replaces channel-based gating, and thread headers carry session metadata instead of placeholder text.

## In scope

1. **Role-based message acceptance** -- Replace `_is_help_desk_message()` channel-ID gating with role-aware logic. Admins/members can send from any managed channel. Customers remain scoped to help desk threads.
2. **Adapter-owned title construction** -- Move title building out of `adapter_client._route_to_ui()` into each adapter's `ensure_channel()`. Core passes the `Session` object; each adapter builds its own title.
3. **Per-project Discord forums** -- Enable `discord_project_forum_mirroring` by default (or remove the flag). Route admin/member sessions to the forum matching their `project_path`. Fall back to `_all_sessions_channel_id` for orphan sessions.
4. **Enriched thread header (topper)** -- Replace the placeholder first message in Discord forum threads with session metadata (project, agent, speed, session IDs). The topper is sent once at creation and never moves.

## Out of scope

- Telegram adapter changes (metadata-rich titles and moving footer stay as-is).
- Rolling session title re-summarization (separate todo: `rolling-session-titles`).
- Discord media/file attachment handling (separate todo: `discord-media-handling`).
- Help desk customer-facing UX changes beyond what's needed for role gating.
- Changes to the TUI or web adapter.

## Success Criteria

- [ ] SC-1: Admin/member messages from any managed Discord forum/thread are accepted and routed to the correct session.
- [ ] SC-2: Customer messages are only accepted from help desk threads (existing behavior preserved).
- [ ] SC-3: Each adapter constructs its own title -- `adapter_client` no longer calls `get_display_title_for_session()` before `ensure_ui_channels()`. The `ensure_channel` signature changes from `(session, title)` to `(session)`.
- [ ] SC-4: Discord session threads for admin/member sessions are created in the project-specific forum when a matching trusted dir exists.
- [ ] SC-5: Sessions without a matching trusted dir fall back to the `_all_sessions_channel_id` catch-all forum.
- [ ] SC-6: Discord thread first message contains structured metadata: project name, agent type/speed, TeleClaude session ID, native AI session ID.
- [ ] SC-7: Telegram adapter behavior is unchanged -- still uses the metadata-rich title format and moving footer.
- [ ] SC-8: `make test` passes; `make lint` passes.

## Constraints

- The `_all_sessions_channel_id` catch-all must remain as fallback, not be removed.
- Forum auto-provisioning (`_ensure_project_forums()`) must remain idempotent.
- Thread topper is sent once at creation and never moves. Output always appends at the bottom.
- Core (`adapter_client`) must not construct titles or make adapter-specific presentation decisions.
- The `ensure_channel` contract change (dropping the `title` parameter) affects all adapters -- the base class `UiAdapter`, `TelegramAdapter`, and `DiscordAdapter` signatures must all be updated.

## Risks

- The `ensure_channel` signature change is a cross-cutting refactor across all adapter implementations. Missed call sites will cause runtime errors.
- Enabling per-project forums on startup creates Discord channels eagerly. If trusted dirs change frequently, orphan forums may accumulate (acceptable -- cleanup is manual).
- `_is_help_desk_message()` removal changes the security boundary. The replacement must correctly identify managed forums including project forums to prevent messages from arbitrary channels being processed.
