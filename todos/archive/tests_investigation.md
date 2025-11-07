# Test Quality Investigation Plan

**Target:** 90%+ test coverage with high-quality tests
**Current:** 17.69% coverage (as of 2025-11-01)

---

## Executive Summary

### Current State
- **Total Coverage:** 17.69%
- **Unit Tests:** 3 tests (voice_handler only)
- **Integration Tests:** 14 files (~40 tests)
- **Critical Gaps:** daemon.py (5.97%), telegram_adapter.py (7.32%), terminal_bridge.py (36.50%)

### Key Concerns
1. Main orchestrator (`daemon.py`) virtually untested
2. Recent features (escape commands, exit marker logic, timer updates) have **zero** tests
3. Unknown: Are we testing our logic or just mocking third-party libs?

---

## Investigation Steps

### 1. Coverage Audit (Quantitative)
**Goal:** Map what's tested vs what's critical

**Commands:**
```bash
# Generate detailed coverage report
.venv/bin/pytest tests/ --cov=teleclaude --cov-report=html --cov-report=term-missing

# Open HTML report
open htmlcov/index.html
```

**Deliverable:** Coverage matrix by module

| Module | Coverage | Lines | Critical? | Priority |
|--------|----------|-------|-----------|----------|
| daemon.py | 5.97% | 691 | YES | P0 |
| telegram_adapter.py | 7.32% | 476 | YES | P0 |
| terminal_bridge.py | 36.50% | 174 | YES | P1 |
| session_manager.py | 73.15% | 90 | YES | P2 |
| voice_handler.py | 87.76% | 39 | NO | P3 |

---

### 2. Test Quality Analysis (Qualitative)

**For each test file, answer:**

#### A. What Are We Testing?
- [ ] **Our business logic** (good)
- [ ] **Third-party library behavior** (bad - waste of time)
- [ ] **Integration points** (good if critical path)

**Example audit:**
```python
# tests/unit/test_voice.py
@patch("openai.OpenAI")  # ✅ Mocking external API, testing our retry logic
def test_voice_transcription_with_retry():
    # VERDICT: Good - tests our error handling
```

#### B. Test Approach Assessment

For each module, document:

**Unit Tests:**
- What's mocked vs real?
- Are we testing edge cases?
- Are we testing error paths?

**Integration Tests:**
- Do they use real components (tmux, sqlite)?
- Do they test end-to-end flows?
- Are they flaky? (timing issues, race conditions)

**Deliverable:** Test quality scorecard

```markdown
### tests/unit/test_voice.py
- **Coverage:** 87.76% (good)
- **Mocking:** OpenAI API (appropriate)
- **Edge cases:** ✅ Retry logic, ✅ Failure handling
- **Score:** 8/10 - Missing: timeout scenarios

### tests/integration/test_core.py
- **Coverage:** Basic CRUD only
- **Real components:** ✅ tmux, ✅ sqlite
- **Edge cases:** ❌ Session crashes, ❌ Concurrent access
- **Score:** 5/10 - Happy path only
```

---

### 3. Gap Analysis (What's Missing)

#### A. Untested Critical Paths

Run git diff to find recent changes without tests:
```bash
# Check recent commits
git log --oneline -20 --no-merges

# Check which files changed recently
git diff --stat HEAD~10

# Cross-reference with coverage report
```

**Deliverable:** Missing coverage list

```markdown
## P0 (Blocker - Core functionality)
- [ ] daemon.py:handle_message() - Double slash stripping (`//` → `/`)
- [ ] daemon.py:handle_message() - Exit marker logic (new vs running process)
- [ ] daemon.py:_poll_and_send_output() - Timer update throttling (5s)
- [ ] daemon.py:_escape_command() - Escape key sending
- [ ] terminal_bridge.py:send_keys() - append_exit_marker parameter
- [ ] telegram_adapter.py - All command handlers (cancel, escape, cd, etc.)

## P1 (High - User-facing)
- [ ] Command routing (all /commands)
- [ ] Session lifecycle (create, poll, exit)
- [ ] Error handling (tmux crash, network failures)
- [ ] Voice transcription integration

