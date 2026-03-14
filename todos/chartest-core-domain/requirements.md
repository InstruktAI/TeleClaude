# Requirements: chartest-core-domain

Characterization tests for core domain logic.

## Goal

Write characterization tests that pin current behavior of all listed source files
at their public boundaries, creating a safety net for future refactoring.

## Scope

### In scope

- Characterization tests for every listed source file
- 1:1 source-to-test file mapping under `tests/unit/`

### Out of scope

- Modifying production code
- Adding new features
- Refactoring existing code

## Source files

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

## Success criteria

- [ ] Every listed source file has a corresponding test file (or documented exemption)
- [ ] Tests pin actual behavior at public boundaries
- [ ] All tests pass on current codebase
- [ ] No string assertions on human-facing text
- [ ] Max 5 mock patches per test
- [ ] Each test name reads as a behavioral specification
- [ ] All existing tests still pass (no regressions)
- [ ] Lint and type checks pass

## Constraints

- Recommended agent: **claude**
- Follow OBSERVE-ASSERT-VERIFY cycle (not RED-GREEN-REFACTOR)
- Tests pass immediately — this is expected for characterization

## Methodology: Characterization Testing (OBSERVE-ASSERT-VERIFY)

Follow the OBSERVE-ASSERT-VERIFY cycle per source file. See testing policy for full details.

### Rules

- Test at public API boundaries only
- Behavioral contracts, not implementation details
- No string assertions on human-facing text
- Max 5 mock patches per test
- One clear expectation per test
- Mock at architectural boundaries (I/O, DB, network)
- Every test must answer: "What real bug in OUR code would this catch?"
- 1:1 source-to-test mapping
- Use pytest with standard fixtures
- Skip files with genuinely no testable logic — document why
