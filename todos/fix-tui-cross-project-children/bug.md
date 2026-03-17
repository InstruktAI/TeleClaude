# Bug: TUI session tree nests child sessions under parent regardless of project — cross-project children should be top-level

## Symptom

TUI session tree nests child sessions under parent regardless of project — cross-project children should be top-level

## Detail

## Problem

The TUI session tree builds parent-child hierarchy using `initiator_session_id` alone (`teleclaude/cli/tui/tree.py:124, 219`). It does not consider which project a child session belongs to. When an orchestrator in project A dispatches a worker in project B, that worker renders as a nested child under project A's tree node — incorrectly.

Real example: `telec bugs report` in TeleClaude dispatches a bug-fix orchestrator. The orchestrator is created with `initiator_session_id` pointing to the caller's session. In the TUI tree, it nests under the caller even though it may be an independent orchestrator running in its own project context.

## Why initiator_session_id must stay

Removing the parent link was considered and rejected. `initiator_session_id` provides ownership tracking (who spawned what) and auditability (trace chains of delegation). Multiple subsystems depend on it: feedback routing (`adapter_client/_output.py:108`), child session listing (`next_machine/work.py:851`), session list filtering (`api/sessions_routes.py:404`), and display title enrichment (`core/session_utils.py:351`).

## Correct behavior

The tree builder should compare the child's project_path against the parent's project_path. If they differ, the child should render as a top-level node in its own project group rather than nested under the parent. The `initiator_session_id` relationship is preserved in the database — this is purely a display/grouping concern.

## Files

- `teleclaude/cli/tui/tree.py` — tree builder uses `initiator_session_id` at line 124 and builds `sessions_by_initiator` map at line 219 without project filtering
- `teleclaude/api/sessions_routes.py:148` — where initiator is injected (context only, no change needed)
- `teleclaude/core/command_handlers/_session.py:204` — where initiator is persisted (context only)

## Triggered by

`telec bugs report` dispatches orchestrators via `teleclaude/cli/telec/handlers/bugs.py:163` using `create_session()` with `skip_listener_registration=True`. The session gets `initiator_session_id` automatically from the API layer (`sessions_routes.py:148`). The original fix (`11fc8dbc2`) only suppressed notifications, not the parent-child linkage.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

Traced the tree building logic in `teleclaude/cli/tui/tree.py`. At line 124 (pre-fix), sessions are classified into `sessions_by_initiator` or `root_sessions` based solely on whether `initiator_session_id` exists and points to a session in the current set. No project affinity check is performed.

When `_build_session_node` recursively adds children (line 235), it pulls from `sessions_by_initiator` without considering whether the child session belongs to the same project. A cross-project child (e.g., project B worker initiated by project A orchestrator) gets nested under the parent in project A's tree.

## Root Cause

`build_tree` classifies sessions into parent-child relationships using `initiator_session_id` alone (line 124-126). It does not compare `project_path` between the child and initiator. Cross-project children are incorrectly nested under their initiator's project tree node instead of appearing as top-level sessions in their own project group.

## Fix Applied

Added two helper functions to `tree.py`:

- `_base_project_path(path)`: Strips worktree suffix (`/trees/...`) to resolve the base project path.
- `_same_project(path_a, path_b)`: Compares two session project paths by their resolved base projects.

Modified the session classification loop to check `_same_project(session.project_path, initiator.project_path)` before nesting. Cross-project children now fall through to `root_sessions` and render as top-level nodes in their own project group.

The `initiator_session_id` relationship is preserved in the data — this change only affects display grouping.
