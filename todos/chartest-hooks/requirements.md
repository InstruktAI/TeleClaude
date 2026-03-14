# Requirements: chartest-hooks

Characterization tests for hook system.

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

- `teleclaude/hooks/api_routes.py`
- `teleclaude/hooks/checkpoint_flags.py`
- `teleclaude/hooks/config.py`
- `teleclaude/hooks/delivery.py`
- `teleclaude/hooks/dispatcher.py`
- `teleclaude/hooks/handlers.py`
- `teleclaude/hooks/inbound.py`
- `teleclaude/hooks/matcher.py`
- `teleclaude/hooks/registry.py`
- `teleclaude/hooks/webhook_models.py`
- `teleclaude/hooks/whatsapp_handler.py`
- `teleclaude/hooks/adapters/base.py`
- `teleclaude/hooks/adapters/claude.py`
- `teleclaude/hooks/adapters/codex.py`
- `teleclaude/hooks/adapters/gemini.py`
- `teleclaude/hooks/checkpoint/_evidence.py`
- `teleclaude/hooks/checkpoint/_git.py`
- `teleclaude/hooks/checkpoint/_models.py`
- `teleclaude/hooks/normalizers/github.py`
- `teleclaude/hooks/normalizers/whatsapp.py`
- `teleclaude/hooks/receiver/_session.py`
- `teleclaude/hooks/utils/parse_helpers.py`

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
