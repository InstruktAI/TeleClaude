# Requirements: help-desk-control-room

## Goal

Establish a Discord-based admin control room where all AI sessions — regardless of origin platform or project — are mirrored as forum threads. Admins observe session activity in real-time and can intervene by sending messages directly in threads.

This addresses a key limitation of the Telegram supergroup model: all sessions share one flat topic list with no categorization. Discord's richer channel hierarchy (categories, forums, tags) enables organized admin observation with clear separation between help desk and internal sessions.

## Problem

- Telegram mirrors all sessions as forum topics in one supergroup — no categorization by type
- Discord only handles help desk customer sessions (via `help_desk_channel_id`) and escalations (via `escalation_channel_id`)
- Admins have no Discord-based visibility into internal/admin sessions
- There is no unified cross-platform observation surface — sessions are only visible on their origin adapter

## Intended Outcome

A single Discord forum channel serves as the admin control room:

- Every session gets a thread, regardless of origin platform (Telegram, Discord, API, MCP)
- Session output is mirrored to the thread in real-time via the existing adapter observer broadcast (`_broadcast_to_observers`)
- Admins can type in any thread to send input to the session
- Discord forum tags categorize threads by session type (help-desk, internal, maintenance)
- The control room is separate from and does not interfere with the customer-facing help desk forum

## Requirements

### R1: Control room Discord forum channel

**Config:** `teleclaude/config/__init__.py`

- Add `control_room_channel_id: int | None` to `DiscordConfig`
- When not configured, all control room behavior is silently skipped (graceful degradation)
- The control room forum is a standard Discord forum channel; the admin creates it manually and configures the ID

### R2: Per-session thread creation

**Files:** `teleclaude/adapters/discord_adapter.py`, adapter metadata models

- When a session starts and `control_room_channel_id` is configured, create a thread in the control room forum
- Thread title matches the session display title (same format as Telegram supergroup topics)
- Store the control room thread ID in adapter metadata (`control_room_thread_id`)
- Help desk customer sessions get BOTH a help desk thread (customer-facing) and a control room thread (admin observation) — these are independent

### R3: Output mirroring to control room threads

- Session output appears in the control room thread in near real-time
- For sessions originating from Discord: output goes to origin thread + control room thread
- For sessions originating from other platforms: the existing `_broadcast_to_observers` fan-out delivers output to the Discord adapter as an observer, which routes to the control room thread
- Rate limiting: respect Discord API limits; if output updates are throttled, the last state wins (same pattern as existing output)

### R4: Admin intervention via control room threads

**Files:** `teleclaude/adapters/discord_adapter.py`, `teleclaude/core/db.py`

- Admin messages in control room threads are routed to the session's tmux pane via `ProcessMessageCommand`
- Reverse lookup: resolve session from `control_room_thread_id` in adapter metadata
- Relay conflict: if the session has an active relay (`relay_status == "active"`), warn the admin in the thread that the session is in relay mode and intervention goes through the relay thread instead
- Admin identity: messages in control room threads are attributed to the admin who sent them

### R5: Thread lifecycle management

- Thread title updates when session title changes (via `update_channel_title`)
- Thread is closed when session ends (via `close_channel` — 72h sweep or manual stop)
- Thread can be archived/deleted when session is deleted (via `delete_channel`)

### R6: Forum tag categorization

- On adapter startup, ensure forum tags exist in the control room channel
- Tags: `help-desk`, `internal`, `maintenance` (minimum set)
- Tag assignment: determined by session context — help desk project sessions get `help-desk`; admin/member sessions get `internal`; job/maintenance sessions get `maintenance`

## Out of Scope

- **Replacing Telegram supergroup** — Telegram observation continues as-is
- **Customer interaction via control room** — control room is admin-only; customers use the help desk forum
- **Historical session import** — only new sessions get control room threads
- **Per-computer separation** — all sessions share one control room forum (future enhancement)
- **Custom admin commands in threads** — admin only sends text input; no slash commands in control room threads

## Constraints

- Must not break existing Telegram adapter behavior
- Must not break existing Discord help desk or escalation flows
- Must handle Discord API rate limits on thread creation and message posting
- Admin intervention in control room must not conflict with direct session interaction from other adapters (input is additive, not exclusive)

## Risks

- Discord rate limits on thread creation could slow down session starts during high-activity periods
- Sessions with high output frequency may hit Discord message rate limits (mitigated by existing throttling in `send_output_update`)
- Multiple admins typing in the same control room thread could create confusing multi-input scenarios (same risk as Telegram supergroup — accepted)
