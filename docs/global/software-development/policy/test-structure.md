---
description: '1:1 source-to-test mapping, directory conventions, exemptions, and CI enforcement.'
id: 'software-development/policy/test-structure'
scope: 'domain'
type: 'policy'
---

# Test Structure — Policy

## Rules

1. Every source file under `teleclaude/` must have a corresponding test file under `tests/unit/` following the mirror convention: `teleclaude/x/y.py` → `tests/unit/x/test_y.py`.
2. Exemptions are declared in `pyproject.toml` under `[tool.test-mapping].exclude` as an explicit list of repo-root-relative paths.
3. Exemptions are valid only for files with genuinely no testable logic (pure type definitions, configuration delegation, thin wrappers). Files containing functions with branching, validation, parsing, or business rules must have tests regardless of their primary purpose.
4. The CI enforcement script `tools/lint/test_mapping.py` checks the mapping and exits nonzero when gaps exist. Run via `make check-test-mapping`.
5. `make check-test-mapping` is opt-in during the test-suite-overhaul migration period. It will be added to `make lint` once all module workers complete their migration.
6. New source files must have a corresponding test file before merge. The test file may start as a stub, but the mapping must exist.
7. Tests are behavioral contracts, not implementation snapshots:
   - Assert behavior and outcomes, not internal state or call counts.
   - No string assertions on any human-facing text — composed messages, CLI output, formatted reports, notifications, error prose, agent artifacts, documentation. Assert on the data structure that produces the output, not the rendered string. Exception: execution-significant text (parser tokens, schema keys, command names, protocol markers).
   - Maximum 5 mock patches per test. More indicates the code under test has too many dependencies.
   - Each test function must have a docstring or descriptive name that serves as a behavioral specification.

## Rationale

- 1:1 mapping makes coverage gaps immediately visible and prevents orphan tests.
- `pyproject.toml` follows the standard Python tooling convention (ruff, pytest, mypy, coverage all live there).
- Behavioral contracts survive refactoring; implementation-detail tests create drag.

## Scope

- Applies to all source files under `teleclaude/` and all test files under `tests/unit/`.

## Enforcement

- `tools/lint/test_mapping.py` runs in CI and reports gaps.
- Code review verifies new source files have corresponding test files.

## Exceptions

- Files listed in `pyproject.toml` `[tool.test-mapping].exclude` with a comment explaining why.