## P2 (Medium - Edge cases)
- [ ] Concurrent session handling
- [ ] File cleanup (output files, temp files)
- [ ] Database migrations
- [ ] Config validation
```

#### B. Test Infrastructure Gaps

```markdown
- [ ] No fixture for mocked Telegram bot
- [ ] No fixture for test tmux sessions (cleanup issues?)
- [ ] No helpers for async testing patterns
- [ ] No performance/stress tests
- [ ] No test data generators
```

---

### 4. Test Organization Review

**Current structure:**
```
tests/
├── unit/          # Only voice_handler
├── integration/   # 14 files, mixed quality
└── manual/        # 6 files - should be automated?
```

**Questions to answer:**
1. Why are manual tests not automated?
2. Is unit vs integration split logical?
3. Are test names descriptive?
4. Are tests independent (no shared state)?

**Deliverable:** Reorganization proposal

---

## Execution Plan

### Phase 1: Quick Wins (1-2 days)
**Goal:** Get to 50% coverage

1. **Daemon core paths** (daemon.py)
   - Test handle_message() with mocked adapter
   - Test command routing (all commands)
   - Test _poll_and_send_output() with mocked tmux

2. **Terminal bridge** (terminal_bridge.py)
   - Test send_keys() with append_exit_marker variations
   - Test send_escape()
   - Test all tmux operations with real tmux

3. **Telegram adapter** (telegram_adapter.py)
   - Test all command handlers with mocked bot
   - Test message routing
   - Test callback query handling

### Phase 2: Edge Cases (2-3 days)
**Goal:** Get to 75% coverage

1. Error scenarios (network failures, tmux crashes)
2. Concurrent operations (multiple sessions)
3. Resource cleanup (file deletion, session cleanup)
4. Configuration edge cases

### Phase 3: Comprehensive (3-5 days)
**Goal:** Get to 90%+ coverage

1. All branches covered (if/else, try/except)
2. All error paths tested
3. Performance/stress tests
4. Documentation of test patterns

---

## Test Quality Checklist

For each new test, verify:

- [ ] **Tests OUR code**, not third-party libraries
- [ ] **Descriptive name** (`test_send_keys_appends_exit_marker_for_new_commands`)
- [ ] **Clear arrange-act-assert** structure
- [ ] **Mocks external dependencies** (OpenAI, Telegram API)
- [ ] **Uses real components** when testing integration (tmux, sqlite)
- [ ] **Tests edge cases** (empty input, invalid data, errors)
- [ ] **Tests error paths** (exceptions, failures, timeouts)
- [ ] **Independent** (no shared state, no order dependency)
- [ ] **Fast** (< 1s for unit tests, < 5s for integration)
- [ ] **Deterministic** (no flaky tests due to timing)

---

## Success Metrics

| Metric | Current | Target | Timeline |
|--------|---------|--------|----------|
| Coverage | 17.69% | 90% | 2 weeks |
| P0 gaps covered | 0% | 100% | 3 days |
| P1 gaps covered | 0% | 80% | 1 week |
| Test quality score | ? | 8/10 avg | 2 weeks |
| Flaky tests | ? | 0 | 1 week |

---

## Recommended Tools

```bash
# Coverage with branch coverage
pytest --cov=teleclaude --cov-branch --cov-report=html

# Find slow tests
pytest --durations=10

# Find flaky tests
pytest --count=10 tests/integration/

