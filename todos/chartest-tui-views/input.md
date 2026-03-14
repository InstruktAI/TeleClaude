# Input: chartest-tui-views

Characterization tests for TUI views and widgets.

**Recommended agent:** codex

## Source files to characterize

- `teleclaude/cli/tui/views/_config_constants.py`
- `teleclaude/cli/tui/views/base.py`
- `teleclaude/cli/tui/views/config.py`
- `teleclaude/cli/tui/views/config_editing.py`
- `teleclaude/cli/tui/views/config_render.py`
- `teleclaude/cli/tui/views/interaction.py`
- `teleclaude/cli/tui/views/jobs.py`
- `teleclaude/cli/tui/views/preparation.py`
- `teleclaude/cli/tui/views/preparation_actions.py`
- `teleclaude/cli/tui/views/sessions.py`
- `teleclaude/cli/tui/views/sessions_actions.py`
- `teleclaude/cli/tui/views/sessions_highlights.py`
- `teleclaude/cli/tui/widgets/activity_row.py`
- `teleclaude/cli/tui/widgets/agent_badge.py`
- `teleclaude/cli/tui/widgets/agent_status.py`
- `teleclaude/cli/tui/widgets/banner.py`
- `teleclaude/cli/tui/widgets/box_tab_bar.py`
- `teleclaude/cli/tui/widgets/computer_header.py`
- `teleclaude/cli/tui/widgets/group_separator.py`
- `teleclaude/cli/tui/widgets/job_row.py`
- `teleclaude/cli/tui/widgets/modals.py`
- `teleclaude/cli/tui/widgets/project_header.py`
- `teleclaude/cli/tui/widgets/status_bar.py`
- `teleclaude/cli/tui/widgets/telec_footer.py`
- `teleclaude/cli/tui/widgets/todo_file_row.py`
- `teleclaude/cli/tui/widgets/todo_row.py`

## What

Write characterization tests for every source file listed above, following the
OBSERVE-ASSERT-VERIFY cycle. Each source file gets a corresponding test file
under `tests/unit/` mirroring the source directory structure.

## Acceptance criteria

- Every listed source file has a corresponding test file (or documented exemption)
- Tests pin actual behavior at public boundaries
- All tests pass on the current codebase
- No string assertions on human-facing text
- Max 5 mock patches per test
- Each test has a descriptive name that reads as a behavioral specification
- All existing tests still pass (no regressions)
- Lint and type checks pass

## Methodology: Characterization Testing (OBSERVE-ASSERT-VERIFY)

This is a **characterization testing** task, not TDD. The code already exists and works.
The goal is to pin current behavior as a safety net for future refactoring.

### Cycle per source file:

1. **OBSERVE** — Read the source file. Identify public functions/methods/classes that other
   modules call. Run representative inputs through the code mentally (or via quick test runs).
   Record actual return values, side effects, exceptions, and state changes.

2. **ASSERT** — Write tests that assert the observed behavior at public boundaries.
   The tests will pass immediately — this is expected and correct for characterization.
   Each test should have a descriptive name that serves as a behavioral specification.

3. **VERIFY** — For each test, mentally verify: if I introduced a deliberate fault in the
   production code (wrong return value, missing condition, swapped branch), would this test
   catch it? If not, the test is too shallow — strengthen or discard.

### Rules (from testing policy):

- Test at **public API boundaries only** — functions/methods other modules actually call
- **Behavioral contracts**, not implementation details — no mocking internals
- **No string assertions** on human-facing text (messages, CLI output, error prose)
- **Max 5 mock patches per test** — more indicates too many dependencies
- **One clear expectation per test**
- Mock at **architectural boundaries** (I/O, DB, network, external services)
- Every test must answer: **"What real bug in OUR code would this catch?"**
- Follow **1:1 source-to-test mapping**: `teleclaude/foo/bar.py` → `tests/unit/foo/test_bar.py`
- Use **pytest** with standard fixtures. Check existing `conftest.py` files for patterns.
- Skip files with genuinely no testable logic (pure re-exports, empty wrappers). Document why.

### Anti-patterns to avoid:

- Testing third-party library behavior (YAML round-trips, JSON serialization)
- Testing informational side-effects (log entries, metrics) unless the system depends on them
- Tautological assertions (asserting literals match their own source)
- Truthy-check assertions (`assert value` instead of asserting specific expected values)
- Over-mocking — if you need 6+ mocks, the code may need refactoring (document as tech debt)
