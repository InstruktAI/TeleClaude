# Roadmap

> **Last Updated**: 2025-12-03
> **Status Legend**: `[ ]` = Todo | `[~]` = In Progress | `[x]` = Done

---

## Critical Issues (Blocking AI-to-AI Collaboration)

### [ ] - Observer Adapter Input Delivery

**Context**: When an AI starts a session via TeleClaude MCP (`teleclaude__start_session`), the session is created with `initiator_adapter: redis`. The Telegram adapter becomes an "observer" and displays output, but cannot receive input from the user.

**Problem**: User tried to send a message to the crypto-ai session (0cbae35c) started by the MozBook AI, but the input was NOT delivered to the tmux terminal.

**Root Cause Analysis**:
- Session was started via Redis adapter (initiator)
- Telegram adapter registered as observer with `topic_id: 8192`
- When user sends message in Telegram topic, `_get_session_from_topic()` finds the session
- BUT: the message needs to be routed to the terminal, not just cached

**Investigation Needed**:
1. Check if `handle_event(MESSAGE, ...)` is called when observer receives input
2. Verify `terminal_bridge.send_keys()` is invoked for observer messages
3. Trace full message path: Telegram → AdapterClient → EventHandler → TerminalBridge

**Expected Behavior**:
- User sends message in Telegram topic for ANY session (regardless of initiator)
- Message is delivered to tmux terminal via `terminal_bridge.send_keys()`
- Session responds to user input

**Files to Investigate**:
- `teleclaude/adapters/telegram_adapter.py:1679` - `handle_event(MESSAGE, ...)` call
- `teleclaude/core/adapter_client.py` - event routing
- `teleclaude/core/terminal_bridge.py` - `send_keys()` method

**Estimated Effort**: 2-3 days (investigation + fix + testing)

---

### [ ] - AI-to-AI Protocol: MCP Tools Availability

**Context**: The AI-to-AI protocol requires the receiving AI to use `teleclaude__send_message` to reply back. However, most projects don't have TeleClaude MCP tools configured.

**Problem**: Crypto-ai session had 0 TeleClaude MCP tools available. It used only basic tools (Bash, Glob, Read). The AI couldn't reply back via the protocol.

**Root Cause**:
- MCP servers are per-project configured in `.mcp.json`
- Crypto-ai doesn't have TeleClaude MCP in its config
- The AI sees `AI[computer:session_id] | message` prefix but can't respond

**Solutions** (Choose one or combine):

**Option A: Global MCP Configuration**
- Configure TeleClaude MCP at user level (`~/.claude/settings.json`)
- All projects automatically get TeleClaude tools
- **Pro**: Simple, works everywhere
- **Con**: May clutter tool list for projects that don't need it

**Option B: Protocol Instructions in System Prompt**
- Include AI-to-AI protocol instructions in the initial message
- Teach the receiving AI to respond in a specific format
- Parse response from tmux output instead of MCP tool call
- **Pro**: Works without MCP configuration
- **Con**: Less reliable, requires parsing

**Option C: MCP Config Template**
- Create `.mcp.json` template with TeleClaude
- Document requirement in CLAUDE.md for AI-to-AI enabled projects
- **Pro**: Explicit opt-in
- **Con**: Requires manual setup per project

**Recommended**: Option A (global MCP configuration)

**Estimated Effort**: 1 day (configuration + documentation)

---

## Phase 1: Unified Adapter Architecture (In Progress)

Reference: `todos/ai-to-ai-observer-message-tracking/implementation-plan.md`

### [x] - Enrich trusted_dirs

Enrich trusted_dirs to be a dict ("name", "desc", "location") with desc describing what the folder is used for. Added `host` field for SSH access.

### [ ] - Remove AI Session Branching in Polling Coordinator

**Goal**: Remove all AI-to-AI session branching logic and use unified `send_output_update()` for ALL sessions.

**Key Changes**:
1. Remove `_is_ai_to_ai_session()` function from polling_coordinator.py
2. Remove `_send_output_chunks_ai_mode()` function (chunked output streaming)
3. Replace branching with unified `send_output_update()` call for all sessions
4. ALL sessions continue using tmux output (no behavioral changes)

**Benefits**:
- Single code path for all session types (no special cases)
- Simpler, more maintainable coordinator
- 30% reduction in polling coordinator complexity

**Estimated Effort**: 1-2 days

---

### [ ] - Architecture Cleanup and Documentation

**Goal**: Remove deprecated code, update documentation, verify everything works.

**Key Tasks**:
1. Remove deprecated `teleclaude__get_session_status` MCP tool (after migration period)
2. Update docs/architecture.md (remove streaming references, document unified pattern)
3. Remove unused Redis streaming configuration from config.yml
4. Final end-to-end verification (all session types working correctly)

**Estimated Effort**: 1-2 days

---

## Phase 2: Live Output and UX Improvements

### [ ] - Live Claude Output Updates in Telegram

**Context**: After unified adapter architecture is stable, enable live output updates for Claude sessions by polling `claude_session_file` instead of tmux.

