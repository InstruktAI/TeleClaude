# Review Findings: api-todos-work-stability-hardening

## Critical

- None.

## Important

1. Prep invalidation misses root config changes, so stale worktree config can be reused.
   - Confidence: 98
   - Location: `teleclaude/core/next_machine/core.py:74`, `teleclaude/core/next_machine/core.py:1975`, `teleclaude/core/next_machine/core.py:2034`, `tools/worktree-prepare.sh:88`
   - Evidence:
     - `_compute_prep_inputs_digest(...)` hashes `tools/worktree-prepare.sh` plus worktree manifests/lockfiles, but not root `config.yml`.
     - `tools/worktree-prepare.sh` regenerates worktree `config.yml` from root `config.yml` during prep.
     - Concrete repro in this review: first `ensure_worktree_with_policy(...)` returned `prepared=True` (`prep_state_missing`); after editing root `config.yml`, second call returned `prepared=False` with `prep_reason='unchanged_known_good'`.
   - Impact:
     - `/todos/work` can skip prep after root config edits, leaving `trees/{slug}/config.yml` stale and diverged from main.
   - Required fix:
     - Include root `config.yml` (and any other root inputs consumed by prep) in prep-input digest, and add a unit test that asserts prep runs when root config changes.

## Suggestions

1. Comment/docstring drift:
   - `teleclaude/core/next_machine/core.py:1639` says `_sync_file` returns `False` only when source is missing, but it now also returns `False` when contents match.
   - `teleclaude/core/next_machine/core.py:1734` says planning artifacts are copied unconditionally, but copy is now conditional on content change.
2. Manual verification gap:
   - I validated targeted unit tests only (`test_next_machine_worktree_prep.py`, `test_next_machine_hitl.py`, `test_config_cli.py`).
   - I did not run live `/todos/work` + daemon log inspection (`instrukt-ai-logs ... NEXT_WORK_PHASE`) in this review environment.

## Paradigm-Fit Assessment

- Data flow: follows existing `next_machine` orchestration path and helper boundaries; no adapter bypasses observed.
- Component reuse: reuses existing worktree/sync helpers and extends them instead of copy-pasting parallel flows.
- Pattern consistency: follows existing dispatch/error contracts (`format_error`, `format_tool_call`, phase checks).

## Verification Evidence

- `pytest -q tests/unit/test_next_machine_worktree_prep.py` -> 7 passed
- `pytest -q tests/unit/test_next_machine_hitl.py` -> 44 passed
- `pytest -q tests/unit/test_config_cli.py` -> 26 passed

## Fixes Applied

1. Prep invalidation misses root config changes.
   - Fix: Added root prep-input tracking for `config.yml` in `_compute_prep_inputs_digest(...)` and added regression test `test_runs_preparation_when_root_config_changes`.
   - Commit: `948e8e2e`

## Verdict

REQUEST CHANGES
