---
description: Run the context-selection test matrix against teleclaude__get_context outputs.
argument-hint: '[--csv <path>]'
---

# Run Context Selection Tests

Use the CSV matrix to evaluate get_context selection quality and sensitivity.

## Inputs

- Master CSV: `.agents/tests/get-context-master.csv`
- Run CSV: `.agents/tests/runs/get-context.csv`
- Thinking mode: `med` only for the first pass

## Steps

1. Copy the master CSV to the run CSV path.
2. Load the run CSV and ensure required columns exist (see “CSV Schema”).
3. For each row where `agent` matches the runner:
   - Start a fresh session for the agent.
   - Append the final user request variant (see “Request Variants”).
   - Call `teleclaude__get_context` in **two phases** (index, then selection).
4. Record outputs for **thinking_mode=med** only.
5. Write results back into the CSV (update `med_*` columns).
6. Move the run CSV to `.agents/tests/runs/get-context-<timestamp>.csv`.
7. Summarize misses, false positives, and ambiguous cases.

## Notes

- Set `TELECLAUDE_GET_CONTEXT_TESTING=1` for test runs.
- Treat baseline context as always present.
- Use the two-phase get_context flow when the matrix expects selection.

## CSV Schema

Required input columns:

- `case_id`
- `agent` (claude|codex|gemini)
- `final_request_variants` (pipe-separated variants; choose one per run)

Output columns:

- `med_phase1_areas`
- `med_phase1_index_ids`
- `med_phase2_selected_ids`
- `med_notes`

Additional columns for slow/fast (optional):

- `slow_phase1_areas`
- `slow_phase1_index_ids`
- `slow_phase2_selected_ids`
- `slow_notes`
- `fast_phase1_areas`
- `fast_phase1_index_ids`
- `fast_phase2_selected_ids`
- `fast_notes`
