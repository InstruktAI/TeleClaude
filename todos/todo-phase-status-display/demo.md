# Demo: todo-phase-status-display

## Validation

### Verify targeted tests for the changed behavior

```bash
pytest tests/unit/core/test_roadmap.py tests/unit/cli/tui/test_phase_labels.py tests/unit/test_tui_todo_row.py
```

Confirms the pipeline fields, phase-label mapping, and `TodoRow` rendering logic for
`P:*` and `I:*` states.

### Validate the demo artifact structure

```bash
telec todo demo validate todo-phase-status-display
```

Confirms the executable demo blocks remain valid.

### Reload the running TUI after the widget change

```bash
kill -USR2 "$(tmux list-panes -t tc_tui -F '#{pane_pid}' | head -1)"
```

Confirms the live TUI reload path required by the repository instructions.

## Guided Presentation

### Step 1: Show the mapping module

Open `teleclaude/cli/tui/phase_labels.py`. This module contains two pure functions:
`prepare_phase_label()` and `integration_phase_label()`. Each maps a state machine
phase value to a `(display_label, color)` tuple for TUI rendering. Walk through the
mapping tables — PreparePhase values collapse into four user-facing labels (discovery,
requirements, planning, blocked), while IntegrationPhase values collapse into four
(queued, started, delivered, failed).

### Step 2: Show the data pipeline extension

Open `teleclaude/core/models.py` and point to the three new fields on `TodoInfo`:
`prepare_phase`, `integration_phase`, `finalize_status`. Then trace the pipeline:
`read_todo_metadata()` in `roadmap.py` reads them from state.yaml,
`api_server.py` passes them into `TodoDTO`, and `preparation.py` maps them into
`TodoItem`. Each layer carries the same three optional fields.

### Step 3: Show phase-aware column rendering

Open `teleclaude/cli/tui/widgets/todo_row.py`. In `_build_columns()`, the phase
detection logic evaluates top-to-bottom: active prepare → show `P:*`, active
integration or queued handoff → show `I:*`, active build/review/finalize work →
show the existing `B/R/F/D` columns, else → DOR only. The column sets are mutually
exclusive. Show that when all new fields are `None`, the existing `B/R/F/D` path
executes unchanged.

### Step 4: Show fingerprint update

Open `teleclaude/cli/tui/views/preparation.py` and point to the three new entries
in `_todo_fingerprint()`. These ensure the TUI detects phase transitions and triggers
widget rebuilds.

### Step 5: Show integration mirroring

Open `teleclaude/core/integration/state_machine.py` and point to the
`_mirror_integration_phase()` helper. This writes the integration phase to the
candidate's per-todo state.yaml after each checkpoint write, making the data
available to the TUI polling path.

### Step 6: Run the checks

Execute the targeted `pytest` command from the validation section, then run
`telec todo demo validate todo-phase-status-display`. Highlight that the mapping tests
cover every enum value and the rendering tests verify column mutual exclusivity.
