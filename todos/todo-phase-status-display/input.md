# todo-phase-status-display — Input

Add phase-contextual status columns to the todo pane for prepare and integrate visibility.

## Current state
The todo pane shows work-phase columns only: DOR, B, R, F, D. Prepare and integrate phases have zero visibility in the TUI.

## Prepare statuses (P:)
- P:discovery — input assessment + triangulation phase
- P:requirements — requirements drafting/review phase
- P:planning — implementation plan drafting/review phase
- P:blocked — prepare is stuck, needs attention

Display: shown as a single column when prepare is the active macro-phase. Replaces B/R/F/D columns (which are all pending during prepare). DOR score column still shown alongside when available (gate phase onward).

When prepare completes, P column disappears — the DOR score and green ready status icon already communicate readiness.

## Integrate statuses (I:)
- I:queued — finalize handed off, waiting for integrator pickup
- I:started — integrator is actively processing this candidate
- I:delivered — successfully integrated and delivered
- I:failed — integration failed (conflict, push rejection, etc.)

Display: shown as a single column when the todo has entered integration. Replaces B/R/F/D columns (work is complete at this point).

## Phase detection logic
1. prepare_phase is set and not prepared/blocked → show P:sub-state
2. prepare_phase == blocked → show P:blocked (red)
3. prepare done, build still pending → show DOR only (ready state)
4. build != pending → show existing B/R/F/D work columns (unchanged)
5. finalize.status == handed_off but not yet delivered → show I:queued or I:started
6. Integration active on this candidate → show I:started
7. delivered_at set → show I:delivered
8. Integration failure → show I:failed

## Data pipeline changes needed
- state.yaml: prepare_phase already exists. Add integration_phase field for per-todo integration tracking.
- Integrator state machine: write progress to todo state.yaml as integration_phase during processing.
- roadmap.py: read prepare_phase and integration_phase from state, pass through.
- TodoInfo (core/models.py): add prepare_phase and integration_phase fields.
- TodoDTO (api_models.py): add same two fields.
- TodoItem (cli/tui/todos.py): add same two fields.
- TodoRow (cli/tui/widgets/todo_row.py): phase-aware column rendering — detect current phase, render appropriate columns.

## Mapping from machine states to display labels

### PreparePhase enum → P: label
- input_assessment → P:discovery
- triangulation → P:discovery
- requirements_review → P:requirements
- plan_drafting → P:planning
- plan_review → P:planning
- gate → P:planning (DOR score column shows gate result)
- grounding_check → P:planning
- re_grounding → P:planning
- prepared → (no P column, transitions to ready)
- blocked → P:blocked

### IntegrationPhase enum → I: label
- candidate_dequeued, clearance_wait → I:queued (if not yet active) or I:started
- merge_clean, merge_conflicted, awaiting_commit, committed, delivery_bookkeeping → I:started
- merge_conflicted specifically: I:started (conflict is transient, integrator handles it or escalates to I:failed)
- push_succeeded, cleanup, candidate_delivered, completed → I:delivered
- push_rejected → I:failed

## Color scheme
- P: labels — cyan/blue (planning register)
- P:blocked — red (attention)
- I: labels — magenta/purple (finalizing register)
- I:failed — red (attention)
- I:delivered — green (success)
