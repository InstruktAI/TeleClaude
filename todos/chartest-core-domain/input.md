# Input: chartest-core-domain

Characterization tests for core domain logic.

**Recommended agent:** claude

## Source files to characterize

- `teleclaude/core/activity_contract.py`
- `teleclaude/core/agent_parsers.py`
- `teleclaude/core/agents.py`
- `teleclaude/core/cache.py`
- `teleclaude/core/checkpoint_dispatch.py`
- `teleclaude/core/codex_prompt_normalization.py`
- `teleclaude/core/codex_prompt_submit.py`
- `teleclaude/core/codex_transcript.py`
- `teleclaude/core/command_mapper.py`
- `teleclaude/core/command_registry.py`
- `teleclaude/core/command_service.py`
- `teleclaude/core/dates.py`
- `teleclaude/core/db_models.py`
- `teleclaude/core/error_feedback.py`
- `teleclaude/core/event_bus.py`
- `teleclaude/core/event_guard.py`
- `teleclaude/core/events.py`
- `teleclaude/core/feature_flags.py`
- `teleclaude/core/feedback.py`
- `teleclaude/core/file_handler.py`
- `teleclaude/core/identity.py`
- `teleclaude/core/inbound_errors.py`
- `teleclaude/core/inbound_queue.py`
- `teleclaude/core/metadata.py`
- `teleclaude/core/origins.py`
- `teleclaude/core/output_poller.py`
- `teleclaude/core/parsers.py`
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/redis_utils.py`
- `teleclaude/core/roadmap.py`
- `teleclaude/core/session_launcher.py`
- `teleclaude/core/session_listeners.py`
- `teleclaude/core/session_utils.py`
- `teleclaude/core/status_contract.py`
- `teleclaude/core/summarizer.py`
- `teleclaude/core/system_stats.py`
- `teleclaude/core/task_registry.py`
- `teleclaude/core/tmux_delivery.py`
- `teleclaude/core/tmux_io.py`
- `teleclaude/core/todo_watcher.py`
- `teleclaude/core/tool_access.py`
- `teleclaude/core/tool_activity.py`
- `teleclaude/core/voice_assignment.py`
- `teleclaude/core/voice_message_handler.py`

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
