# Review Findings — finalize-push-guardrails

## Paradigm-Fit Assessment

- Data flow: Main-protection logic is implemented at transport/boundary layers (`.githooks`, session-scoped wrappers, init/install paths), preserving the existing core-orchestration model.
- Component reuse: The change reuses established setup/session components (`install_hooks`, `init_flow`, `tmux_bridge`) instead of creating parallel entry points.
- Pattern consistency: Finalize remains staged in next-machine with explicit worker output gating (`FINALIZE_READY`) and orchestrator-owned apply.

## Manual Verification Evidence

- Targeted tests:
  - `pytest -q -n 1 tests/unit/test_pre_push_guardrails.py tests/unit/test_git_wrapper_guardrails.py tests/unit/test_gh_wrapper_guardrails.py tests/unit/test_install_hooks.py tests/unit/test_next_machine_hitl.py tests/unit/test_next_machine_state_deps.py tests/unit/core/test_next_machine_deferral.py tests/unit/test_project_setup_init_flow.py tests/unit/test_tmux_bridge_tmpdir.py`
  - Result: `107 passed`.
- Concrete runtime trace of wrapper dispatch:
  - `git` wrapper with PATH entries `wrapper:bin1:bin2` where first real git exits non-zero and second exits zero invoked both binaries for one command (`BIN1 status`, then `BIN2 status`).
  - `gh` wrapper shows the same behavior (`GH1 auth status`, then `GH2 auth status`).

## Critical

1. `R2-F1` Real-binary dispatch retries failed commands across PATH entries, causing duplicate execution and failure masking.
   - Location: `teleclaude/install/wrappers/git:17`, `teleclaude/install/wrappers/gh:17`
   - Confidence: 99
   - Details: `_real_git`/`_real_gh` use `[ -x ... ] && binary "$@" && return 0`. A non-zero exit does not return; the loop continues and executes the next PATH candidate (including duplicate PATH entries). This can replay side-effecting commands and convert an initial failure into apparent success.
   - Requirement impact: Violates command-fidelity expectations under `R7` (lifecycle behavior should remain intact) and creates high-risk side effects for guardrail enforcement paths.
   - Fix direction: Execute the first discovered real binary exactly once and propagate its exact exit status (`exec` preferred).

## Important

1. `R2-F2` Regression tests do not cover failing real-binary dispatch behavior in wrappers.
   - Location: `tests/unit/test_git_wrapper_guardrails.py`, `tests/unit/test_gh_wrapper_guardrails.py`
   - Confidence: 95
   - Details: Current tests cover blocked/allowed guardrail paths and a non-merge single-execution success case, but do not assert behavior when the first PATH-resolved binary returns non-zero.
   - Fix direction: Add tests that simulate multiple PATH candidates with first-command failure and assert exactly one invocation with preserved failure status.

## Verdict

REQUEST CHANGES

## Fixes Applied

- `R2-F1` (Critical): Updated `_real_git` and `_real_gh` to execute the first PATH-resolved binary exactly once and return its exact exit status, preventing retry/masking behavior. Commit: `9ca1fad8`.
- `R2-F2` (Important): Added regression tests for wrapper dispatch failure behavior to assert first-binary single invocation and preserved non-zero status for both `git` and `gh` wrappers. Commit: `9c23f9c7`.
