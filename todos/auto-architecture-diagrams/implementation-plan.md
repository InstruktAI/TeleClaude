# Implementation Plan: auto-architecture-diagrams

## Overview

Build a set of Python extraction scripts under `scripts/diagrams/` that parse the TeleClaude codebase using the `ast` module and emit Mermaid diagram files. A `make diagrams` target orchestrates all scripts and writes output to `docs/diagrams/`. Each script is standalone and focused on one diagram type.

## Files to Change

| File                                         | Change                                                         |
| -------------------------------------------- | -------------------------------------------------------------- |
| `scripts/diagrams/extract_state_machines.py` | Create — parse next_machine enums and state.json schema        |
| `scripts/diagrams/extract_events.py`         | Create — parse events.py, HOOK_EVENT_MAP, coordinator handlers |
| `scripts/diagrams/extract_data_model.py`     | Create — parse SQLModel classes from db_models.py              |
| `scripts/diagrams/extract_modules.py`        | Create — parse import statements across teleclaude/            |
| `scripts/diagrams/extract_commands.py`       | Create — parse agents/commands/ markdown frontmatter           |
| `scripts/diagrams/extract_runtime_matrix.py` | Create — parse HOOK_EVENT_MAP and adapter features             |
| `Makefile`                                   | Add `diagrams` target                                          |
| `.gitignore`                                 | Add `docs/diagrams/` if we decide on gitignored output         |

## Phase 1: Extraction Scripts

### Task 1.1: State machine diagram

**File(s):** `scripts/diagrams/extract_state_machines.py`

- [ ] Parse `PhaseName`, `PhaseStatus`, `RoadmapMarker`, `RoadmapBox` enums from `teleclaude/core/next_machine/core.py` using `ast`
- [ ] Parse `DEFAULT_STATE` dict for state.json schema
- [ ] Emit Mermaid state diagram for roadmap lifecycle (4 states)
- [ ] Emit Mermaid state diagram for build/review phase transitions (pending → complete → approved, with changes_requested loop)
- [ ] Write to `docs/diagrams/state-machines.mmd`

### Task 1.2: Event flow diagram

**File(s):** `scripts/diagrams/extract_events.py`

- [ ] Parse `AgentHookEventType` (Literal type alias) and `EventType` (Literal type alias) from `teleclaude/core/events.py` using `ast.Assign`/`ast.Subscript` nodes (not ClassDef — these are Literal aliases, not enums)
- [ ] Parse `HOOK_EVENT_MAP` class attribute from `AgentHookEvents` class in `teleclaude/core/events.py` to extract per-runtime event mappings
- [ ] Parse handler method names from `AgentCoordinator.handle_event()` dispatch in `teleclaude/core/agent_coordinator.py`
- [ ] Emit Mermaid flowchart: agent runtime → native event → internal event → handler → side effects
- [ ] Write to `docs/diagrams/event-flow.mmd`

### Task 1.3: Data model ERD

**File(s):** `scripts/diagrams/extract_data_model.py`

- [ ] Parse all `class Foo(SQLModel, table=True)` definitions from `teleclaude/core/db_models.py`
- [ ] Extract field names, types, and `Field()` metadata (primary_key, foreign_key)
- [ ] Emit Mermaid ER diagram with relationships
- [ ] Write to `docs/diagrams/data-model.mmd`

### Task 1.4: Module dependency graph

**File(s):** `scripts/diagrams/extract_modules.py`

- [ ] Walk all `.py` files under `teleclaude/`
- [ ] Parse `import` and `from ... import` statements using `ast`
- [ ] Group by package (`core`, `hooks`, `mcp`, `cli`, `api`, `adapters`, `memory`, `transport`, `cron`)
- [ ] Emit Mermaid flowchart showing inter-package dependencies (package level, not module level to avoid noise)
- [ ] Write to `docs/diagrams/module-layers.mmd`

### Task 1.5: Command dispatch diagram

**File(s):** `scripts/diagrams/extract_commands.py`

- [ ] Parse YAML frontmatter from `agents/commands/*.md` (description field)
- [ ] Parse H1 titles and `## Steps` sections for dispatch references (e.g., "dispatch next-build")
- [ ] Emit Mermaid flowchart showing command orchestration: prepare → gate → work → build → review → fix → finalize
- [ ] Write to `docs/diagrams/command-dispatch.mmd`

### Task 1.6: Runtime feature matrix

**File(s):** `scripts/diagrams/extract_runtime_matrix.py`

- [ ] Parse `HOOK_EVENT_MAP` from `teleclaude/core/events.py` — count events per runtime
- [ ] Parse adapter files under `teleclaude/adapters/` for transcript format, blocking support
- [ ] Parse `teleclaude/helpers/agent_types.py` for `AgentName` enum and `teleclaude/core/agents.py` for agent config (resume template, thinking modes)
- [ ] Emit Mermaid table or annotated class diagram showing feature support per runtime
- [ ] Write to `docs/diagrams/runtime-matrix.mmd`

### Task 1.7: Makefile target

**File(s):** `Makefile`

- [ ] Add `diagrams` target that creates `docs/diagrams/` dir and runs all 6 extraction scripts
- [ ] Add `docs/diagrams/` to `.gitignore` (regenerated, not committed)

---

## Phase 2: Validation

### Task 2.1: Spot-check accuracy

- [ ] Run `make diagrams` and verify each .mmd file renders correctly
- [ ] Cross-reference state machine diagram against `core/next_machine/core.py` enums
- [ ] Cross-reference event flow against `core/events.py` HOOK_EVENT_MAP
- [ ] Cross-reference ERD against `core/db_models.py` table definitions
- [ ] Verify Mermaid syntax is valid (GitHub preview or `mmdc` if available)

### Task 2.2: Quality Checks

- [ ] Scripts use only stdlib (no external deps)
- [ ] `make diagrams` completes in < 5 seconds
- [ ] Each script is independently runnable (`python scripts/diagrams/extract_*.py`)
- [ ] Run `make lint` on new scripts

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
