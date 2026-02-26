# Review Findings: api-todos-work-stability-hardening

## Critical

- None.

## Important

1. Single-flight locking leaks across project boundaries because lock key omits `cwd`.
   - Confidence: 96
   - Location: `teleclaude/core/next_machine/core.py:90`, `teleclaude/core/next_machine/core.py:91`, `teleclaude/core/next_machine/core.py:108`, `teleclaude/core/next_machine/core.py:111`
   - Evidence:
     - `_SINGLE_FLIGHT_LOCKS` is keyed only by `slug` (`dict[str, asyncio.Lock]`), and `_get_slug_single_flight_lock(slug)` does not include project root in the key.
     - Manual repro in this review (two independent temp repos, both with slug `same-slug`, patched prep sleep `0.2s`):
       - Concurrent `next_work(...)` elapsed with same slug across different repos: `0.532s`
       - Concurrent `next_work(...)` elapsed with different slugs across different repos: `0.271s`
       - This confirms unrelated repos serialize when slug names collide.
   - Impact:
     - Unrelated repositories interfere with each other and introduce avoidable latency spikes.
     - Violates boundary purity for lock ownership (single-flight should be scoped to repo + slug, not process-global slug).
   - Required fix:
     - Scope single-flight key by canonical project root + slug (for example `dict[tuple[str, str], asyncio.Lock]`).
     - Add regression coverage proving two different repos with the same slug can run prep concurrently.

## Suggestions

1. Comment/docstring drift:
   - `teleclaude/core/next_machine/core.py:1643` says `_sync_file` returns `False` only when source is missing, but it now also returns `False` when source/destination are identical.
   - `teleclaude/core/next_machine/core.py:1738` says planning artifacts are copied unconditionally, but implementation conditionally skips unchanged files.

## Paradigm-Fit Assessment

- Data flow: implementation stays inside existing next-machine orchestration path and helper boundaries.
- Component reuse: extends existing ensure/sync helpers rather than introducing parallel ad-hoc flows.
- Pattern consistency: dispatch/error formatting patterns are preserved, but single-flight scoping currently couples independent project contexts via a process-global slug key.

## Verification Evidence

- `pytest -q tests/unit/test_next_machine_worktree_prep.py tests/unit/test_next_machine_hitl.py tests/unit/test_config_cli.py` -> 78 passed
- Manual behavior check (same repo, repeated calls):
  - First and second `next_work(...)` both dispatched `next-build`
  - Prep executed once (`prep_calls=1`)
  - `NEXT_WORK_PHASE` logs emitted and included `phase=ensure_prepare decision=skip` on repeat call
- Manual isolation check (two repos):
  - Same slug in different repos serialized (`elapsed=0.532s`)
  - Different slugs in different repos ran in parallel (`elapsed=0.271s`)

## Fixes Applied

1. Single-flight locking leaks across project boundaries because lock key omits `cwd`.
   - Fix: `_get_slug_single_flight_lock` now canonicalizes `cwd` via `resolve_canonical_project_root` before keying the in-process lock map, enforcing repo-root + slug isolation even when callers provide non-canonical paths.
   - Regression coverage: added `test_next_work_concurrent_same_slug_different_repos_do_not_serialize_prep` proving same-slug `next_work` prep runs concurrently across two repos.
   - Commit: `e7257f20`

## Verdict

REQUEST CHANGES
