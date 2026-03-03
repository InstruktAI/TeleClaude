# Implementation Plan: person-knowledge-level

## Overview

Add a `knowledge` field to the person data model and inject it into agent sessions
at start time. The change follows the existing injection chain: hook receiver reads
session → looks up person → prepends knowledge context → agent receives it via
`additionalContext`. All changes are additive with safe defaults.

## Phase 1: Core Changes

### Task 1.1: Add `knowledge` field to `PersonEntry`

**File(s):** `teleclaude/config/schema.py`

- [ ] Add `knowledge: Literal["novice", "intermediate", "advanced", "expert"] = "intermediate"`
      to `PersonEntry` (after `role` field, line ~128).

### Task 1.2: Extend memory injection to include knowledge line

**File(s):** `teleclaude/hooks/receiver.py`

- [ ] In `_print_memory_injection()`, after the existing identity resolution block
      (inside the `if session_id:` block where `row` is already fetched), add person
      lookup: iterate `config.people` to find the person matching `row.human_email`.
- [ ] Store `person_name` and `person_knowledge` from the matched `PersonEntry`.
- [ ] After building `context` from `_get_memory_context()`, prepend the knowledge line
      if a person was found: `Human in the loop: {person_name} ({person_knowledge})`.
- [ ] Adjust the early return: proceed with injection even if memory context is empty
      but a knowledge line exists (the knowledge line alone is valid injection content).

### Task 1.3: Add `--knowledge` to CLI people commands

**File(s):** `teleclaude/cli/config_cli.py`

- [ ] In `PersonInfo` dataclass, add `knowledge: str | None = None`.
- [ ] In `_people_list()`, populate `info.knowledge` from `person.knowledge` (the
      `PersonEntry` field via `getattr` for safety, defaulting to `"intermediate"`).
- [ ] In `_people_add()`, read `opts.get("knowledge")` and pass it to `PersonEntry()`
      constructor.
- [ ] In `_people_edit()`, add `"knowledge"` to the check for editable global entry
      fields (`any(k in opts for k in ("role", "email", "username", "knowledge"))`).
      In the edit loop, add: `if "knowledge" in opts: p.knowledge = opts["knowledge"]`.
- [ ] Update the "no changes" error message to include `--knowledge` in the list of
      valid flags.

### Task 1.4: Add `knowledge` to `PersonDTO`

**File(s):** `teleclaude/api_models.py`

- [ ] Add `knowledge: Literal["novice", "intermediate", "advanced", "expert"] = "intermediate"`
      to `PersonDTO`.

### Task 1.5: Show knowledge level in TUI config wizard

**File(s):** `teleclaude/cli/tui/views/config.py`

- [ ] In `_render_people()`, after rendering role and email for each person, append
      the knowledge level: `result.append(f" [{person.knowledge}]", style=_DIM)`.
      Use `getattr(person, "knowledge", "intermediate")` for safety.

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Add unit test for `PersonEntry` schema: valid values accepted, invalid rejected.
- [ ] Add unit test for `_print_memory_injection` knowledge line output: mock session
      row with `human_email`, mock `config.people` with matching person, verify output
      contains `Human in the loop:` prefix.
- [ ] Add unit test for CLI `_people_add` with `--knowledge expert`: verify `PersonEntry`
      is created with `knowledge="expert"`.
- [ ] Add unit test for CLI `_people_edit` with `--knowledge novice`: verify field update.
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
