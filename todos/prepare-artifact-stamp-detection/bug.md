# Bug: prepare state machine uses filesystem heuristics to detect artifact existence instead of artifact lifecycle stamps. Three locations: (1) _prepare_step_test_spec_build uses _has_test_spec_artifacts which globs worktree for any test_*.py containing the string 'xfail' — wrong because all files from main are in the worktree and any pre-existing test file mentioning xfail triggers a false positive; (2) plan drafting step uses check_file_has_content for implementation-plan.md; (3) requirements steps use check_file_has_content for requirements.md. Fix: replace all three with artifact stamp checks (state['artifacts'][key]['produced_at'] non-empty). Add 'test_specs' to DEFAULT_STATE.artifacts. Add 'test_specs' as a recognized phase to telec todo mark-phase that stamps artifacts.test_specs.produced_at. Update next-prepare skill to mark artifacts after verifying worker output, before calling telec todo prepare again.

## Symptom

prepare state machine uses filesystem heuristics to detect artifact existence instead of artifact lifecycle stamps. Three locations: (1) _prepare_step_test_spec_build uses _has_test_spec_artifacts which globs worktree for any test_*.py containing the string 'xfail' — wrong because all files from main are in the worktree and any pre-existing test file mentioning xfail triggers a false positive; (2) plan drafting step uses check_file_has_content for implementation-plan.md; (3) requirements steps use check_file_has_content for requirements.md. Fix: replace all three with artifact stamp checks (state['artifacts'][key]['produced_at'] non-empty). Add 'test_specs' to DEFAULT_STATE.artifacts. Add 'test_specs' as a recognized phase to telec todo mark-phase that stamps artifacts.test_specs.produced_at. Update next-prepare skill to mark artifacts after verifying worker output, before calling telec todo prepare again.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
