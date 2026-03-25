# Demo: scoped-agent-lint-test

## Validation

```bash
# Verify the helper exits cleanly outside a session (exit 2, no output)
TMPDIR=$(mktemp -d) .venv/bin/python tools/session_scope.py --mode lint; echo "exit: $?"
```

```bash
# Verify scoped lint includes companions and excludes non-Python files
.venv/bin/pytest \
  tests/unit/tools/test_session_scope.py::test_filter_lint_mode_includes_test_companion_for_teleclaude_source \
  tests/unit/tools/test_session_scope.py::test_filter_lint_mode_includes_python_source_files \
  -q
```

```bash
# Verify shell scripts route scoped helper output into lint/test commands
.venv/bin/pytest \
  tests/unit/tools/test_shell_scoping.py::TestLintShWiring::test_scoped_files_flow_to_each_lint_tool \
  tests/unit/tools/test_shell_scoping.py::TestTestShWiring::test_scoped_test_files_flow_to_pytest_in_both_branches \
  tests/unit/tools/test_shell_scoping.py::TestPrecommitHookWiring::test_parallel_typecheck_routes_scoped_files_to_pyright_and_mypy \
  -q
```

```bash
# Verify error-fallback: session identity exists but collection fails → exit 3 from helper
.venv/bin/pytest \
  tests/unit/tools/test_session_scope.py::test_collection_failure_exits_3_with_stderr_diagnostic \
  -q
```

## Guided Presentation

### Step 1: Non-session fallback (no regression)

Run the first validation block. Observe that the helper exits `2` with no output when
no session identity exists. This proves the fallback path works and existing non-agent
workflows are unaffected.

### Step 2: Helper direct invocation

Run `.venv/bin/python tools/session_scope.py --mode lint` directly. Outside a session,
it exits with code 2 and produces no output. This confirms the "no session" detection path.

Inside an agent session, the same command outputs the Python files this session touched
(one per line) and exits with code 0. Run with `--mode test` to see the companion test
file mapping.

### Step 3: Scoped lint (inside agent session)

Run the second validation block. Observe:

- The scoped helper includes the touched `teleclaude/...` source file and its mapped `tests/unit/...` companion.
- Non-Python touched files are excluded from the lint target list.

### Step 4: Scoped test (inside agent session)

Run the third validation block. Observe:

- `lint.sh` routes `$SCOPED_FILES` into ruff, pyright, mypy, and pylint.
- `test.sh` routes `$SCOPED_TEST_FILES` into both the normal and `--cov` pytest branches.
- `precommit-hook.sh` routes the same scoped file list into standalone and parallel type-check invocations.

### Step 5: Error fallback

Run the final validation block. Observe:

- The helper exits through the `exit 3` path with a non-empty diagnostic on stderr.
- The shell scripts continue to interpret that path as "fall back to full suite" rather than crash.
