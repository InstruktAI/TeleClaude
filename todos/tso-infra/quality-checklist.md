# Quality Checklist: tso-infra

## Build Gates (Builder)

- [x] All tasks in `implementation-plan.md` are `[x]`
- [x] `make test` passes (≥3338 tests, 0 failures) — 3338 passed, 6 skipped
- [x] `make lint` passes — Pre-existing issue in teleclaude/core/next_machine/core.py (out of scope); all new files pass ruff/pyright clean
- [x] `python tools/lint/test_mapping.py` exits 1 with gap list (expected at this stage)
- [x] `make check-test-mapping` target exists and runs
- [x] `tests/unit/` has all missing module directories, each with conftest.py stub
- [x] `pyproject.toml` has `[tool.test-mapping].exclude` with 2 legitimate exclusions (audited from 8)
- [x] `docs/global/software-development/policy/test-structure.md` exists with policy content
- [x] All new Python files pass `ruff check` and `pyright`
- [x] No `teleclaude/` source files modified
- [x] `tso-infra` branch exists in worktree

## DoD Section 6 — Documentation

- [x] Test structure policy doc snippet created (`docs/global/software-development/policy/test-structure.md`)
- [x] Doc snippet covers: 1:1 mapping rule, pyproject.toml exemption format, exemption validity criteria, CI enforcement, behavioral test contract standards
- [x] Snippet has proper frontmatter (id, type, scope, description)

## Build Verification Notes

All 9 tasks completed. Directory scaffold complete (~47 conftest stubs across all
scaffold directories ensuring git tracking). CI enforcement script
(`tools/lint/test_mapping.py`) reads exclusions from `pyproject.toml` using `tomllib`.
9 unit tests in `test_lint_test_mapping.py`. Exemption audit reduced exclusions from 8
(in stale `tests/ignored.md`) to 2 legitimate files (`metadata.py`, `logging_config.py`).
Test structure policy doc snippet created for module workers.

`tests/constants.py` deleted (dead code — imported by zero files).
`tests/ignored.md` remains as human documentation but is no longer machine-parsed.
