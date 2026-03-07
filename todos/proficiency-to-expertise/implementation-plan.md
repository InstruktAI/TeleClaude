# Implementation Plan: proficiency-to-expertise

## Overview

One behavior — replace flat proficiency with structured expertise — flowing through
its consumers. The approach is mechanical: define the model, update each consumer
to read the new shape. ~200 lines of production code + test updates.

## Phase 1: Schema Foundation

### Task 1.1: Expertise Pydantic model

**File(s):** `teleclaude/config/schema.py`

- [ ] Define `ExpertiseLevel = Literal["novice", "intermediate", "advanced", "expert"]`
- [ ] Define expertise type: `dict[str, ExpertiseLevel | dict[str, ExpertiseLevel]]`
  - String value = flat domain (e.g. `teleclaude: novice`)
  - Dict value = structured domain with `default` + freeform sub-areas
- [ ] Add validator: all leaf values must be valid ExpertiseLevel
- [ ] Replace `proficiency` field on `PersonEntry` with `expertise: dict[...] = Field(default_factory=dict)`
- [ ] Add `@model_validator` for backward compat: if `proficiency` is in `model_extra`, migrate to `expertise["software-development"]["default"]` and remove from extra

**Why:** The model is the single source of truth. Every other change reads from it.

**Verify:** Unit tests for valid/invalid expertise structures, migration from proficiency.

### Task 1.2: API DTO

**File(s):** `teleclaude/api_models.py`

- [ ] Replace `proficiency` on `PersonDTO` with `expertise: dict[str, Any] = Field(default_factory=dict)`

**Why:** DTO mirrors schema for API responses. Must stay in sync.

**Verify:** Existing API tests still pass.

### Task 1.3: PersonInfo dataclass

**File(s):** `teleclaude/cli/config_cli.py`

- [ ] Replace `proficiency: str | None = None` with `expertise: dict[str, Any] = field(default_factory=dict)` on `PersonInfo`

**Why:** JSON output from CLI list command uses this dataclass.

**Verify:** `telec config people list --json` outputs expertise structure.

## Phase 2: Consumer Updates

### Task 2.1: CLI commands

**File(s):** `teleclaude/cli/config_cli.py`

- [ ] `_people_list`: change `proficiency=getattr(...)` to `expertise=getattr(p, "expertise", {})`
- [ ] `_people_add`: replace `--proficiency` with `--expertise` (JSON blob), parse with `json.loads`
- [ ] `_people_edit`: replace `--proficiency` handling with `--expertise` (JSON blob, merges into existing)
- [ ] Update error message on line 339 to list `--expertise` instead of `--proficiency`

**Why:** CLI is the primary config interface for agents and scripts.

**Verify:** CLI tests for add/edit/list with expertise.

### Task 2.2: Hook injection

**File(s):** `teleclaude/hooks/receiver.py`

- [ ] Replace lines 263-264: read `expertise` instead of `proficiency`
- [ ] Render human-readable block: `Human in the loop: {name}\nExpertise:\n  {domain}: {level} ({sub-areas})`
- [ ] Handle empty expertise: fall back to just `Human in the loop: {name}` with no expertise block

**Why:** This is the behavioral change — agents see structured expertise instead of flat level.

**Verify:** Injection tests verify rendered format.

### Task 2.3: TUI display

**File(s):** `teleclaude/cli/tui/views/config.py`

- [ ] Line 932: replace `proficiency` display with expertise summary (e.g. show top domain or count)

**Why:** TUI shows person info; must reflect new field.

**Verify:** Visual check via SIGUSR2 reload.

## Phase 3: Tests

### Task 3.1: Schema tests

**File(s):** `tests/unit/test_config_schema.py`

- [ ] Update `test_person_entry_proficiency_default` → test expertise default (empty dict)
- [ ] Update `test_person_entry_proficiency_valid_values` → test expertise with all level values
- [ ] Update `test_person_entry_proficiency_invalid_value` → test invalid level in expertise
- [ ] Add: test flat domain level, structured domain, migration from old proficiency field
- [ ] Add: test freeform domain and sub-area keys

### Task 3.2: CLI tests

**File(s):** `tests/unit/test_config_cli.py`

- [ ] Update `test_add_person_with_proficiency_expert` → test with `--expertise` JSON
- [ ] Update `test_edit_proficiency_novice` → test with `--expertise` JSON
- [ ] Update `test_list_json_includes_proficiency` → test expertise in JSON output

### Task 3.3: Injection tests

**File(s):** `tests/unit/test_hooks_receiver_memory.py`

- [ ] Update `_make_config_with_person` helper: replace `proficiency` param with `expertise`
- [ ] Update `test_print_memory_injection_proficiency_line_prepended` → verify expertise block format
- [ ] Update `test_print_memory_injection_proficiency_line_only` → verify expertise-only output
- [ ] Update `test_print_memory_injection_no_person_match_no_proficiency_line` → no expertise line

### Task 3.4: Config handler test

**File(s):** `tests/unit/test_config_handlers.py`

- [ ] Line 159: update PersonEntry fixture from `proficiency="expert"` to `expertise={...}`

## Phase 4: Validation

### Task 4.1: Full suite

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no unchecked tasks remain

### Task 4.2: Serialization check

- [ ] Verify `save_global_config()` correctly serializes nested expertise to YAML
- [ ] Load the saved config back and verify round-trip fidelity

---

## Referenced files

- `teleclaude/config/schema.py`
- `teleclaude/api_models.py`
- `teleclaude/cli/config_cli.py`
- `teleclaude/hooks/receiver.py`
- `teleclaude/cli/tui/views/config.py`
- `tests/unit/test_config_schema.py`
- `tests/unit/test_config_cli.py`
- `tests/unit/test_hooks_receiver_memory.py`
- `tests/unit/test_config_handlers.py`
