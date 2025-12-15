# Universal File-Watcher Hook System

## Objective
Implement a robust, agent-agnostic event system that monitors session log files directly to detect agent state changes, replacing the current reliance on internal agent hooks (e.g., `claude-code` hooks).

## Core Requirements

### 1. Universal Session Monitoring
- **Watch Multiple Paths:** Monitor session directories for supported agents (e.g., `~/.claude/sessions`, `~/.gemini/sessions`).
- **Configurable Paths:** Allow configuration of session log paths per agent in `config.yml`.
- **File Types:** Support `.jsonl` (Claude/Gemini?) and potentially other formats if needed.

### 2. Session Discovery & Adoption
- **Detect New Sessions:** Real-time detection of newly created session files.
- **Auto-Adoption:** Automatically link a newly discovered native session file to the currently active TeleClaude session if one exists and is waiting for adoption.
- **Persistence:** Store the `native_session_id` and `native_log_file` path in `SessionUXState` upon discovery.

### 3. Event Generation (File Watching)
- **Tail-Based Parsing:** Continuously monitor adopted session files for new content.
- **Event Mapping:** Parse log entries into TeleClaude events:
  - **Session Start:** Detected upon file creation/first write.
  - **Stop/Turn Complete:** Detect when the agent finishes its turn (e.g., specific log entry type or "summary" block).
  - **Notification/Input Needed:** Detect when the agent is asking for user input.
  - **Title/Summary Updates:** Extract generated titles and summaries from log entries.

### 4. Architecture Updates
- **New Component:** `SessionWatcher` service that runs alongside `OutputPoller`.
- **Decoupling:** Deprecate/remove `teleclaude__handle_claude_event` MCP tool (incoming webhooks).
- **Unified Event Flow:** All agent events should originate from `SessionWatcher` -> `AdapterClient.handle_event`.

## Technical constraints
- **Performance:** File watching must be efficient (inotify/kqueue where available, or optimized polling).
- **Resilience:** Must handle log rotation, truncation, or agent crashes gracefully.
- **Concurrency:** Handle multiple active sessions/agents simultaneously.

## Benefits
- **Zero-Config for Agents:** No need to install custom hooks/scripts inside the agent's environment.
- **Robustness:** "Exit code trick" and other hacks become secondary or unnecessary if we reliably watch logs.
- **Consistency:** Same event lifecycle for all agents (Claude, Gemini, Codex).
