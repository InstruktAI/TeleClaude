---
id: teleclaude/concept/glossary
type: concept
scope: project
description: Shared terminology for TeleClaude sessions, adapters, transports, and identifiers.
requires: []
---

Purpose
- Provide consistent definitions for core TeleClaude terms used across docs and code.

Definitions
- Session: a tmux-backed execution context tracked in SQLite and surfaced in Telegram/MCP/API.
- session_id: TeleClaude-generated UUID used as the primary session identifier across adapters.
- native_session_id: agent-native identifier captured from hook payloads (Claude/Gemini/Codex).
- origin adapter: the adapter that created the session (for example, telegram).
- UI adapter: an adapter with human-facing UX responsibilities (Telegram).
- transport adapter: an adapter that supports cross-computer execution (Redis Streams).
- computer name: the configured identity for a daemon instance (config.computer.name).
- project_path: the base project directory assigned to a session.
- subdir: optional relative path for a worktree or subfolder within project_path.
- session summary: lightweight session DTO used for list views and cache snapshots.
- session detail: live output and event stream for an active session.
