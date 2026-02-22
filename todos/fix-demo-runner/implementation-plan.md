# Implementation Plan: fix-demo-runner

## Overview

Two independent tracks: (1) add missing `demo` fields to snapshot files, and (2) extend the MCP wrapper's existing auto-injection to cover `session_id`. The wrapper already injects `cwd` and `caller_session_id` — `session_id` is the same pattern. No handler changes needed.

## Phase 1: Add demo fields to snapshots

### Task 1.1: Add demo field to themed-primary-color

**File(s):** `demos/themed-primary-color/snapshot.json`

- [ ] Add `"demo"` field with a shell command that demonstrates the themed primary color feature
- [ ] Command runs via `subprocess.run(cmd, shell=True, cwd=demo_dir)`

### Task 1.2: Add demo field to tui-markdown-editor

**File(s):** `demos/tui-markdown-editor/snapshot.json`

- [ ] Add `"demo"` field with a shell command that demonstrates the markdown editor feature
- [ ] Command runs via `subprocess.run(cmd, shell=True, cwd=demo_dir)`

## Phase 2: Auto-inject session_id in MCP wrapper

### Task 2.1: Extend wrapper injection logic

**File(s):** `teleclaude/entrypoints/mcp_wrapper.py`

- [ ] In `_inject_context` (or equivalent injection point): when `session_id` is not already in arguments, inject it from the same session marker used for `caller_session_id`
- [ ] Same precedence rule as other injected params: explicit AI-provided value wins

### Task 2.2: Make session_id optional in tool schemas

**File(s):** `teleclaude/mcp/tool_definitions.py`

- [ ] Remove `"session_id"` from `required` in `render_widget` schema
- [ ] Remove `"session_id"` from `required` in `send_result` schema
- [ ] Remove `"session_id"` from `required` in `send_file` schema

### Task 2.3: Clean up next-demo command artifact

**File(s):** `agents/commands/next-demo.md`

- [ ] Remove the note about handling missing `demo` field — that's CLI-level
- [ ] Confirm no session_id ceremony exists or is needed

---

## Phase 3: Validation

### Task 3.1: Demo execution

- [ ] `telec todo demo themed-primary-color` exits 0
- [ ] `telec todo demo tui-markdown-editor` exits 0

### Task 3.2: Wrapper injection

- [ ] `render_widget` works without explicit `session_id`
- [ ] `render_widget` works with explicit `session_id` (backward compat)

### Task 3.3: Quality checks

- [ ] `make lint`
- [ ] `make test`

---

## Phase 4: Review Readiness

- [ ] Requirements reflected in code changes
- [ ] All implementation tasks marked `[x]`
