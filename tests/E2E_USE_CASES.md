# E2E + TUI Use Cases (Exhaustive Starting Set)

Purpose: list user-facing interactions we want covered by a mix of view snapshots, integration tests, and end-to-end flows.

## A. TUI (telec) — Sessions View

1. Startup + empty state

- Launch TUI with no sessions/projects/computers.
- Verify empty view messaging.

2. Sessions tree rendering

- One computer -> one project -> one session (expanded).
- Multiple computers/projects (counts, nesting).
- Orphan sessions (project_path missing).
- AI-to-AI nesting (parent/child sessions).

3. Navigation

- Up/down selection (single line + multi-line items).
- Page scroll behavior (scroll_offset).
- Selection persistence after refresh.

4. Expand/collapse

- Expand all (+/=) shows all sessions.
- Collapse all (-) hides session details.

5. Session actions

- Start new session on project (n).
- Open/close all sessions for project (a/A).
- Kill session (k) with confirm modal.

6. Sticky + preview

- Single click selects + preview.
- Double click toggles sticky (parent-only vs parent+child).
- Sticky limit (max 5) warning.

7. Focus + pane integration

- Focus session pane switch.
- Preview vs sticky pane behavior.

## B. TUI (telec) — Preparation View

1. Startup + empty state

- No projects/todos -> empty view messaging.

2. Tree rendering

- Computer -> project -> todo nodes.
- Todo status markers (pending/ready/in_progress).
- Build/review status line.

3. Expand/collapse

- Expand all (+/=) shows todo file nodes.
- Collapse all (-) hides file nodes.

4. Todo actions

- Start work (s) for ready todos.
- Prepare todo (p) for any status.

5. File actions

- View file (v), edit file (e), close preview (c).
- Double click to toggle sticky preview.

6. Focus + navigation

- Focus computer/project.
- Back stack navigation.

## C. TUI Shell + App Controller

1. View switching

- Sessions <-> Preparation views.
- Action bar updates for selection.

2. WebSocket event routing

- sessions_initial, projects_initial, refresh updates.
- WS heal refresh when disconnected.

3. Theme/layout

- Footer separator + tab bar rendering.
- Pane layout derivation when sessions change.

## D. CLI (non-TUI)

1. telec list (stdout)
2. telec status / health
3. telec send message
4. telec start session
5. telec end session
6. telec docs index (phase 1 output)
7. telec docs get (phase 2 content)
8. telec sync --validate-only (no deploy)
9. telec init (project bootstrap)
10. shell completion (TELEC_COMPLETE)
11. error handling (invalid session, offline computer)

## E. Telegram / Human Interaction

1. Command -> tmux -> output -> telegram (success path)
2. Command failure -> error output -> telegram
3. Long-running command -> output polling stays active (idle status line updates)
4. File upload -> path injected into terminal
5. Agent transcript download -> download button -> temp file cleanup
6. Voice -> transcription -> execute

## F. MCP / AI-to-AI

1. list_computers
2. list_sessions
3. start_session
4. send_message
5. send_file
6. send_result
7. interest window (stream then detach)
8. poll/get_session_data after detach
9. timeout + error propagation

## G. Resilience / Recovery

1. daemon restart -> sessions survive
2. polling restarts after process exit
3. redis adapter snapshot warmup
4. outbox + delivery de-dup
5. cache digest stability

---

Test strategy mapping:

- View snapshots: A + B (fast, stable visual diffs).
- Integration tests: D + E + F + G (full workflows, adapters, tmux).
- Minimal mocks, prefer real tmux/redis where feasible.
