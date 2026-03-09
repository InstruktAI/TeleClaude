# Review Findings: tso-infra

**Verdict: APPROVE**
**Date:** 2026-03-09
**Review round:** 1

---

## Critical

None.

## Important

None.

## Suggestions

None unresolved. Three findings were auto-remediated (see below).

---

## Resolved During Review

### S1 — Ruff import sorting error in `tools/lint/test_mapping.py` (auto-remediated)

**Severity:** Important (quality checklist claimed lint passes; it didn't)
**Location:** `tools/lint/test_mapping.py:1-6`
**Principle:** Linting Requirements
**Issue:** `ruff check` reported I001 (unsorted import block). `tomllib` was in the wrong position — stdlib imports must be grouped after `from __future__`.
**Fix:** Ran `ruff check --fix` — `tomllib` moved to stdlib group. `ruff check` now passes clean.

### S2 — `demos/tso-infra/demo.md` stale content (auto-remediated)

**Severity:** Critical (demo blocks reference nonexistent file `tests/constants.py`)
**Location:** `demos/tso-infra/demo.md` — Sections 6, 7, 8
**Principle:** Fail Fast (demo validation)
**Issue:** The `demos/` copy was not synced after the builder updated `todos/tso-infra/demo.md`. Three problems:
- Section 6 tested `from tests.constants import TEST_VERSION` — `tests/constants.py` doesn't exist (was deleted during build).
- Section 7 included `tests/constants.py` in the ruff/pyright check commands.
- Section 8 expected "6 passed" but there are 9 tests.
- Intro mentioned "shared constants" which is not a deliverable.
**Fix:** Replaced `demos/tso-infra/demo.md` with the corrected `todos/tso-infra/demo.md` content. All 8 sections now reference real files, commands, and correct expected output.

### S3 — Previous review-findings.md had wrong scope verification (auto-remediated)

**Severity:** Important (stale review artifact)
**Location:** `todos/tso-infra/review-findings.md`
**Issue:** The prior review-findings referenced wrong requirements: R5 described `ignored.md` regex parsing (actual R5 is `pyproject.toml` exemptions), R6 described `tests/constants.py` shared constants (actual R6 is test structure policy doc). This review replaces it entirely.
**Fix:** Complete rewrite of review-findings.md with accurate scope verification.

---

## Scope Verification

All 6 requirements fully delivered:

| Requirement | Evidence |
|---|---|
| R1: Feature branch | `git branch --list feat/test-suite-overhaul` confirms branch exists |
| R2: Directory scaffold | ~47 conftest stubs across all scaffold directories; existing dirs untouched |
| R3: Conftest restructure | TUI section labeled at line 98 (`# TUI Test Fixtures` — pre-existing on main); 6 module conftest stubs created for adapters, api, core, cli, hooks, memory |
| R4: CI enforcement script | `tools/lint/test_mapping.py` reads `pyproject.toml`, exits 1 with 295 gaps; `make check-test-mapping` target present; 9 unit tests pass |
| R5: `pyproject.toml` exemptions | `[tool.test-mapping].exclude` has 2 entries: `metadata.py` (pure Pydantic model) and `logging_config.py` (delegates to external lib). Both verified trivial by source inspection |
| R6: Test structure policy doc | `docs/global/software-development/policy/test-structure.md` created with proper frontmatter, covers all 5 required topics |

No gold-plating. No unrequested features. No `teleclaude/` source files modified.

## Paradigm-fit Verification

- `test_mapping.py` follows `guardrails.py` structure: pure-stdlib, `main(repo_root)`, `sys.exit()`, `__name__` entry point.
- `test_lint_test_mapping.py` uses the `importlib.util` dynamic loading pattern from `test_lint_guardrails.py`.
- Makefile `check-test-mapping` target uses `@python` consistent with existing targets.
- Conftest stubs are single-line docstrings matching existing conventions.

## Security Review

- No secrets, credentials, or tokens in any changed file.
- No log statements emitting PII.
- All file paths via `pathlib` — no injection vectors.
- No user input processing beyond local filesystem reads.

## Test Coverage

9 tests covering all public functions and branches:
- `_load_exclusions`: 2 tests (reads config; graceful on missing section)
- `_mirror_path`: 3 tests (nested, flat, top-level)
- `main`: 4 tests (gaps → exit 1, all mapped → exit 0, missing source dir → exit 2, exclusion flow)

All pass. Lint and type check clean.

## Demo Artifact

`demos/tso-infra/demo.md` — 8 sections with executable bash blocks. All commands reference real targets, flags, and files confirmed in the codebase. Synced with `todos/tso-infra/demo.md`.

## Manual Verification Evidence

- `pytest tests/unit/test_lint_test_mapping.py`: 9 passed, 0 failed
- `python tools/lint/test_mapping.py`: exits 1 with 295 unmapped files
- `ruff check tools/lint/test_mapping.py tests/unit/test_lint_test_mapping.py`: All checks passed
- `pyright tools/lint/test_mapping.py tests/unit/test_lint_test_mapping.py`: 0 errors, 0 warnings
- All scaffold directories present with conftest stubs
- `pyproject.toml` exemptions verified against source files

## Why APPROVE (Zero-finding justification)

1. **Paradigm-fit**: `test_mapping.py` follows the exact `guardrails.py` pattern (stdlib-only, `main(repo_root)`, `sys.exit`). Test file uses the `importlib.util` loading pattern from `test_lint_guardrails.py`. Makefile target follows existing conventions.
2. **Requirements met**: All 6 requirements verified with evidence (branch, directories, conftest, script, pyproject config, doc snippet). No missing functionality.
3. **Copy-paste duplication checked**: No duplicated logic across files. `_mirror_path` and `_load_exclusions` are single-point implementations.
4. **Security reviewed**: No secrets, no injection vectors, no PII in logs. Pure filesystem reads via `pathlib`.
5. **Test coverage adequate**: 9 tests covering all 3 public functions and both exit code paths. All pass deterministically.
