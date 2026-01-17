# Invariants

## System Availability
- Daemon remains up; downtime only during controlled restart.
- Use `make restart` for restarts.

## Identity & Addressing
- `session_id` is generated once and returned immediately.
- tmux name format is stable: `tc_{session_id[:8]}`.
- `native_session_id` is independent from TeleClaude `session_id`.

## Data Integrity
- Single DB file for daemon: `teleclaude.db` in project root.
- No duplicate DB files except worktrees.

## Command & Event Contract
- Command response always includes `command_id`.
- Response includes expected events with per‑event timeouts.
- Events are emitted once per state transition.

## Operational Semantics
- No defaults or fallbacks for required fields.
- Contract violations fail fast.

## Scope & Security
- MCP default scope: caller‑owned sessions only.
- Global scope requires explicit override.

## Adapter Boundaries
- Adapters normalize input; core never interprets adapter‑specific payloads.
- Transport metadata never drives domain intent.

## Polling & Output
- Output polling tied to tmux session lifecycle.
- Pollers never run for closed sessions.

## Cache
- Cache is read‑only snapshots; not source of truth.
- Cache updates are event‑driven.

## UX (Telegram)
- Feedback cleanup: delete prior feedback before sending new feedback.
- User input cleanup: delete prior inputs on next input.

## Multi‑Computer
- Only master bot registers Telegram commands.
- Redis optional for multi‑computer Telegram.

## Hooks
- Hook receiver is the authority for `native_session_id`.
- `TELECLAUDE_SESSION_ID` is injected into agent sessions.
