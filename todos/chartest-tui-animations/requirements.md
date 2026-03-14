# Requirements: chartest-tui-animations

Characterization tests for TUI animations.

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

- `teleclaude/cli/tui/animation_colors.py`
- `teleclaude/cli/tui/animation_engine.py`
- `teleclaude/cli/tui/animation_triggers.py`
- `teleclaude/cli/tui/animations/agent.py`
- `teleclaude/cli/tui/animations/base.py`
- `teleclaude/cli/tui/animations/config.py`
- `teleclaude/cli/tui/animations/creative.py`
- `teleclaude/cli/tui/animations/general.py`
- `teleclaude/cli/tui/animations/particles.py`
- `teleclaude/cli/tui/animations/sky.py`
- `teleclaude/cli/tui/animations/sprites/birds.py`
- `teleclaude/cli/tui/animations/sprites/cars.py`
- `teleclaude/cli/tui/animations/sprites/celestial.py`
- `teleclaude/cli/tui/animations/sprites/clouds.py`
- `teleclaude/cli/tui/animations/sprites/composite.py`
- `teleclaude/cli/tui/animations/sprites/ufo.py`

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
