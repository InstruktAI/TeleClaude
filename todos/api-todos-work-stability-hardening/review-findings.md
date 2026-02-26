# Review Findings: api-todos-work-stability-hardening

## Critical

1. New prep-state marker is treated as user dirty state, causing `/todos/work` to fail immediately after prep.
   - Confidence: 99
   - Location: `teleclaude/core/next_machine/core.py:73`, `teleclaude/core/next_machine/core.py:2018`, `teleclaude/core/next_machine/core.py:1805`
   - Evidence:
     - Prep writes `.teleclaude/worktree-prep-state.json` (`_WORKTREE_PREP_STATE_REL`, `_write_worktree_prep_state`).
     - `has_uncommitted_changes(...)` ignores only roadmap + `todos/{slug}` paths, not `.teleclaude/`.
     - Concrete repro (this review):
       - Minimal temp repo + slug, call `next_work(...)` once.
       - Returned first line: `UNCOMMITTED CHANGES in trees/single-flight`.
       - `git status --porcelain` in worktree showed: `?? .teleclaude/`.
   - Impact:
     - First prep for a slug can self-trigger uncommitted-change blocking and prevent normal build dispatch.
     - Violates behavior parity/safety requirement (`R5`) by introducing a new false-positive guardrail failure.
   - Required fix:
     - Treat prep-state marker as orchestrator-owned (ignore it in `has_uncommitted_changes`, or move marker under an already-ignored orchestrator path).
     - Add regression coverage asserting `next_work(...)` can dispatch after prep without patching `has_uncommitted_changes`.

## Important

1. Test coverage currently masks the above regression.
   - Confidence: 95
   - Location: `tests/unit/test_next_machine_hitl.py:826`
   - Evidence:
     - New concurrent single-flight test patches `has_uncommitted_changes` to `False`.
     - This bypass hides dirty-path interactions from the new prep-state file.
   - Required fix:
     - Add at least one test that exercises real dirty-path filtering with prep-state marker present.

## Suggestions

1. Comment/docstring drift:
   - `teleclaude/core/next_machine/core.py:1639` says `_sync_file` returns `False` only when source is missing, but it now also returns `False` when source/destination are identical.
   - `teleclaude/core/next_machine/core.py:1738` says planning artifacts are copied unconditionally, but the implementation now conditionally skips unchanged files.

## Paradigm-Fit Assessment

- Data flow: implementation stays inside existing next-machine orchestration path and helper boundaries.
- Component reuse: extends existing ensure/sync helpers rather than introducing parallel ad-hoc flows.
- Pattern consistency: dispatch/error formatting patterns are preserved; no transport-bound leakage into domain policy observed.

## Verification Evidence

- `pytest -q tests/unit/test_next_machine_worktree_prep.py tests/unit/test_next_machine_hitl.py -q` -> 52 passed
- `pytest -q tests/unit/test_config_cli.py -q` -> 26 passed
- Manual repro (temp git repo): first `next_work(...)` returned `UNCOMMITTED CHANGES in trees/single-flight`; worktree status contained `?? .teleclaude/`.

## Verdict

REQUEST CHANGES

## Fixes Applied

1. Critical: prep-state marker was treated as user dirty state.
   - Fix: `has_uncommitted_changes(...)` now ignores orchestrator-owned `.teleclaude` prep-state paths, including directory-form porcelain output (`?? .teleclaude/`).
   - Commit: `8493525d`
2. Important: concurrent single-flight test masked dirty-path regression by stubbing dirty checks.
   - Fix: `test_next_work_concurrent_same_slug_single_flight_prep` now runs against a real git repo/worktree and no longer patches `has_uncommitted_changes`, asserting dispatch succeeds with prep-state marker present.
   - Commit: `0e7090a3`
