# Test Suite Quality Requirements

## Purpose

Define the quality criteria that ALL tests in this codebase must meet. This document describes the DESIRED STATE, not the current state. Every test will be evaluated against these criteria.

---

## Fundamental Principles

### 1. Production Code is Sacrosanct

**NEVER modify production code to accommodate tests.**

- Tests adapt to the code, not the reverse
- If a test cannot be written without changing production code, the test design is wrong
- No adding `try/except` blocks for test convenience
- No exposing private methods for testing
- No adding parameters "for testability"
- No conditional logic that checks if running in test mode

### 2. Tests are Black Box

**Test the CONTRACT, not the implementation.**

- A test verifies WHAT the code does, not HOW it does it
- Only public interfaces are tested
- Private methods are tested indirectly through public methods

### 3. Tests Verify Behavior

**Assert on OBSERVABLE OUTCOMES, not internal calls.**

- GOOD: Assert that the database contains the expected record
- GOOD: Assert that the function returns the expected value
- GOOD: Assert that the expected exception is raised
- BAD: Assert that `mock.assert_called_once()`
- BAD: Assert that `mock.call_args == expected`
- BAD: Assert on the number of times a method was called

---

## Quality Criteria

### Independence

Each test must be completely independent:

- No shared mutable state between tests
- No reliance on test execution order
- Each test sets up its own preconditions
- Each test cleans up after itself
- Running a single test produces the same result as running the full suite

### Determinism

Each test must be deterministic:

- Same inputs always produce the same result
- No reliance on current time (mock it)
- No reliance on random values (seed or mock them)
- No reliance on filesystem state outside the test
- No reliance on network availability
- No reliance on external services

### Speed

Unit tests must be fast:

- Target: < 100ms per test
- No unnecessary I/O
- No unnecessary network calls
- No unnecessary database operations (mock the interface)
- Use in-memory alternatives where appropriate

### Clarity

Each test must be self-documenting:

- Test name describes the behavior being tested
- Format: `test_<function>_<scenario>_<expected_outcome>`
- Example: `test_create_session_with_invalid_path_raises_validation_error`
- Arrange-Act-Assert pattern is visible
- No complex logic in tests (no loops, no conditionals)

### Single Responsibility

Each test verifies ONE behavior:

- One logical assertion per test (multiple asserts on same object is OK)
- If a test fails, you know exactly what broke
- Tests are not "mega tests" that verify multiple scenarios

---

## Mocking Rules

### What to Mock

Mock at SYSTEM BOUNDARIES only:

- Database connections and queries
- Network calls (HTTP, Redis, external APIs)
- Filesystem operations (when testing non-file logic)
- System time (`time.time()`, `datetime.now()`)
- External processes (subprocess calls)
- Third-party libraries that have side effects

### What NOT to Mock

Never mock:

- The code under test
- Pure functions within the same module
- Data classes and models
- Configuration objects (use test configuration instead)
- Anything that makes the test meaningless if mocked

### Mock Accuracy

Mocks MUST exactly match the real interface:

- Same method names
- Same parameter signatures
- Same return types
- Same exception types

### Mock Verification

When mocks are necessary:

- Verify the mock was called with correct arguments IF that's the behavior being tested
- Prefer testing the RESULT over testing the CALL
- If you can test the outcome without verifying mock calls, do that instead

---

## Test Structure

### Arrange-Act-Assert

Every test follows this pattern:

```python
def test_function_scenario_expected():
    # Arrange: Set up preconditions
    input_data = create_test_input()

    # Act: Execute the code under test
    result = function_under_test(input_data)

    # Assert: Verify the outcome
    assert result == expected_value
```

### Naming Convention

```
test_<unit>_<scenario>_<expected>
```

Examples:
- `test_create_session_with_valid_input_returns_session_id`
- `test_create_session_with_duplicate_title_appends_counter`
- `test_delete_session_when_already_closed_succeeds_silently`

