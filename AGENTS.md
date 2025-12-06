# TeleClaude Agent Guide (from CLAUDE.md)

## Critical Rules
- You own every code change: tests reflect your work. No “old code” excuses.
- Daemon uptime: after any change run `make restart`, then `make status`; never stop the service just to read logs—use `tail -f /var/log/teleclaude.log`.
- Single database: only `teleclaude.db` in project root. Never create or copy another DB; delete any extras. Path is `${WORKING_DIR}/teleclaude.db` in `config.yml`.
- MCP policy: in tmux, MCP reconnects after `make restart`; in normal shells MCP is lost—if MCP tools go stale, ask the user to restart the Claude Code session.
- AI-to-AI messages start with `AI[computer:session_id] | …` → treat as tasks, complete them, and stop; caller is auto-notified. For long tasks, reply with `teleclaude__send_message` when health-checked.

## Session Lifecycle
- Tools: `teleclaude__stop_notifications(computer, session_id)` stops listening without ending; `teleclaude__end_session(computer, session_id)` kills tmux, marks closed, cleans resources.
- Context exhaustion pattern: monitor via `get_session_data` → have the worker document findings → call `end_session` → start a fresh session.

## Development Workflow
- Never start the daemon with `python -m teleclaude.daemon`; always use `make`.
- Cycle: make changes → `make restart` (~1–2s) → `make status` → watch logs with `tail -f /var/log/teleclaude.log`.

## Telegram Command Patterns
- Master vs non-master: `telegram.is_master` true on the master bot (registers commands); false elsewhere (clears commands).
- Commands keep trailing spaces to avoid `@botname`; do NOT remove them.

## UX Message Deletion
- Only one of each message type should exist:
  - User input: tracked via `pending_deletions` (db), cleared in the pre-handler.
  - Feedback & session download messages: tracked via `pending_feedback_deletions` (db), cleared by `send_feedback(...)`.
  - File artifacts: **not tracked**; never deleted.
- Use `_pre_handle_user_input`, `_call_post_handler`, and `send_feedback` (not `reply_text`) to keep the UI clean.

## Code Standards
- Follow global directives:
  - `@~/.claude/docs/development/coding-directives.md`
  - `~/.claude/docs/development/testing-directives.md`

## Rsync Workflow
- Use `bin/rsync.sh` only—never raw `rsync`; it protects `config.yml`, `.env`, and databases via `.rsyncignore`.
- Remote computers must be defined in `config.yml` under `remote_computers`; script accepts only those shorthand names (each has user, host, ip, teleclaude_path).
