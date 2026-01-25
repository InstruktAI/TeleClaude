---
id: teleclaude/concept/glossary
type: concept
scope: project
description:
  Shared terminology for TeleClaude sessions, adapters, transports, and
  identifiers.
---

# Glossary — Concept

## Purpose

- Provide consistent definitions for core TeleClaude terms used across docs and code.

- Inputs: terms used in docs, code, and APIs.
- Outputs: canonical definitions for shared understanding.

- Session: a tmux-backed execution context tracked in SQLite and surfaced in Telegram/MCP/API.
- session_id: TeleClaude-generated UUID used as the primary session identifier across adapters.
- native_session_id: agent-native identifier captured from hook payloads (Claude/Gemini/Codex).
- origin adapter: the adapter that created the session (for example, telegram).
- UI adapter: an adapter with human-facing UX responsibilities (Telegram).
- transport: infrastructure for cross-computer execution and discovery (Redis Streams).
- computer name: the configured identity for a daemon instance (config.computer.name).
- project_path: the base project directory assigned to a session.
- subdir: optional relative path for a worktree or subfolder within project_path.
- session summary: lightweight session DTO used for list views and cache snapshots.
- session detail: live output and event stream for an active session.

- Definitions in this glossary are the canonical meanings for documentation and code comments.

- Inconsistent terminology causes mismatched expectations across adapters and APIs.

## Inputs/Outputs

- **Inputs**: terms used in docs, code, and APIs.
- **Outputs**: canonical definitions for shared understanding.

## Invariants

- Glossary definitions override ad hoc terminology in other docs.
- Terms should remain stable; changes require cross-doc updates.

## Primary flows

- Docs and APIs reference glossary terms to avoid ambiguous naming.

## Failure modes

- Divergent terminology causes adapter incompatibilities and API confusion.
