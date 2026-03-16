# Review Findings: fix-ci-release-credentials

Ad-hoc review (via from-main). Scope, demo, and completeness lanes were skipped per the review procedure for `telec todo from-main` submissions.

## Resolved During Review

- Updated the `telec todo from-main` help surface to advertise the new `--paths` option in [surface.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/teleclaude/cli/telec/surface.py#L534).
- Added regression coverage for marker-based artifacts and `--paths` scoping in [test_todo_from_main.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/tests/unit/test_todo_from_main.py#L95).
- Added build-gate coverage for `from-main` marker acceptance in [test_build_gates.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/tests/unit/core/next_machine/test_build_gates.py#L39).
- Added readiness/worktree-state coverage in [test_slug_resolution.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/tests/unit/core/next_machine/test_slug_resolution.py#L101) and [test_work.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/tests/unit/core/next_machine/test_work.py#L92).

## Code Lane

No unresolved findings after direct diff review and the reviewer-side test/doc fixes above.

## Paradigm Lane

No unresolved findings. The change continues to route `from-main` handling through the existing scaffold/worktree/state-machine seams instead of introducing a parallel flow.

## Principles Lane

No unresolved findings. I did not find unjustified fallback paths, adapter leakage into core boundaries, or new responsibility sprawl in the touched production code.

## Security Lane

No unresolved findings. The diff introduces no hardcoded credentials, no credential logging, and no new shell interpolation of untrusted input.

## Tests Lane

No unresolved findings after remediation. Targeted regression coverage now pins the new marker-based artifact flow, `--paths` filtering, the `build == complete` readiness branch, and the worktree-state readiness lookup.

Verification:

- `pytest -q tests/unit/test_todo_from_main.py tests/unit/core/next_machine/test_build_gates.py tests/unit/core/next_machine/test_slug_resolution.py tests/unit/core/next_machine/test_work.py`

## Errors Lane

No unresolved findings. I did not find new silent-failure paths beyond the scoped behavior now covered by tests.

## Logging Lane

No unresolved findings. The touched Python code does not add or change structured logging behavior.

## Types Lane

No unresolved findings. The touched Python code remains explicitly typed, and the new tests use existing typed patterns.

## Comments Lane

No unresolved findings. The changed comments/docstrings are consistent with the current behavior.

## Docs Lane

No unresolved findings after remediation. The CLI surface now documents `--paths` alongside the handler implementation in [surface.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/teleclaude/cli/telec/surface.py#L534) and [todo.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/teleclaude/cli/telec/handlers/todo.py#L400).

## Simplify Lane

No additional simplification opportunities stood out after the localized review fixes.

## Manual Verification

- Ran `bash -n bin/setup-runner.sh`.
- Did not execute [setup-runner.sh](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/bin/setup-runner.sh) end-to-end because it mutates the local LaunchAgent configuration and depends on real macOS Keychain credentials.

## Suggestions

- Validate [setup-runner.sh](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/fix-ci-release-credentials/bin/setup-runner.sh) on a disposable macOS runner before merge so the LaunchAgent patch and credential checks are exercised against real runner state.

## Why No Issues

- Paradigm fit: checked the existing `todo_scaffold` -> worktree -> next-machine path and verified the remediation stayed inside that flow rather than adding a second control path.
- Requirements fit: validated the ad-hoc requirement text against the actual delivery, then closed the review-only gaps around `--paths` discoverability and missing regression coverage.
- Duplication check: reviewed the added tests for overlap and kept each one pinned to a distinct behavior branch.
- Security review: checked the shell script and Python diff for secrets, credential logging, and unsafe command construction.

## Verdict

APPROVE
