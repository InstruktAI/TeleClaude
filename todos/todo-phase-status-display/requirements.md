# Requirements: todo-phase-status-display

## Goal

Make prepare and integrate phases visible in the TUI todo pane. Currently only
work-phase columns (DOR, B, R, F, D) are shown. Prepare and integrate have zero
TUI visibility despite being tracked in the state machine.

## In scope

1. Extend the data pipeline (state.yaml → TodoInfo → TodoDTO → TodoItem → TodoRow)
   with `prepare_phase` and `integration_phase` fields.
2. Surface the queued integration handoff signal needed for `I:queued`.
3. Phase-aware column rendering in TodoRow: detect the active macro-phase and
   render the appropriate column set instead of always showing B/R/F/D.
4. Enum-to-label mapping for display (PreparePhase → `P:` labels,
   IntegrationPhase → `I:` labels).
5. Color scheme per the input spec.
6. Fingerprint update so the TUI detects phase changes as data changes.

## Out of scope

- Changes to prepare state machine behavior.
- Changes to integration state machine behavior beyond emitting per-todo phase
  metadata needed for display.
- New TUI interactions (clicking, expanding, filtering by phase).
- Modifying the DOR column behavior (it continues to render as-is).
- Changes to the WebSocket event protocol beyond exposing the new phase metadata.

## Requirements

### R1: Pipeline — prepare_phase field

Add `prepare_phase: str | None` to every layer in the data pipeline:

- `read_todo_metadata()` in `teleclaude/roadmap.py`: read `prepare_phase` from
  the todo's `state.yaml`. [inferred] Use the existing `read_todo_metadata()`
  state parsing path that already reads `build`, `review`, `dor`, etc.
- `TodoInfo` dataclass in `teleclaude/core/models.py` (~line 1002): add
  `prepare_phase: Optional[str] = None`.
- `TodoDTO` in `teleclaude/api_models.py` (~line 190): add
  `prepare_phase: str | None = None`.
- `TodoItem` in `teleclaude/cli/tui/todos.py`: add
  `prepare_phase: str | None = None`.
- All construction sites that build these objects field-by-field (api_server.py,
  preparation.py) must pass the new field through.

### R2: Pipeline — integration_phase field

Add `integration_phase: str | None` to every layer in the data pipeline, same
locations as R1.

[inferred] `integration_phase` does not currently exist in per-todo `state.yaml`;
the integration state machine currently tracks progress in a separate checkpoint
file (`teleclaude/core/integration/state_machine.py`). To preserve the existing
todo metadata read path, the integrator must mirror the candidate's externally
observable integration phase into that todo's `state.yaml` while processing,
delivering, or failing the candidate.

### R3: Pipeline — integration queued signal

The todo data available to `TodoRow` must distinguish "finalize handed off but
integration has not started on this candidate yet" from "this candidate is
actively being integrated."

[inferred] The current todo pipeline does not expose `finalize.status`, but the
input's phase detection logic requires it for the `I:queued` state. The data
pipeline must therefore surface either:

- `finalize_status: str | None` derived from `state.yaml.finalize.status`, or
- an equivalent derived boolean that means "integration queued for this todo."

### R4: Phase-aware column rendering

`TodoRow._build_columns()` (in `teleclaude/cli/tui/widgets/todo_row.py`) must
detect the active macro-phase and render the appropriate column set:

| Condition | Columns shown |
|-----------|---------------|
| `prepare_phase` is set and not `prepared`/`blocked` → active prepare | `P:{label}` only (plus DOR when available) |
| `prepare_phase == blocked` | `P:blocked` only (red) |
| Prepare done, build still pending | DOR only (ready state — no extra columns) |
| `build_status != pending` | Existing B/R/F/D columns (unchanged behavior) |
| `finalize.status == handed_off` (or equivalent queued signal) and integration has not started on this candidate yet | `I:queued` only |
| Integration active (`integration_phase` set, not delivered/failed) | `I:{label}` only |
| Integration delivered | `I:delivered` only (green) |
| Integration failed | `I:failed` only (red) |

The column sets are mutually exclusive per phase — not additive. The phase
detection logic evaluates top-to-bottom; the first matching condition wins.

`compute_col_widths()` must account for the new column keys (`P`, `I`) in
addition to the existing `DOR`, `B`, `R`, `F`, `D`.

