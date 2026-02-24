# Review Findings — finalize-push-guardrails

## Paradigm-Fit Assessment

- Data flow: Guardrails were implemented in boundary layers (`.githooks`, agent PATH wrappers, init/install paths) rather than core domain logic, which fits the existing adapter/boundary model.
- Component reuse: Existing install and tmux session wiring were reused (`install_hooks`, `init_flow`, `tmux_bridge`) instead of introducing parallel mechanisms.
- Pattern consistency: Finalize split and `FINALIZE_READY` gating are consistent with next-machine staged orchestration patterns.

## Manual Verification Evidence

- Ran targeted test suite for changed areas:
  - `pytest -q tests/unit/test_pre_push_guardrails.py tests/unit/test_git_wrapper_guardrails.py tests/unit/test_gh_wrapper_guardrails.py tests/unit/test_install_hooks.py tests/unit/test_next_machine_hitl.py tests/unit/test_next_machine_state_deps.py tests/unit/core/test_next_machine_deferral.py tests/unit/test_project_setup_init_flow.py tests/unit/test_tmux_bridge_tmpdir.py`
  - Result: `105 passed`.
- Reproduced wrapper behavior with concrete command traces in isolated temp repos/scripts to validate real execution paths.

## Critical

1. `git push --no-verify` main-protection bypass when no refspec is provided and push target resolves to `origin/main`.
   - Location: `teleclaude/install/wrappers/git:177`
   - Confidence: 99
   - Details: When no refspecs are present, wrapper logic only marks `target_main=1` if current branch is `main` (`if [ "$branch" = "main" ]`). It does not resolve implicit push destination (upstream/push.default). In a concrete replay with `push.default=upstream` and feature branch upstream set to `origin/main`, `git push --no-verify` from a worktree advanced remote `main` (`feature -> main`) and returned success.
   - Requirement impact: Violates `R4` (must block even with `--no-verify`) and success criteria 2/4.
   - Fix direction: Resolve effective push destination for no-refspec pushes (including upstream and push.default modes). If destination resolves to `refs/heads/main`, enforce canonical-context block.

2. `gh` wrapper runs real commands multiple times and applies merge-guard flow to non-merge commands.
   - Location: `teleclaude/install/wrappers/gh:85`, `teleclaude/install/wrappers/gh:89`, `teleclaude/install/wrappers/gh:93`, `teleclaude/install/wrappers/gh:169`
   - Confidence: 99
   - Details: Pass-through branches call `_real_gh "$@"` but do not exit. Execution continues into base-branch parsing and final `_real_gh "$@"`. Concrete replay showed `gh auth status` invoked real gh three times. Non-PR commands can therefore duplicate side effects and still run PR-view probing unexpectedly.
   - Requirement impact: Breaks command fidelity and creates high-risk duplicate execution behavior in agent sessions.
   - Fix direction: Exit immediately after each pass-through `_real_gh` call (prefer `exec`). Gate base-branch parsing strictly behind confirmed `pr merge` path.

## Important

1. Test coverage missed both critical regressions in wrapper behavior.
   - Location: `tests/unit/test_git_wrapper_guardrails.py`, `tests/unit/test_gh_wrapper_guardrails.py`
   - Confidence: 95
   - Details: Added tests cover explicit refspec paths for `git push` and `pr merge` paths for `gh`, but do not cover:
     - no-refspec push with upstream resolving to `main` (`--no-verify` bypass case),
     - non-`pr merge` gh commands executing exactly once.
   - Fix direction: Add explicit regression tests for both paths before approval.

## Suggestions

- Add a small shared parser/helper for wrapper pass-through flow to avoid control-flow drift and duplicated early-return mistakes.

## Verdict

REQUEST CHANGES

## Fixes Applied

1. Critical: `git push --no-verify` no-refspec bypass to `origin/main`
   - Fix: Extended wrapper no-refspec push resolution to account for `push.default` + upstream destination and block implicit main-targeting pushes from non-canonical contexts.
   - Commit: `d9a7777a`

2. Critical: `gh` wrapper duplicate execution on non-merge commands
   - Fix: Added immediate exits after pass-through `_real_gh` calls so non-`pr merge` commands terminate after a single real invocation.
   - Commit: `6264315f`

3. Important: missing regression coverage for implicit push/gh pass-through paths
   - Fix: Added tests for no-refspec upstream-to-main `git push --no-verify` and for non-merge `gh` commands executing exactly once.
   - Commit: `04486e1f`
