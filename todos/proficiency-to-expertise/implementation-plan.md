# Implementation Plan: proficiency-to-expertise

## Overview

Replace flat `proficiency` field on PersonEntry with structured `expertise` model.
This parent tracks three sub-todo builds: schema, injection, and CLI (TUI deferred).
Implementation proceeds foundation-first: schema → injection → CLI.

Backward compat: `proficiency` field stays as optional deprecated field throughout transition.

## Phase 1: Schema Foundation

### Task 1.1: Pydantic expertise model (`config/schema.py`)

**File(s):** `teleclaude/config/schema.py`

- [x] Add `ProficiencyLevel` type alias
- [x] Replace `proficiency: Literal[...]` on `PersonEntry` with `expertise` + optional `proficiency` for backward compat

### Task 1.2: API DTO mirror (`api_models.py`)

**File(s):** `teleclaude/api_models.py`

- [x] Update `PersonDTO` to add `expertise` field, keep `proficiency` as optional/deprecated

---

## Phase 2: Injection

### Task 2.1: Hook receiver expertise rendering (`hooks/receiver.py`)

**File(s):** `teleclaude/hooks/receiver.py`

- [x] Replace single-line proficiency injection with full expertise block
- [x] Fallback to `proficiency` if `expertise` is absent (backward compat)

---

## Phase 3: CLI

### Task 3.1: PersonInfo dataclass and list serialization (`config_cli.py`)

**File(s):** `teleclaude/cli/config_cli.py`

- [x] Add `expertise` field to `PersonInfo` dataclass, keep `proficiency`
- [x] `_people_list()`: serialize `expertise` in JSON output

### Task 3.2: CLI add/edit expertise support (`config_cli.py`)

**File(s):** `teleclaude/cli/config_cli.py`

- [x] `_people_add()`: support `--expertise` JSON blob flag (keep `--proficiency` for backward compat)
- [x] `_people_edit()`: support `--expertise` JSON blob flag

---

## Phase 4: Validation

### Task 4.1: Schema tests

**File(s):** `tests/unit/test_config_schema.py`

- [x] Add expertise model validation tests
- [x] Keep existing proficiency backward-compat tests

### Task 4.2: Injection tests

**File(s):** `tests/unit/test_hooks_receiver_memory.py`

- [x] Update tests to cover expertise block rendering
- [x] Keep proficiency-only tests (backward compat path still works)

### Task 4.3: CLI tests

**File(s):** `tests/unit/test_config_cli.py`

- [x] Add expertise add/edit/list CLI tests
- [x] Keep existing proficiency tests (backward compat)

### Task 4.4: Run tests and lint

- [x] `make test`
- [x] `make lint`

---

## Phase 5: Review Readiness

### Task 5.1: Demo

- [x] Add executable bash blocks to `todos/proficiency-to-expertise/demo.md`
- [x] Validate: `telec todo demo validate proficiency-to-expertise`
- [x] Promote: copy to `demos/proficiency-to-expertise/demo.md`

### Task 5.2: Final checklist

- [x] All tasks `[x]`
- [x] Working tree clean

---

## Deferrals

TUI sub-todo (`proficiency-to-expertise-tui`) deferred. The config wizard expertise editing
requires a new multi-level UI pattern (nested enum cycling + freeform entry for custom sub-areas).
This is scoped and tracked in `todos/proficiency-to-expertise-tui/`.
