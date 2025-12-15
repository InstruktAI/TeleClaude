# Implementation Plan - Universal File-Watcher Hooks

## Group 1: Configuration & Foundation

- [x] **Define Agent Log Paths:** Update `config.py` and `config.yml.sample` to include `session_dir` and `log_pattern` for each agent.
- [x] **Create SessionWatcher Class:** Scaffold `teleclaude/core/session_watcher.py` with polling/watching logic.
- [x] **Define LogParser Interface:** Create `teleclaude/core/parsers.py` with abstract base class for log parsing.

## Group 2: Log Parsers

- [x] **Implement CodexParser:** Implement parser for Codex session logs (JSONL).
- [x] **Cleanup:** Remove unused `ClaudeParser` and `GeminiParser` (enforce "only watch what we can't hook").
- [x] **Test Parsers:** Unit tests for CodexParser.

## Group 3: Session Watcher Implementation

- [x] **Implement Discovery:** Logic to scan configured directories for new files matching patterns.
- [x] **Implement Adoption:** Logic to match new files to active TeleClaude sessions (by timestamp/heuristic) and update `ux_state`.
- [x] **Implement Tailing:** Logic to read new lines from adopted files.
- [x] **Event Dispatch:** Emit generic `AGENT_EVENT` when parser detects events.

## Group 4: Gemini Native Hooks (New)

- [x] **Create Hook Script:** Created `receiver_gemini.py` and consolidated bridge scripts in `teleclaude/hooks/`.
- [x] **Configure Gemini:** Created `scripts/install_hooks.py` and integrated into `bin/install.sh`.
- [x] **Update MCP Server:** Verified `teleclaude__handle_claude_event` handles generic events.

## Group 5: Integration & Cleanup

- [x] **Integrate with Daemon:** Start `SessionWatcher` in `TeleClaudeDaemon.start()` and stop in `stop()`.
- [x] **Deprecate Webhook?** (No, keep for Claude/Gemini). Ensure adapter handles events from watcher seamlessly.
- [x] **Update Tests:** Integration tests for file watching.

## Group 6: Review & Polish

- [x] **Review:** Verify all requirements met.
- [x] **Refine:** Optimize polling intervals and resource usage.