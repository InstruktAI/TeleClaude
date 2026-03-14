# Requirements: chartest-cli-telec

Characterization tests for telec CLI surface.

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

- `teleclaude/cli/telec/_run_tui.py`
- `teleclaude/cli/telec/_shared.py`
- `teleclaude/cli/telec/handlers/auth_cmds.py`
- `teleclaude/cli/telec/handlers/bugs.py`
- `teleclaude/cli/telec/handlers/config.py`
- `teleclaude/cli/telec/handlers/content.py`
- `teleclaude/cli/telec/handlers/demo.py`
- `teleclaude/cli/telec/handlers/docs.py`
- `teleclaude/cli/telec/handlers/events_signals.py`
- `teleclaude/cli/telec/handlers/history.py`
- `teleclaude/cli/telec/handlers/memories.py`
- `teleclaude/cli/telec/handlers/misc.py`
- `teleclaude/cli/telec/handlers/roadmap.py`
- `teleclaude/cli/telec/handlers/todo.py`
- `teleclaude/cli/telec/help.py`
- `teleclaude/cli/telec/surface.py`
- `teleclaude/cli/telec/surface_types.py`
- `teleclaude/cli/tool_commands/infra.py`
- `teleclaude/cli/tool_commands/sessions.py`
- `teleclaude/cli/tool_commands/todo.py`

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

- Recommended agent: **codex**
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