### Docstrings

Each test should have a docstring explaining:
- What behavior is being tested
- Edge cases covered (if any)

---

## Database Testing

### Approach

For database operations:

- Mock the database INTERFACE (`Db` class methods)
- Do NOT use a different database engine for testing
- Test that the code handles return values correctly
- Test that the code handles errors correctly

### What to Verify

- That errors are handled appropriately
- That return values are processed correctly
- That the function produces the correct output given mocked DB responses

---

## Async Testing

### Requirements

For async code:

- Use `pytest.mark.asyncio` decorator
- Mock async functions with `AsyncMock`
- Test both success and error paths
- Verify timeouts are handled
- Verify cancellation is handled

---

## Error Handling Tests

### Requirements

Every function that can raise exceptions must have tests for:

- Each exception type that can be raised
- The conditions that trigger each exception
- That error messages are informative
- That cleanup occurs on error

---

## Coverage Requirements

### Minimum Coverage

- All public functions must have at least one test
- All code branches must be exercised
- All error paths must be tested
- All edge cases must be covered

### Edge Cases to Test

- Empty inputs
- Null/None values
- Boundary values
- Invalid inputs
- Concurrent access (where applicable)
- Resource exhaustion (where applicable)

---

## Review Checklist

Before a test is approved, verify:

- [x] Does NOT require production code changes
- [x] Tests behavior, not implementation
- [x] Independent of other tests
- [x] Deterministic
- [x] Fast (< 100ms)
- [x] Clear naming and structure
- [x] Mocks only at system boundaries
- [x] Asserts on observable outcomes
- [x] Covers error cases
- [x] Has descriptive docstring

---

## Anti-Patterns to Eliminate

### Tests That Only Verify Mock Calls

```python
# BAD - tests nothing about behavior
def test_send_message():
    mock_bot.send_message = AsyncMock()
    await send_message(...)
    mock_bot.send_message.assert_called_once()  # So what?
```

### Tests That Match Implementation Details

```python
# BAD - tests internal method instead of behavior
def test_internal_method_called():
    with patch('module._internal_helper') as mock:
        function_under_test()
        mock.assert_called_with(specific_internal_args)
```

### Tests With Wrong Expected Values

```python
# BAD - expected value does not match the correct behavior
def test_same_computer_keeps_computer_suffix():
    assert result == "Claude-fast@MozMini"  # Verify this is actually correct
```

### Tests That Required Production Code Changes

```python
# BAD - production code was modified to make this test pass
try:
    db.get_ux_state(...)
except DatabaseNotInitialized:
    return None  # This exception handler exists only for tests
```

### Mega Tests

```python
# BAD - tests too many things
def test_everything():
    # 50 lines of setup
    # Multiple scenarios
    # Multiple assertions on different behaviors
```

---

## Execution Process

For each test file:

1. Read every test function completely
2. Evaluate against each criterion above
3. Decide: KEEP (meets criteria), MODIFY (fixable), DELETE (unfixable)
4. Make changes
5. Run `make test` to verify
6. Run `make lint` to verify
7. Commit with descriptive message

---

## Files to Process

1. `tests/unit/test_db.py`
2. `tests/unit/test_session_utils.py`
3. `tests/unit/test_mcp_server.py`
4. `tests/unit/test_command_handlers.py`
5. `tests/unit/test_telegram_adapter.py`
6. `tests/unit/test_terminal_bridge.py`
7. `tests/unit/test_daemon.py`
8. `tests/unit/test_models.py`
9. `tests/unit/test_agents.py`
10. `tests/unit/test_transcript.py`
11. `tests/unit/test_summarizer.py`
12. `tests/unit/test_next_machine_hitl.py`
13. `tests/unit/test_output_poller.py`
14. `tests/unit/test_mcp_wrapper.py`
15. `tests/integration/test_mcp_tools.py`
16. `tests/integration/test_session_lifecycle.py`
