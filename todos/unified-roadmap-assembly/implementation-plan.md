# Implementation Plan: unified-roadmap-assembly

## Overview

Extract roadmap assembly logic into a core function and unify usage across CLI and API.

## Phase 1: Core Extraction

### Task 1.1: Create `teleclaude/core/roadmap.py`

**File(s):** `teleclaude/core/roadmap.py`

- [x] Create module with `assemble_roadmap` function.
- [x] Port logic from `command_handlers.list_todos`, including:
  - Roadmap loading
  - Icebox parsing
  - State.json reading (DOR, status, etc.)
  - Breakdown/container injection
  - Grouping and dependency handling
- [x] Add `include_icebox` and `icebox_only` parameters.

### Task 1.2: Refactor `command_handlers.py`

**File(s):** `teleclaude/core/command_handlers.py`

- [x] Update imports.
- [x] Replace `list_todos` body with call to `assemble_roadmap`.

## Phase 2: CLI Integration

### Task 2.1: Update `telec.py` schema

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `--include-icebox` (-i) and `--icebox-only` (-o) flags to `roadmap` command definition.
- [x] Add `--json` flag to `roadmap` command definition.

### Task 2.2: Update `telec.py` handler

**File(s):** `teleclaude/cli/telec.py`

- [x] Refactor `_handle_roadmap_show` to use `assemble_roadmap`.
- [x] Implement CLI rendering using `TodoInfo` objects (replacing raw `RoadmapEntry` usage).
- [x] Implement JSON output format.
- [x] Handle new icebox flags.

## Phase 3: Validation

### Task 3.1: Verification

- [x] Verify `telec roadmap` output matches expected rich format.
- [x] Verify `telec roadmap --json` output.
- [x] Verify `telec roadmap --icebox-only`.

### Task 3.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain
