# Implementation Plan: todo-phase-status-display

## Overview

Surface prepare and integrate phase visibility in the TUI todo pane. The work extends
the data pipeline (state.yaml → TodoInfo → TodoDTO → TodoItem → TodoRow) with
`prepare_phase`, `integration_phase`, and `finalize_status` fields, then adds
phase-aware column rendering in TodoRow.

The approach follows the existing pipeline pattern: each layer carries optional fields,
`read_todo_metadata()` is the single read site, and `_build_columns()` is the single
render site. A new `phase_labels.py` module isolates the enum-to-label mapping as pure
functions for independent testability.

## Tasks

### Task 1: Add `prepare_phase`, `integration_phase`, and `finalize_status` to data models

**File(s):** `teleclaude/core/models.py`, `teleclaude/api_models.py`,
`teleclaude/cli/tui/todos.py`

- [ ] Add `prepare_phase: Optional[str] = None`, `integration_phase: Optional[str] = None`,
  `finalize_status: Optional[str] = None` to `TodoInfo` dataclass (~line 1013)
- [ ] Update `TodoInfo.from_dict()` to read the three new fields from the dict using
  `cast(Optional[str], data.get(...))` pattern matching existing fields
- [ ] Add the same three fields to `TodoDTO` (~line 206) as `str | None = None`
- [ ] Add the same three fields to `TodoItem` (~line 22) as `str | None = None`

**Why:** These are the carriers for all downstream rendering. All three layers must be
extended simultaneously to maintain the invariant that the pipeline preserves all fields
end-to-end. Backward compatible — `None` defaults mean existing state.yaml without these
fields renders identically to today.

**Verification:** Unit test constructing TodoInfo with new fields, serializing to dict,
deserializing via `from_dict()`, asserting round-trip fidelity. Test `None` defaults.

---

### Task 2: Read `prepare_phase`, `integration_phase`, `finalize_status` in `read_todo_metadata()`

**File(s):** `teleclaude/core/roadmap.py`

- [ ] In `read_todo_metadata()` (~line 87), after the existing state parsing block:
  - Read `prepare_phase = state.get("prepare_phase")` — coerce empty string to `None`
  - Read `finalize_status` from `state.get("finalize", {}).get("status")` — only accept
    known values (`"pending"`, `"ready"`, `"handed_off"`), else `None`
  - Read `integration_phase = state.get("integration_phase")` — coerce empty string to
    `None` (this field doesn't exist in state.yaml yet; Task 6 adds the writer)
- [ ] Expand the return tuple to include `prepare_phase`, `integration_phase`,
  `finalize_status` (3 new elements)
- [ ] Update `append_todo()` (~line 162) to unpack the expanded tuple and pass
  `prepare_phase=`, `integration_phase=`, `finalize_status=` to `TodoInfo(...)`

**Why:** `read_todo_metadata()` is the single place that reads state.yaml for todo
metadata. Adding reads here ensures all consumers get the data without scatter-shot
changes. The finalize status comes from the nested `finalize.status` dict already
written by the work state machine.

**Verification:** Unit test with mock state.yaml containing the new fields → verify
correct extraction. Test missing fields → `None`. Test empty string → `None`.

---

### Task 3: Pass new fields through TodoInfo→TodoDTO→TodoItem construction sites

**File(s):** `teleclaude/api_server.py`, `teleclaude/cli/tui/views/preparation.py`

- [ ] Update `TodoDTO(...)` at ~line 2017 (local project path) to pass:
  `prepare_phase=t.prepare_phase, integration_phase=t.integration_phase,
  finalize_status=t.finalize_status`
- [ ] Update `TodoDTO(...)` at ~line 2050 (cache entries) to pass:
  `prepare_phase=todo.prepare_phase, integration_phase=todo.integration_phase,
  finalize_status=todo.finalize_status`
- [ ] Update `TodoDTO(...)` at ~line 2443 (WS projects) to pass:
  `prepare_phase=t.prepare_phase, integration_phase=t.integration_phase,
  finalize_status=t.finalize_status`
- [ ] Update `TodoItem(...)` in `preparation.py` (~line 168) to pass:
  `prepare_phase=getattr(t, "prepare_phase", None),
  integration_phase=getattr(t, "integration_phase", None),
  finalize_status=getattr(t, "finalize_status", None)`

**Why:** The pipeline is field-by-field, not dict-based. Every construction site must
explicitly pass new fields or they silently drop to `None`. The `getattr` pattern in
`preparation.py` matches the existing defensive style for cross-version compat with
cached data.

**Verification:** Covered by V1 end-to-end pipeline test.

---

### Task 4: Enum-to-label mapping functions

**File(s):** `teleclaude/cli/tui/phase_labels.py` (new)

- [ ] Create `prepare_phase_label(phase: str | None) -> tuple[str, str] | None`:
  - `input_assessment`, `triangulation` → `("P:discovery", "cyan")`
  - `requirements_review` → `("P:requirements", "cyan")`
  - `plan_drafting`, `plan_review`, `gate`, `grounding_check`, `re_grounding` →
    `("P:planning", "cyan")`
  - `blocked` → `("P:blocked", "red")`
  - `prepared`, `""`, `None` → `None` (no P column)
  - Unknown values → `None` (defensive)
- [ ] Create `integration_phase_label(phase: str | None, finalize_status: str | None) -> tuple[str, str] | None`:
  - `finalize_status == "handed_off"` AND `phase` is `None` → `("I:queued", "magenta")`
  - `candidate_dequeued`, `clearance_wait`, `merge_clean`, `merge_conflicted`,
    `awaiting_commit`, `committed`, `delivery_bookkeeping` → `("I:started", "magenta")`
  - `push_succeeded`, `cleanup`, `candidate_delivered`, `completed` →
    `("I:delivered", "green")`
  - `push_rejected` → `("I:failed", "red")`
  - Both `None` → `None` (no I column)

**Why:** Isolating mapping in pure functions enables testing without TUI instantiation.
The mapping is display-only — no enum or state machine modification. A separate module
keeps TodoRow focused on layout. Returning `(label, color)` tuples lets the renderer
apply Rich styles directly.

**Verification:** Unit tests covering every PreparePhase and IntegrationPhase enum
value → correct label and color. Edge cases: `None`, empty string, unknown values.

---

### Task 5: Phase-aware column rendering in TodoRow

**File(s):** `teleclaude/cli/tui/widgets/todo_row.py`

- [ ] In `compute_col_widths()`: add `"P": 0` and `"I": 0` to `maxes`. For each todo,
  call `prepare_phase_label()` and `integration_phase_label()` to get rendered labels,
  measure length, update max widths. Absent labels → width 0.
- [ ] In `_build_columns()`: implement phase detection (top-to-bottom, first match wins):
  1. Call `prepare_phase_label(self.todo.prepare_phase)` — if not `None`:
     render P column with returned label/color + DOR column if available. Return (skip
     B/R/F/D).
  2. Else call `integration_phase_label(self.todo.integration_phase,
     self.todo.finalize_status)` — if not `None`:
     render I column with returned label/color. Return (skip B/R/F/D).
  3. Else if `build_status` is not `None` and not `"pending"`:
     render existing DOR + B/R/F/D columns (unchanged path).
  4. Else: render DOR only (ready/pending state, no extra columns).

**Why:** Phase-aware rendering is the core deliverable. Top-to-bottom detection with
early return preserves the existing B/R/F/D path byte-for-byte when no prepare or
integration phase data is present (R8 regression safety). Integration must outrank the
build-complete branch once handoff begins, otherwise `build_status="complete"` would
mask every `I:*` state and the feature would never become visible. The P column renders
alongside DOR because the DOR score becomes available during the gate phase of prepare.

**Verification:** Unit tests for phase detection (V3, V4):
- `prepare_phase="plan_drafting"` → P:planning column, no B/R/F/D
- `prepare_phase="blocked"` → P:blocked in red
- `build_status="complete"` → existing B/R/F/D columns
- `finalize_status="handed_off"`, no `integration_phase` → I:queued
- `integration_phase="merge_clean"` → I:started
- `integration_phase="candidate_delivered"` → I:delivered in green
- `integration_phase="push_rejected"` → I:failed in red
- All new fields `None` → identical to current rendering (regression)

---

### Task 6: Integration state machine mirrors phase to per-todo state.yaml

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] Add helper `_mirror_integration_phase(cwd: str, slug: str, phase: str) -> None`:
  ```python
  from teleclaude.core.next_machine.core import read_phase_state, write_phase_state
  state = read_phase_state(cwd, slug)
  state["integration_phase"] = phase
  write_phase_state(cwd, slug, state)
  ```
- [ ] Call `_mirror_integration_phase()` after key phase transitions where
  `checkpoint.candidate_slug` is set:
  - After `CANDIDATE_DEQUEUED` write
  - After `MERGE_CLEAN` / `MERGE_CONFLICTED` / `AWAITING_COMMIT` / `COMMITTED` /
    `DELIVERY_BOOKKEEPING` writes
  - After `PUSH_SUCCEEDED` write
  - After `PUSH_REJECTED` write
  - After `CANDIDATE_DELIVERED` write

**Why:** The integration checkpoint is a singleton tracking the current candidate.
Per-todo `state.yaml` is what `read_todo_metadata()` reads. Without mirroring, the TUI
has no per-todo integration data. Mirroring is best-effort — timing lag is acceptable
per requirements risk section. Uses existing `read_phase_state`/`write_phase_state` for
consistency with the state.yaml I/O pattern.

**Verification:** Unit tests that drive the relevant integration transition paths with
a candidate slug and assert the candidate todo's `state.yaml` is updated when the
checkpoint advances to a started state, a delivered state, and a failed state. A small
helper-focused test may cover the raw write path, but transition-level assertions are
required so the plan proves the mirror calls were actually wired in.

---

### Task 7: TUI fingerprint update

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [ ] In `_todo_fingerprint()` (~line 103), add three entries after `t.group or ""`:
  ```python
  t.prepare_phase or "",
  t.integration_phase or "",
  t.finalize_status or "",
  ```
  Note: the fingerprint iterates over `TodoDTO` properties (via `ProjectWithTodosInfo`
  which is `ProjectWithTodosDTO`), so these are the DTO field names — already added in
  Task 1.

**Why:** Without fingerprint inclusion, the TUI won't detect phase transitions and won't
rebuild widgets when phases advance. This is the change detection gate.

**Verification:** Unit test: two TodoDTO objects differing only in `prepare_phase` →
different fingerprints. Same for `integration_phase` and `finalize_status`.

---

### Task 8: Targeted verification, hook validation, and live TUI check

**File(s):** All modified files

- [ ] During RED/GREEN, run the smallest affected unit test files first (pipeline,
  mapping, TodoRow rendering, fingerprint, integration mirroring); only broaden scope
  if targeted coverage is inconclusive
- [ ] Run repository pre-commit hooks as the final verification path
- [ ] Validate the demo artifact with `telec todo demo validate todo-phase-status-display`
- [ ] Reload the running TUI with `SIGUSR2` per repo instructions and verify prepare
  todos show `P:*` columns while integration todos show the appropriate `I:*` columns
- [ ] Confirm hook output covers linting and type-checking with no violations
- [ ] Verify no debug/temp code remains

**Why:** The repo's testing policy requires targeted tests during development and
pre-commit hooks as the primary final verification path. This todo changes TUI code, so
the repo-specific reload procedure and an observed live check are required evidence that
the new columns render correctly outside isolated unit tests. Demo validation keeps the
presentation artifact executable and aligned with the delivered behavior.

**Verification:** Targeted tests fail first then pass, pre-commit hooks pass, demo
validation exits 0, and the reloaded TUI visibly reflects phase transitions.

## Execution Order

```
Task 1 (models) → Task 2 (reader) → Task 3 (passthrough) → Task 4 (labels)
                                                               ↓
                                                         Task 5 (rendering)
                                                               ↓
Task 6 (integration mirror) ─────────────────────────── Task 7 (fingerprint)
                                                               ↓
                                                         Task 8 (final check)
```

Task 6 is independent of Tasks 5 and 7 and can be done in parallel.
Tests are written first in each task's RED-GREEN cycle per TDD policy.

## Deferrals

None. All requirements (R1–R8) are addressed.
