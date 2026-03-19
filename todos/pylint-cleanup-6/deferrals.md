# Deferrals: pylint-cleanup-6

## Deferral 1

- Scope: Repo-level lint guardrail failures outside the paths assigned to this slug.
- Why deferred: `make lint` still fails in `teleclaude/daemon_session.py`, `teleclaude/cli/session_auth.py`, `teleclaude/core/next_machine/`, and `scripts/helpers/nano_banana_helper.py`, none of which are listed in `requirements.md`.
- Evidence: `make lint` reports banned session env-var usage at those paths after the scoped lint cleanup is complete.
- Suggested outcome: NEW_TODO

## Deferral 2

- Scope: Repo-level test failures outside the paths assigned to this slug.
- Why deferred: `make test` still fails in `tests/unit/install/test_git_wrapper_permissions.py` and `tests/unit/test_todo_from_main.py`; the failing production files are outside the slug's assigned directories.
- Evidence: after repairing all regressions introduced by the scoped lint cleanup, the remaining `make test` failures are limited to those suites.
- Suggested outcome: NEW_TODO
