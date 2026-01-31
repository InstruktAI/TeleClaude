---
description: Run the context-selection test matrix against teleclaude__get_context outputs.
argument-hint: '[--csv <path>]'
---

@~/.teleclaude/docs/software-development/role/tester.md

# Run Context Selection Tests

You are now the Tester.

## Purpose

Evaluate get_context selection quality using the CSV test matrix.

## Inputs

- Master CSV: `.agents/tests/get-context-master.csv`
- Run CSV: `.agents/tests/runs/get-context.csv`
- Environment: `TELECLAUDE_GET_CONTEXT_TESTING=1`
- Thinking mode: `med` only for the first pass

## Outputs

- Updated run CSV with `med_*` columns
- Archived run CSV at `.agents/tests/runs/get-context-<timestamp>.csv`
- Summary of misses, false positives, and ambiguous cases

## Steps

- Copy the master CSV to the run CSV path.
- Ensure required columns exist: `case_id`, `agent`, `final_request_variants`.
- For each row where `agent` matches the runner:
  - Start a fresh session for the agent.
  - Append the final request variant.
  - Call `teleclaude__get_context` in two phases (index, then selection).
- Record outputs for thinking*mode=med only into `med*\*` columns.
- Move the run CSV to `.agents/tests/runs/get-context-<timestamp>.csv`.
- Summarize misses, false positives, and ambiguous cases.