# Mutation testing (check test quality)
pip install mutpy
mutpy --target teleclaude --unit-test tests
```

---

## Output Deliverables

1. **Coverage Report** (`htmlcov/index.html`)
2. **Quality Scorecard** (markdown table per module)
3. **Gap Analysis** (prioritized checklist)
4. **Test Plan** (what to write, in priority order)
5. **CI/CD Integration** (GitHub Actions workflow with coverage gates)

---

## Notes

- **Don't test library code** - Focus on our business logic
- **Integration tests should use real tmux** - Mocking tmux defeats the purpose
- **Mock Telegram API** - We don't want to send real messages during tests
- **Fixtures are your friend** - Reuse setup code
- **Test error paths** - Most bugs happen in error handling

---

## Critical Review: Recently Added Tests (2025-11-01)

**Coverage Achieved:** 46.53% → 58.50% (+11.97%)
**Tests Added:** 20 new tests across daemon.py

### Quality Assessment

#### ✅ GOOD - What Works Well

1. **Comprehensive _poll_and_send_output coverage** (7 tests)
   - Tests critical polling logic with proper mocking
   - Patches `asyncio.sleep` to avoid delays
   - Tests exit code detection (PRIMARY stop condition)
   - Tests idle notification without stopping poll
   - Tests message editing flow and error recovery

2. **Error handling tests** (8 tests)
   - Simple, focused tests for edge cases
   - Tests missing parameters gracefully
   - Tests unknown adapter types

3. **claude_resume command** (3 tests)
   - Tests happy path and error scenarios
   - Properly mocks terminal and session manager

4. **Mocking strategy**
   - External APIs mocked (Telegram, OpenAI)
   - Focus on testing our business logic, not libraries

#### ⚠️ ISSUES - Potential Problems

### 1. **Directory Cleanup Issues** (MEDIUM)

**Problem:** Tests create `/tmp/test_output` directories but may not clean them up.

**Affected Tests:**
- `test_poll_with_idle_notification`
- `test_poll_with_output_truncation`
- `test_poll_edit_failure_sends_new_message`
- `test_poll_notification_deleted_when_output_resumes`

**Evidence:**
```python
# Tests do this:
mock_daemon.output_dir = Path("/tmp/test_output")
mock_daemon.output_dir.mkdir(parents=True, exist_ok=True)

# But never clean up!
```

**Impact:** Low (uses /tmp, but could accumulate junk over time)

**Fix:**
```python
# Use pytest fixtures with cleanup
@pytest.fixture
def temp_output_dir():
    path = Path(tempfile.mkdtemp(prefix="test_output_"))
    yield path
    shutil.rmtree(path, ignore_errors=True)
```

---

### 2. **Fragile Poll Count Assertions** (MEDIUM)

**Problem:** Tests rely on exact poll counts which could break with minor logic changes.

**Affected Tests:**
- `test_poll_with_idle_notification`
- `test_poll_notification_deleted_when_output_resumes`

**Evidence:**
```python
# Brittle assertion:
assert poll_count[0] >= 4  # What if polling logic changes?
```

**Impact:** Medium (tests could fail on refactoring)

**Better approach:**
```python
# Test behavior, not implementation:
assert idle_notification_sent  # What matters
# Don't assert exact poll count
```

---

### 3. **Incomplete Truncation Test** (LOW)

**Problem:** `test_poll_with_output_truncation` doesn't verify download button structure.

**Evidence:**
```python
# Weak assertion:
if metadata:
    assert "reply_markup" in metadata or "raw_format" in metadata
