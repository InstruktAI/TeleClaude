# Context-Aware Checkpoint (Phase 2) — Implementation Plan

## Approach

Enhance `_maybe_checkpoint_output()` in `receiver.py` to inspect `git diff --name-only HEAD`, run pytest when Python files changed, compose a context-specific checkpoint message, and add an uncommitted-changes gate on the escape hatch path. All logic stays in the receiver (fresh process per hook call — no daemon changes needed).

## Files to Change

| File                                                    | Change                                                                                   |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `teleclaude/hooks/receiver.py`                          | Add git diff inspection, pytest execution, message composition, uncommitted-changes gate |
| `teleclaude/constants.py`                               | Add constants for pytest timeout, file category patterns, gated file extensions          |
| `tests/unit/test_checkpoint_hook.py`                    | Add tests for all new behavior                                                           |
| `docs/project/design/architecture/checkpoint-system.md` | Update to document Phase 2 context-aware flow                                            |

## Task Sequence

### Task 1: Add constants

Add to `teleclaude/constants.py`:

- `CHECKPOINT_PYTEST_TIMEOUT_S = 30` — max seconds for test subprocess
- `CHECKPOINT_GATED_EXTENSIONS` — set of file extensions that trigger the uncommitted-changes gate (`.py`, `.yml` for config)
- File category patterns as a data structure (list of tuples: category name, include patterns, exclude patterns, instruction template)

**Verify:** Import succeeds, no syntax errors.

### Task 2: Add git diff + file categorization helpers

Add to `receiver.py`:

- `_get_uncommitted_files() -> list[str]` — runs `git diff --name-only HEAD` via subprocess, returns list of changed file paths. Returns empty list on error (fail-open).
- `_categorize_files(files: list[str]) -> list[tuple[str, str]]` — maps file list against category patterns, returns deduplicated list of (category, instruction) tuples.

**Verify:** Unit tests for categorization with various file lists.

### Task 3: Add pytest execution helper

Add to `receiver.py`:

- `_run_pytest() -> tuple[bool, str]` — runs `pytest tests/unit/ -x -q` via subprocess with `CHECKPOINT_PYTEST_TIMEOUT_S` timeout. Returns (passed: bool, output: str). Returns (True, "") on timeout or error (fail-open).

**Verify:** Unit tests mocking subprocess.

### Task 4: Compose context-aware checkpoint message

Modify the checkpoint message composition in `_maybe_checkpoint_output()`:

1. Call `_get_uncommitted_files()` to get changed files
2. If any `.py` files in the list: call `_run_pytest()`, capture results
3. Call `_categorize_files()` to get action instructions
4. Build structured message:
   - If tests failed: "Checkpoint — Tests: FAILED\n`\n{output}\n`\nFix the failing tests before proceeding."
   - If tests passed with actions: "Checkpoint — Tests: {count} passed ({time})\n\nChanged: {files}\n\nRequired:\n- {actions}\n\nThen capture anything worth keeping. If everything is clean, do not respond."
   - If no code changes: "Checkpoint — No code changes detected.\n\nCapture anything worth keeping (memories, bugs, ideas). If everything is clean, do not respond."
5. Use this composed message instead of the generic `CHECKPOINT_MESSAGE` constant

**Verify:** End-to-end unit tests with mocked git/pytest subprocesses checking full message output.

### Task 5: Uncommitted changes gate on escape hatch

Modify the `stop_hook_active` escape hatch path in `_maybe_checkpoint_output()`:

1. When `stop_hook_active` is True, call `_get_uncommitted_files()`
2. Check if any files match `CHECKPOINT_GATED_EXTENSIONS`
3. If gated files exist: return blocking JSON with "You have uncommitted code changes. Commit your work before stopping.\n\nChanged: {files}"
4. If no gated files (only docs/ideas/todos): return None (pass through)

**Verify:** Unit tests for gate behavior with various file states.

### Task 6: Update tests

Add comprehensive tests to `test_checkpoint_hook.py`:

- `test_git_diff_empty_returns_generic_message` — no changes → capture-only
- `test_git_diff_py_files_runs_pytest` — Python files trigger test execution
- `test_pytest_pass_includes_results` — passing tests show count + time
- `test_pytest_fail_shows_output` — failing tests show failure output
- `test_daemon_code_change_instructs_restart` — `teleclaude/*.py` → "make restart"
- `test_tui_code_change_instructs_sigusr2` — `teleclaude/cli/tui/*.py` → SIGUSR2
- `test_hook_code_no_instruction` — `receiver.py` → no follow-up action
- `test_agent_artifacts_instructs_restart` — `.claude/agents/**` → agent-restart
- `test_config_change_instructs_restart` — `config.yml` → "make restart"
- `test_escape_hatch_blocks_uncommitted_code` — `stop_hook_active` + uncommitted `.py` → block
- `test_escape_hatch_passes_clean_state` — `stop_hook_active` + no gated files → pass through
- `test_escape_hatch_passes_docs_only` — `stop_hook_active` + only markdown → pass through
- `test_git_diff_failure_is_fail_open` — subprocess error → generic checkpoint
- `test_pytest_timeout_is_fail_open` — timeout → treat as passed

**Verify:** `pytest tests/unit/test_checkpoint_hook.py -v` all green.

### Task 7: Update design doc

Update `docs/project/design/architecture/checkpoint-system.md`:

- Add Phase 2 context-aware flow to Primary flows section
- Add git diff + pytest execution to Inputs
- Add context-aware message format to Outputs
- Add uncommitted-changes gate to Invariants
- Update failure modes table with new scenarios (git unavailable, pytest timeout, subprocess errors)

**Verify:** `telec sync` succeeds.

## Risks and Assumptions

- **Assumption:** `git` is available on PATH in the hook receiver's subprocess environment. If not, fail-open returns generic checkpoint.
- **Assumption:** `pytest` is available via the project's venv. The receiver imports from the project already, so venv activation is inherited.
- **Risk:** pytest execution adds ~10s latency. Acceptable because the receiver is a fresh process (no daemon blocking) and the agent just waits slightly longer.
- **Risk:** Large test suites could exceed the 30s timeout. Mitigated by the timeout guard and fail-open behavior.
- **Risk:** git diff might include staged but not committed files — `git diff --name-only HEAD` includes both staged and unstaged changes relative to HEAD, which is the correct behavior for "uncommitted work."
