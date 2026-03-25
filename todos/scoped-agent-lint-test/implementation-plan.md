# Implementation Plan: scoped-agent-lint-test

## Overview

Create a Python helper (`tools/session_scope.py`) that detects the active agent session
and resolves which files it touched, then modify the three shell scripts (`tools/lint.sh`,
`tools/test.sh`, `tools/lint/precommit-hook.sh`) to use scoped file lists when running
inside a session.

The helper is the single reusable entry point. Shell scripts call it as a subprocess,
parse its stdout for file lists, and fall back to full-suite behavior on non-zero exit.

### Exit Code Protocol

The helper uses a three-way exit code to distinguish normal non-session usage from errors:

- **Exit 0** + file list on stdout: session detected, scoped files resolved.
- **Exit 2** + no output: no session identity file found — normal non-agent context.
  Shell scripts fall back silently.
- **Exit 3** + diagnostic on stderr: session detected but file collection failed
  (session not in DB, no transcript, empty result). Shell scripts fall back with the
  diagnostic visible.

Shell scripts treat any non-zero exit as "use full suite." The distinction between 2
and 3 controls whether stderr output is emitted.

---

## Task 1: Create `tools/session_scope.py` [x]

**What**: A standalone Python script callable from shell that resolves session-touched
files and outputs them filtered by mode.

**Why**: The session detection logic (identity file check, DB lookup, transcript parsing)
lives in Python. Shell scripts cannot access it directly. A helper script isolates
this complexity in one place so `lint.sh`, `test.sh`, and `precommit-hook.sh` all share
the same detection path — satisfying the reusability requirement without duplicating
the session infrastructure in each shell script.

**Interface**:

```
python tools/session_scope.py --mode lint|test [--project-root <path>]
```

- `--mode lint`: outputs Python files (`.py`, `.pyi`) from the touched set, one per line.
  Non-Python files (markdown, YAML, shell) are silently excluded.
- `--mode test`: maps `teleclaude/**/*.py` source files to their test companions using
  the same convention as `tools/lint/test_mapping._mirror_path` (`teleclaude/x/y.py` →
  `tests/unit/x/test_y.py`). Touched files already under `tests/` are included directly.
  Only outputs test files that exist on disk (a missing companion is silently skipped).
- `--project-root`: defaults to the repo root (derived from script location).

**Implementation details**:

1. Import `session_identity.get_session_id()` for session detection.
2. Import `todo_scaffold._collect_session_touched_files()` for file collection.
   This is a private function, but the requirements mandate using it as-is.
3. Implement the source-to-test mapping inline, matching the convention in
   `tools/lint/test_mapping._mirror_path`. The logic is a 5-line string transform
   (`teleclaude/` prefix → `tests/unit/` prefix, `name.py` → `test_name.py`). Importing
   from `test_mapping.py` would add fragile cross-script coupling for no benefit.
4. All error paths go through the exit code protocol above. No exceptions leak to the
   caller.

**Verification**:

- Test spec delivered: `tests/unit/tools/test_session_scope.py` with `pytestmark = pytest.mark.xfail`.
  The builder removes the xfail marker once all tests pass. Tests cover:
  - `test_script_exists` — script is present on disk.
  - `test_no_session_exits_2_with_empty_stdout` — no identity file → exit 2, empty stdout.
  - `test_lint_mode_excludes_non_python_files` — .md/.yaml/.sh files absent from lint output.
  - `test_test_mode_maps_source_files_to_companions` — `teleclaude/x/y.py` → `tests/unit/x/test_y.py`.
  - `test_test_mode_includes_touched_test_files_directly` — test-tree files included as-is.
  - `test_collection_failure_exits_3_with_stderr_diagnostic` — error path → exit 3, non-empty stderr.
  - `test_missing_companion_is_silently_skipped` — non-existent companions absent from output.
- Pre-commit hooks pass.

---

## Task 2: Modify `tools/lint.sh` for session-aware scoping [x]

**What**: After venv detection, attempt session-scoped file resolution. If scoped files
are available, pass them to ruff, ruff format, pyright, mypy, and pylint instead of
the full directory targets.

