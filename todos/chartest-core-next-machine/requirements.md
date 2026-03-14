# Requirements: chartest-core-next-machine

Characterization tests for next-machine state machines.

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

- `teleclaude/core/next_machine/build_gates.py`
- `teleclaude/core/next_machine/create.py`
- `teleclaude/core/next_machine/delivery.py`
- `teleclaude/core/next_machine/git_ops.py`
- `teleclaude/core/next_machine/icebox.py`
- `teleclaude/core/next_machine/output_formatting.py`
- `teleclaude/core/next_machine/prepare.py`
- `teleclaude/core/next_machine/prepare_events.py`
- `teleclaude/core/next_machine/prepare_steps.py`
- `teleclaude/core/next_machine/roadmap.py`
- `teleclaude/core/next_machine/slug_resolution.py`
- `teleclaude/core/next_machine/state_io.py`
- `teleclaude/core/next_machine/work.py`
- `teleclaude/core/next_machine/worktrees.py`

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