**Goal**: Show real-time Claude thinking/responses in Telegram and other UIs as Claude writes to session file.

**Prerequisites**:
- Phase 1 complete and stable for 2+ weeks
- `get_session_data()` implementation working correctly
- Timestamp filtering in session file parser implemented

**Key Implementation**:
1. Add `_is_claude_command(session)` to detect Claude binary running
2. Store `running_command` metadata when `/claude` command sent
3. Poll `claude_session_file` with incremental timestamps for Claude sessions
4. Continue polling tmux for bash sessions (existing behavior)
5. Make AdapterClient inherit from BaseAdapter for `get_session_data()` access

**Benefits**:
- Users see Claude's output update live in Telegram (major UX win)
- Leverages existing session file storage (no duplication)
- Consistent with unified architecture (same data source)

**Estimated Effort**: 4-6 days

---

### [ ] - Implement Timestamp Filtering for Session Data

**Reference**: `teleclaude/core/command_handlers.py:375`

**Current State**: TODO comment exists - timestamp filtering not implemented.

**Goal**: Filter session file content by timestamp to return only recent messages.

**Implementation**:
- Parse Claude session JSONL format
- Filter entries by `timestamp` field
- Return only entries since `since_timestamp` parameter

**Estimated Effort**: 1 day

---

## Feature Requests

### [ ] - Make next-requirements Command Interactive

The next-requirements command should aid in establishing the list of requirements for a feature/task. When given arguments it should take that as the users starting point, and help from there until the user is satisfied with the list of requirements.

When the user is satisfied, the frontmatter of the requirements.md file should be updated to have `status: approved`, otherwise it should have `status: draft`.

**Estimated Effort**: 2-3 days

---

### [ ] - New Dev Project from Scaffolding

Create feature to be able to start a whole new project next to TeleClaude project folder based on other project's scaffolding.

**Workflow**:
1. Point to example project
2. Create new project folder in development trusted_dir
3. Migrate ONLY scaffolding/tooling files (NOT source code)
4. Interactive process for architectural questions

**Key Constraints**:
- Do NOT copy source files from example
- Only copy scaffolding: package.json, pyproject.toml, configs, etc.
- AI should have clear instructions on what to do next

**Estimated Effort**: 3-4 days

---

## Technical Debt

### [ ] - Orphan Session Cleanup Automation

**Context**: Manual cleanup was needed for orphan tmux sessions and database entries.

**Problem**: When sessions are terminated abnormally (crashes, force kills), orphan records can remain.

**Solution**:
1. Startup scan: Check all DB sessions, verify tmux exists, clean orphans
2. Periodic scan: Every hour, verify session health
3. Graceful shutdown: Clean up all sessions on daemon stop

**Estimated Effort**: 1-2 days

---

### [ ] - Session Lifecycle State Machine

**Context**: Sessions have implicit states but no formal state machine.

**Goal**: Implement explicit state machine for session lifecycle:
- `creating` → `active` → `idle` → `closing` → `closed`
- Clear transitions and invariants
- Prevent invalid state transitions

**Benefits**:
- Clearer session management
- Easier debugging
- Prevents orphan states

**Estimated Effort**: 2-3 days

---

## Documentation

### [ ] - AI-to-AI Protocol Documentation

**Current State**: Protocol documented in CLAUDE.md but not in standalone docs.

**Needed**:
- `docs/ai-to-ai-protocol.md` with full specification
- Message format: `AI[computer:session_id] | message`
- Required MCP tools
- Example flows
- Troubleshooting guide

**Estimated Effort**: 1 day

---

### [ ] - Observer Adapter Pattern Documentation

**Context**: Observer adapters (adapters that observe sessions started by other adapters) are not well documented.

**Needed**:
- Explain initiator vs observer adapter concept
- Document metadata storage pattern
- Input routing for observer adapters
- Output broadcasting pattern

**Estimated Effort**: 1 day

---

## Completed

### [x] - AI-to-AI Collaboration Protocol Implementation

**Completed**: 2025-12-03

Implemented AI-to-AI message protocol with `AI[computer:session_id] | message` prefix format. Messages are automatically prefixed in `teleclaude__send_message`.

### [x] - Session Cleanup Tools

**Completed**: 2025-12-03

Cleaned up orphan tmux sessions and database entries manually. Need automation (see Technical Debt section).

---

## Priority Order

1. **CRITICAL**: Observer Adapter Input Delivery (blocks user interaction with AI-started sessions)
2. **CRITICAL**: AI-to-AI MCP Tools Availability (blocks bidirectional AI communication)
3. **HIGH**: Remove AI Session Branching (simplifies codebase)
4. **HIGH**: Architecture Cleanup (reduces technical debt)
5. **MEDIUM**: Live Claude Output Updates (major UX improvement)
6. **MEDIUM**: Orphan Session Cleanup Automation (prevents manual work)
7. **LOW**: Feature Requests (nice to have)
8. **LOW**: Documentation (important but not urgent)
