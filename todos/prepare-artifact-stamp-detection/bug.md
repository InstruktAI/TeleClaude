# Bug: prepare state machine uses filesystem heuristics to detect artifact existence instead of artifact lifecycle stamps. Three locations: (1) _prepare_step_test_spec_build uses \_has_test_spec_artifacts which globs worktree for any test_\*.py containing the string 'xfail' — wrong because all files from main are in the worktree and any pre-existing test file mentioning xfail triggers a false positive; (2) plan drafting step uses check_file_has_content for implementation-plan.md; (3) requirements steps use check_file_has_content for requirements.md. Fix: replace all three with artifact stamp checks (state['artifacts'][key]['produced_at'] non-empty). Add 'test_specs' to DEFAULT_STATE.artifacts. Add 'test_specs' as a recognized phase to telec todo mark-phase that stamps artifacts.test_specs.produced_at. Update next-prepare skill to mark artifacts after verifying worker output, before calling telec todo prepare again.

## Symptom

prepare state machine uses filesystem heuristics to detect artifact existence instead of artifact lifecycle stamps. Three locations: (1) _prepare_step_test_spec_build uses \_has_test_spec_artifacts which globs worktree for any test_\*.py containing the string 'xfail' — wrong because all files from main are in the worktree and any pre-existing test file mentioning xfail triggers a false positive; (2) plan drafting step uses check_file_has_content for implementation-plan.md; (3) requirements steps use check_file_has_content for requirements.md. Fix: replace all three with artifact stamp checks (state['artifacts'][key]['produced_at'] non-empty). Add 'test_specs' to DEFAULT_STATE.artifacts. Add 'test_specs' as a recognized phase to telec todo mark-phase that stamps artifacts.test_specs.produced_at. Update next-prepare skill to mark artifacts after verifying worker output, before calling telec todo prepare again.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

Three filesystem heuristics in the prepare state machine trigger false positives when files from main exist in the worktree:

1. `_prepare_step_test_spec_build` (prepare*steps.py:241) — calls `_has_test_spec_artifacts` which globs `trees/{slug}/\*\*test*\*.py` for any file containing the string "xfail". Any pre-existing test file from main that mentions xfail (e.g. tests for existing features) triggers a false positive, causing the machine to loop to TEST_SPEC_REVIEW before specs are actually built.

2. `_prepare_step_input_assessment` and `_prepare_step_triangulation` (prepare_steps.py:47, 81) — call `check_file_has_content(cwd, "todos/{slug}/requirements.md")`. Since main's requirements.md is present in the worktree, this returns True and the machine skips discovery, looping directly to REQUIREMENTS_REVIEW.

3. `_prepare_step_plan_drafting` (prepare_steps.py:352) — calls `check_file_has_content(cwd, "todos/{slug}/implementation-plan.md")`. Same issue: main's plan file causes a false positive skip to PLAN_REVIEW.

4. `_derive_prepare_phase` (prepare_events.py:119) — the phase deriver uses `_has_test_spec_artifacts` for test_specs detection without applying the ghost artifact protection already in place for requirements and implementation_plan.

Root pattern: the v2 ghost artifact protection (`_is_artifact_produced_v2` check after `check_file_has_content`) was applied to requirements and plan in `_derive_prepare_phase` but was never applied in the step functions, and was never applied to test_specs in either location.

`DEFAULT_STATE["artifacts"]` also lacked a `test_specs` entry, meaning deep-merge couldn't populate it and `_is_artifact_produced_v2` would always find a missing dict key.

## Root Cause

The v2 ghost artifact protection pattern (`_is_artifact_produced_v2(state, key)` after filesystem check) was applied in `_derive_prepare_phase` for requirements and implementation_plan but was missing in all three step functions, and was never applied to test_specs in any location. Additionally, `test_specs` was absent from `DEFAULT_STATE["artifacts"]`, so the deep-merge mechanism couldn't populate the key and any v2 check for it always found an empty dict.

## Fix Applied

1. **`_types.py`**: Added `test_specs` to `DEFAULT_STATE["artifacts"]` so deep-merge populates the key and `_is_artifact_produced_v2` can check it.

2. **`prepare_events.py`** (`_derive_prepare_phase`): Applied ghost artifact protection to `_has_test_spec_artifacts` result — if files exist but `test_specs.produced_at` is empty in v2, treat as not produced.

3. **`prepare_steps.py`** (three step functions): Applied ghost artifact protection in `_prepare_step_input_assessment`, `_prepare_step_triangulation`, and `_prepare_step_test_spec_build`. Added same protection to `_prepare_step_plan_drafting`. Imported `_is_artifact_produced_v2` from `prepare_events`.

4. **`state_io.py`**: Added `mark_prepare_artifact(cwd, slug, artifact_key)` function and `_PREPARE_ARTIFACT_PHASES = ("test_specs",)` constant to enable lifecycle stamping for directory-backed artifacts (no single file to hash).

5. **`core.py`**: Re-exported `mark_prepare_artifact` and `_PREPARE_ARTIFACT_PHASES` for use by the API route.

6. **`todo_routes.py`**: Added "artifact stamp phases" branch in `/mark-phase` handler that calls `mark_prepare_artifact` when `phase in _PREPARE_ARTIFACT_PHASES`.

7. **`tool_commands/todo.py`**: Updated docstring to document `test_specs` as a recognized phase with example.

8. **Tests**: Added 6 reproduction tests (all were RED before the fix): ghost test_specs in step function, ghost requirements in input_assessment and triangulation steps, ghost plan in plan_drafting step, ghost test_specs in `_derive_prepare_phase`, and `mark_prepare_artifact` stamping. Updated existing `test_plan_with_missing_referenced_paths_returns_redraft` to set `implementation_plan.produced_at` (reflecting that a previously produced plan was re-queued for redraft due to missing paths). Updated `test_derive_prepare_phase_routes_to_plan_drafting_after_specs_are_approved` to include `test_specs.produced_at`.