**Why**: This is where `make lint` dispatches — the primary entry point for full lint
runs. Without this change, agents run all lint tools against the entire codebase even
when they touched 3 files. The session scope helper provides the file list; this script
applies it to each tool's invocation.

**Changes**:

1. After the venv detection block (after line 25), add a session-scope detection block.
   Use command substitution to capture stdout from the helper; let stderr pass through
   to the terminal for diagnostics. Check the exit code to decide scoped vs. full suite.

2. For **ruff check** (via `ruff_safe.py`): if `SCOPED_FILES` is set, pass the scoped
   files instead of `$dirs`. `ruff_safe.py` already handles file arguments — it filters
   non-Python targets and passes the rest to ruff.

3. For **ruff format**: if scoped, pass scoped files instead of `$dirs`.

4. For **pyright**: if scoped, pass scoped files as arguments (`$PYRIGHT $SCOPED_FILES`).
   Pyright accepts file paths and only reports diagnostics for those files while still
   using the full project for type resolution. Subject to verification in Task 5.

5. For **mypy**: if scoped, pass scoped files as arguments (`$MYPY $SCOPED_FILES`).
   Same verification caveat as pyright. Subject to verification in Task 5.

6. For **pylint**: if scoped, pass scoped files instead of `teleclaude`.

7. **Guardrails, markdown validation, resource validation**: unchanged. These are fast,
   project-global checks that the requirements explicitly exclude from scoping.

**Verification**:

- Test spec: `tests/unit/tools/test_shell_scoping.py::TestLintShWiring` makes GREEN:
  - `test_calls_session_scope_with_mode_lint` — lint.sh contains session_scope.py call.
  - `test_falls_back_to_full_suite_on_no_session` — no session → clean exit, no scoping.
  - `test_does_not_scope_guardrails_or_markdown` — guardrails runs before scope detection.
  - `TestExitProtocolHandling::test_lint_sh_falls_back_silently_on_exit_2` — exit 2 silent.
- Pre-commit hooks pass.

---

## Task 3: Modify `tools/test.sh` for session-aware scoping [x]

**What**: After venv activation and env setup, attempt session-scoped test file
resolution. If scoped files are available, pass them to pytest instead of the full
`tests/unit tests/integration` directories.

**Why**: Agents run the full test suite (16s+) even when they touched 3 files. The
session scope helper maps touched source files to their test companions. Running only
those companions is both faster and more focused.

**Changes**:

1. After the env variable exports (after line 29), add session-scope detection. Since
   test.sh uses `. "${VENV_ACTIVATE}"` rather than defining `$RUN`, use the venv python
   directly: `"${REPO_ROOT}/.venv/bin/python"` to invoke the helper.

2. In the pytest invocation: if scoped test files are available, pass them to pytest
   instead of `tests/unit tests/integration`. Apply to both the normal and `--cov`
   branches.

3. The existing guard for a missing test suite (lines 11-14) stays before session
   detection — if there's no test suite at all, skip regardless.

**Verification**:

- Test spec: `tests/unit/tools/test_shell_scoping.py::TestTestShWiring` makes GREEN:
  - `test_calls_session_scope_with_mode_test` — test.sh contains session_scope.py call.
  - `test_passes_companion_files_to_pytest_when_scoped` — scoped variable used in pytest invocation.
  - `test_cov_branch_also_uses_scoped_files` — --cov branch applies same scoping.
  - `test_early_exit_guard_precedes_session_detection` — early-exit guard comes first.
  - `TestExitProtocolHandling::test_test_sh_falls_back_silently_on_exit_2` — exit 2 silent.
- Pre-commit hooks pass.

---

## Task 4: Modify `tools/lint/precommit-hook.sh` for session-aware scoping [x]

**What**: In the `parallel-typecheck` component, scope pyright and mypy to
session-touched files when running inside an agent session.

**Why**: The pre-commit hook's `parallel-typecheck` runs pyright and mypy against the
full project — the slowest pre-commit step. Session scoping reduces it to only the
files the agent touched. Ruff-check already receives staged files from pre-commit.
Pylint already scopes to staged files via `git diff --cached`.