### R5: Enum-to-label mapping

#### PreparePhase → P: label

| PreparePhase value | Display label |
|-------------------|---------------|
| `input_assessment` | `P:discovery` |
| `triangulation` | `P:discovery` |
| `requirements_review` | `P:requirements` |
| `plan_drafting` | `P:planning` |
| `plan_review` | `P:planning` |
| `gate` | `P:planning` |
| `grounding_check` | `P:planning` |
| `re_grounding` | `P:planning` |
| `prepared` | (no P column) |
| `blocked` | `P:blocked` |

#### IntegrationPhase → I: label

| IntegrationPhase value | Display label |
|-----------------------|---------------|
| `candidate_dequeued` | `I:started` |
| `clearance_wait` | `I:started` |
| `merge_clean` | `I:started` |
| `merge_conflicted` | `I:started` |
| `awaiting_commit` | `I:started` |
| `committed` | `I:started` |
| `delivery_bookkeeping` | `I:started` |
| `push_succeeded` | `I:delivered` |
| `cleanup` | `I:delivered` |
| `candidate_delivered` | `I:delivered` |
| `completed` | `I:delivered` |
| `push_rejected` | `I:failed` |

`I:queued` is driven by the queued handoff signal from R3 rather than by a
terminal `IntegrationPhase` value.

### R6: Color scheme

| Label | Color |
|-------|-------|
| `P:discovery`, `P:requirements`, `P:planning` | cyan (planning register) |
| `P:blocked` | red (attention) |
| `I:queued`, `I:started` | magenta (finalizing register) |
| `I:delivered` | green (success) |
| `I:failed` | red (attention) |

Colors must use the existing Rich style/color system used by TodoRow.

### R7: TUI fingerprint update

`PreparationView._todo_fingerprint()` must include `prepare_phase` and
`integration_phase`, plus the queued integration signal from R3, so the TUI
detects phase transitions as data changes requiring a widget rebuild.

### R8: No regressions in existing column behavior

When `build_status != pending` and no integration phase is active, the existing
B/R/F/D column rendering must be byte-identical to current behavior. The phase
detection logic must not alter the work-phase display path.

## Verification

- **V1**: Unit test that `read_todo_metadata()` and the TodoInfo → TodoDTO →
  TodoItem serialization chain preserve `prepare_phase`, `integration_phase`,
  and the queued integration signal from `state.yaml` to the TUI model.
- **V2**: Unit tests for the enum-to-label mapping functions (R5). Every
  PreparePhase and IntegrationPhase value maps to the correct display label.
- **V3**: Unit tests for phase detection logic (R4). Given a TodoItem with
  various combinations of prepare_phase, build_status, `finalize.status` (or
  the queued integration signal), and integration_phase, assert the correct
  column set is rendered.
- **V4**: Unit test that existing B/R/F/D rendering is unchanged when
  prepare_phase is None and integration_phase is None (R8).
- **V5**: [inferred] Integration test or manual verification that a todo in
  prepare phase shows `P:` columns in the TUI, and a todo in integration shows
  `I:queued`, `I:started`, `I:delivered`, and `I:failed` at the appropriate
  lifecycle points.
- **V6**: Fingerprint change detection (R7) — a TodoItem with different
  prepare_phase values, integration_phase values, or queued integration signal
  values produces different fingerprints.

## Constraints

- The `PreparePhase` enum in `core/next_machine/core.py` and `IntegrationPhase`
  enum in `core/integration/state_machine.py` are not modified. The mapping is
  display-only, living in the TUI layer.
- No new dependencies. Uses existing Rich styling already in TodoRow.
- The pipeline extension (R1, R2) must be backward-compatible: todos without
  these fields in state.yaml must render as they do today (None → no P/I column
  → fall through to existing logic).

## Risks

- **Integration checkpoint mirroring (R2)**: There is a timing window where the
  mirrored `integration_phase` in `state.yaml` may lag the integrator's
  checkpoint. This is acceptable for display purposes — the TUI polls
  periodically and the next update will reflect the correct state.
- **Column width calculation**: Adding new column keys to `compute_col_widths()`
  must handle the case where only some rows have P/I columns (mixed phase states
  in the todo list). [inferred] Max-width calculation should treat absent columns
  as width 0.
