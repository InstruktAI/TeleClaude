# Roadmap

## [ ] - Remove AI Session Branching in Polling Coordinator

**Context**: Continue unified adapter architecture refactoring - remove AI session special cases from polling coordinator.

**Reference**: `todos/ai-to-ai-observer-message-tracking/implementation-plan.md`

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

**Estimated Effort**: 1-2 days (code changes + testing)

---

## [ ] - Architecture Cleanup and Documentation

**Context**: Final cleanup after unified adapter architecture refactoring.

**Reference**: `todos/ai-to-ai-observer-message-tracking/implementation-plan.md`

**Goal**: Remove deprecated code, update documentation, verify everything works.

**Key Tasks**:
1. Remove deprecated `teleclaude__get_session_status` MCP tool (after migration period)
2. Update docs/architecture.md (remove streaming references, document unified pattern)
3. Remove unused Redis streaming configuration from config.yml
4. Final end-to-end verification (all session types working correctly)

**Benefits**:
- Clean, documented architecture
- No legacy code confusion
- Ready for future UX improvements

**Estimated Effort**: 1-2 days (cleanup + docs + verification)

---

## [ ] - Live Claude Output Updates in Telegram

**Context**: After unified adapter architecture is stable, enable live output updates for Claude sessions by polling `claude_session_file` instead of tmux.

**Reference**: `todos/ai-to-ai-observer-message-tracking/implementation-plan.md`

**Goal**: Show real-time Claude thinking/responses in Telegram and other UIs as Claude writes to session file.

**Prerequisites**:
- Phase 1-4 of unified adapter architecture deployed and stable for 2+ weeks
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

**Estimated Effort**: 4-6 days (implementation + testing + docs)

---

## [ ] - make next-requirements command interactive

The next-requirements command should aid in establishing the list of requirements for a feature/task. When given arguments it should take that as the users starting point, and help from there until the user is satisfied with the list of requirements.
When the user is satsified, the frontmatter of the requirements.md file should be updated to have `status: approved`, otherwise it should have `status: draft`.

## [x] - Enrich trusted_dirs

Enrich trusted_dirs to be a dict ("name", "desc", "location") with desc describing what the folder is used for (may be empty). (Update the local config.yml to have a folder named "development", with desc "dev projects" to make the dev folder point to "/Users/Morriz/Documents/Workspace/morriz").
Make teleclaude/config.py's ComputerConfig return the list with the `default_working_dir` merged with desc "TeleClaude folder".

Also add a `host` field that can be empty or a hostname/ip. If set, teleclaude can ssh into that host and run commands there (assuming the trusted_dir is mounted there too). Add proper descriptions to all fields so AI understands them.

## [ ] - New dev project from skaffolding

Create feature to be able to start a whole new project next to TeleClaude project folder based on other project's skaffolding.

We have many projects in different folders on the computer and we would like to point to one of those and create a new project folder based on that example project. It should then create a new project folder (in the trusted_dir desginated as development folder) and only migrate the necessary, tooling and scaffolding files to that new `{developmentFolder}/{newProjectName}` location. This process should be interactive with the user so that any questions are answered before you do things that affects the architecture. Do NOT copy over source files from the example project, only the scaffolding and tooling files. It should be clear to the AI what to do next.