**Changes**:

1. At the top of the script (after venv detection), add session-scope detection using
   the same pattern as lint.sh — call `session_scope.py --mode lint` and capture the
   result.

2. In the `parallel-typecheck` case:
   - If session-scoped files are available, pass them to pyright and mypy as arguments.
   - Pylint: no change — it already uses `git diff --cached` for staged-file scoping.
     Broadening pylint to session scope is not supported by the requirements and could
     block commits on files edited earlier in the session but not staged.

3. The standalone `pyright` and `mypy` cases: scope them the same way when session
   files are available.

4. Other components (`guardrails`, `ruff-check`, `markdown`) unchanged — they either
   already receive file arguments from pre-commit or are fast/global.

**Verification**:

- Test spec: `tests/unit/tools/test_shell_scoping.py::TestPrecommitHookWiring` makes GREEN:
  - `test_calls_session_scope_with_mode_lint` — hook contains session_scope.py call.
  - `test_pylint_not_scoped_to_session` — pylint retains staged-file git diff --cached scoping.
  - `test_parallel_typecheck_pyright_uses_scoped_files` — scoped variable in parallel-typecheck.
  - `test_guardrails_and_ruff_check_unchanged` — guardrails and ruff-check components intact.
- Pre-commit hooks pass inside and outside agent sessions.

---

## Task 5: Verify type checker file-scoped behavior [x]

**What**: Empirically verify that pyright and mypy produce equivalent error reports
when invoked with file arguments vs. full-project invocation, for the subset of scoped
files.

**Why**: Both tools use whole-program analysis. File-scoped invocation might miss
cross-module errors or produce false positives if the project configuration interacts
badly with explicit file arguments. The requirements flag this as a risk that the
builder must investigate.

**Steps**:

1. Pick 3-5 source files with known cross-module type dependencies.
2. Run `pyright` (full project) and capture errors for those files.
3. Run `pyright file1.py file2.py ...` and capture errors.
4. Compare. Document any differences.
5. Repeat for mypy.
6. If file-scoped invocation produces false positives or misses real errors, document
   the limitation and fall back to full-project invocation for that tool (add a comment
   in the script explaining why).

**Verification**:

- Builder documents findings in commit message or code comment.
- If a tool cannot be safely scoped, the fallback is explicit and justified in code.

---

## Task 6: Update and validate `demo.md` [x]

**What**: Review `todos/scoped-agent-lint-test/demo.md` against the delivered implementation
and update any steps, output descriptions, or validation commands that differ from the
actual behavior.

**Why**: `demo.md` was drafted before implementation. The builder holds ground-truth
knowledge about the real output format (scoping messages, tool invocation flags, timing
characteristics). Without a final review pass the demo may misrepresent the feature,
which fails the review-awareness requirement for demo-lane coverage. This also satisfies
the DoD documentation gate.

**Steps**:

1. Run each validation command in `demo.md` against the implemented behavior and verify
   the described output matches reality.
2. Update any step descriptions, expected output, or command flags that diverged during
   implementation.
3. Confirm the five guided presentation steps reflect the actual session-scoped behavior
   (non-session fallback, helper direct invocation, scoped lint, scoped test, error
   fallback).

**Verification**:

- All `demo.md` validation commands pass without modification.
- `telec todo demo validate scoped-agent-lint-test` reports no errors.

---

## Referenced Paths

**Created**:

- `tools/session_scope.py`
- `tests/unit/tools/test_session_scope.py`

**Modified**:

- `tools/lint.sh`
- `tools/test.sh`
- `tools/lint/precommit-hook.sh`

**Read (not modified)**:

- `teleclaude/session_identity.py` — session ID resolution
- `teleclaude/todo_scaffold.py` — `_collect_session_touched_files()`
- `tools/lint/test_mapping.py` — `_mirror_path()` convention reference
- `tools/lint/ruff_safe.py` — already handles file arguments
- `.pre-commit-config.yaml` — hook configuration (unchanged)
- `Makefile` — make targets (unchanged, they call the shell scripts)