# Should verify InlineKeyboardMarkup structure!
```

**Impact:** Low (test passes but doesn't verify button works)

**Fix:**
```python
# Verify button structure:
from telegram import InlineKeyboardMarkup
assert isinstance(metadata["reply_markup"], InlineKeyboardMarkup)
assert "download_full" in metadata["reply_markup"].inline_keyboard[0][0].callback_data
```

---

### 4. **Lock Test Race Conditions** (HIGH RISK)

**Problem:** Lock tests use real file locking which could interfere with running daemon.

**Affected Tests:**
- `test_daemon_lock_acquisition`
- `test_daemon_lock_already_held`

**Evidence:**
```python
# Uses real fcntl locks:
daemon._acquire_lock()  # Could block if daemon is running!
```

**Current Mitigation:**
- Tests use temporary PID files (GOOD)
- But if temp file path collides, tests could hang

**Risk:** HIGH in CI environments where daemons might be running

**Better approach:**
```python
# Mock fcntl for unit tests, or use integration test marker:
@pytest.mark.integration
@pytest.mark.skipif(daemon_is_running(), reason="Daemon running")
```

---

### 5. **Missing Edge Cases** (MEDIUM)

**Gaps identified:**

1. **_poll_and_send_output:**
   - ❌ What if output file write fails mid-poll? (caught, but not tested)
   - ❌ What if adapter.send_message fails? (error logged, poll continues?)
   - ❌ Max polls reached (600) - should send timeout message
   - ❌ Session death with buffered output - is buffer sent?

2. **claude_resume:**
   - ❌ Invalid terminal_size format (e.g., "80" instead of "80x24")
   - ❌ Missing working_directory handling

3. **Daemon initialization:**
   - ❌ Config file parse errors
   - ❌ Missing environment variables
   - ❌ Adapter loading failures (tested partially)

**Impact:** Medium (real-world scenarios not covered)

---

### 6. **No Fixture Reuse** (LOW)

**Problem:** Tests duplicate setup code instead of using fixtures.

**Evidence:**
```python
# Duplicated in every test:
mock_daemon.output_dir = Path("/tmp/test_output")
mock_daemon.output_dir.mkdir(parents=True, exist_ok=True)
mock_daemon.config = {"polling": {"idle_notification_seconds": 2}}
```

**Impact:** Low (maintenance burden, not correctness)

**Better approach:**
```python
@pytest.fixture
def configured_daemon(mock_daemon):
    mock_daemon.output_dir = Path(tempfile.mkdtemp())
    mock_daemon.config = {"polling": {"idle_notification_seconds": 2}}
    yield mock_daemon
    shutil.rmtree(mock_daemon.output_dir, ignore_errors=True)
```

---

### 7. **Async Mocking Inconsistency** (LOW)

**Problem:** Some tests mix AsyncMock and MagicMock inconsistently.

**Evidence:**
```python
# Inconsistent:
mock_daemon.terminal.send_keys = AsyncMock(return_value=True)  # Async
mock_daemon.config = {}  # Not mocked, direct assignment
```

**Impact:** Low (tests work, but confusing)

**Best practice:** Be explicit about what's async vs sync.

---

## Test Quality Scorecard

| Test Suite | Coverage | Mocking | Edge Cases | Cleanup | Score |
|------------|----------|---------|------------|---------|-------|
| _poll_and_send_output | ✅ 90%+ | ✅ Good | ⚠️ Partial | ⚠️ Missing | 7/10 |
| claude_resume | ✅ 100% | ✅ Good | ⚠️ Partial | ✅ Good | 7/10 |
| Error handling | ✅ 100% | ✅ Good | ✅ Good | ✅ Good | 9/10 |
| Daemon init | ✅ 80% | ✅ Good | ⚠️ Partial | ⚠️ Risky | 6/10 |

**Average Score:** 7.25/10 (Good, not excellent)

---

## Recommendations for Next Phase

### Immediate Fixes (P0)
1. ✅ **Add cleanup fixtures** for temp directories
2. ✅ **Remove fragile poll count assertions** - test behavior, not implementation
3. ✅ **Improve truncation test** - verify download button structure

### Short-term Improvements (P1)
4. ✅ **Add max polls timeout test** - verify 600 poll limit behavior
5. ✅ **Test output file write failures** - ensure graceful degradation
6. ✅ **Test config parse errors** - daemon should fail fast with clear errors

### Long-term Quality (P2)
7. ✅ **Create test fixtures library** - reduce duplication
8. ✅ **Add mutation testing** - verify tests actually catch bugs
9. ✅ **Performance benchmarks** - ensure polls don't slow down

---

## Conclusion

**Overall Assessment:** Tests are **functional but improvable**.

**Strengths:**
- Good mocking strategy (external APIs isolated)
- Comprehensive coverage of main polling logic
- Error paths tested

**Weaknesses:**
- Resource cleanup gaps (temp dirs)
- Fragile assertions (poll counts)
- Missing edge cases (timeouts, parse errors)
- Lock tests could cause CI flakiness

**Next Steps:**
1. Fix cleanup issues (add fixtures)
2. Remove brittle assertions
3. Add missing edge case tests
4. Consider integration tests for lock behavior

**Verdict:** ✅ **Ship it** (with fixes applied before merge)
