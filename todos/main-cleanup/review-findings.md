# Review Findings: main-cleanup

Ad-hoc review (via from-main). Scope, demo, and completeness lanes were skipped per procedure because the todo artifacts are stubs.

## Important

- `R1-F1` The worktree still fails the enforced pre-commit `typecheck` hook, so the review artifact could not be committed. The blocking output includes diff-adjacent type issues in `teleclaude/core/next_machine/state_io.py` and `teleclaude/helpers/git_repo_helper.py`, plus broader existing pyright/mypy failures in the current branch (`teleclaude/adapters/discord/*`, `teleclaude/adapters/qos/*`, related tests). Until the branch is hook-clean, this item does not meet the repository merge gate.

## Resolved During Review

- Removed touched-file lint failures in `teleclaude/core/next_machine/state_io.py`, `tests/unit/hooks/checkpoint/test__git.py`, `tests/unit/project_setup/test_git_repo.py`, and `tests/unit/test_sync.py`.
- Replaced untyped monkeypatch lambdas with typed local helpers in `tests/unit/hooks/checkpoint/test__git.py` and `tests/unit/test_sync.py` so the touched test files satisfy the repository type rules.

## Code

No findings. The only behavior change in production code is the consolidation of daemon session environment-variable names into shared constants; the remaining production diffs are import-order or redundant-cast cleanup.

## Paradigm

No findings. The daemon still owns transport-specific environment setup, and the constant extraction keeps that knowledge local instead of spreading string literals across modules.

## Principles

No findings. The changed production code does not add fallback paths, silent degradation, boundary leakage, or new multi-responsibility branches.

## Security

No findings. No secrets were added, no auth or authorization checks were weakened, and the touched subprocess and git interactions do not introduce injection risk.

## Tests

No findings. The touched behavior remains covered by targeted unit and characterization tests, and the updated tests still assert behavior rather than implementation details.

Verification run:
`pytest -q tests/unit/test_daemon_session.py tests/unit/test_sync.py tests/unit/project_setup/test_git_repo.py tests/unit/hooks/checkpoint/test__git.py`

## Errors

No findings. Error handling behavior in the changed production code is unchanged apart from replacing duplicated env-var literals with shared constants.

## Logging

No findings. The diff does not add logging regressions, debug probes, truncated identifiers, or secret-bearing log statements.

## Types

Inline remediation cleared the targeted `pyright` issues in the touched review files, but there is one unresolved finding: the repository-level `typecheck` hook still fails in this worktree.

Targeted verification run:
`pyright teleclaude/core/next_machine/state_io.py teleclaude/daemon_session.py teleclaude/constants.py teleclaude/helpers/git_repo_helper.py tests/unit/hooks/checkpoint/test__git.py tests/unit/project_setup/test_git_repo.py tests/unit/test_sync.py`

## Comments

No findings. The touched comments still match the concrete behavior in the reviewed code paths.

## Docs/Config Surface

Not triggered. The reviewed diff does not change CLI help, config keys, API surface, or other user-facing documentation contracts.

## Simplify

No findings. After the inline lint/type cleanup, there is no additional simplification worth making without turning a narrow cleanup into a broader refactor.

## Manual Verification

Not required. The reviewed diff does not introduce user-facing CLI, UI, config, or API behavior changes.

## Verdict

REQUEST CHANGES
