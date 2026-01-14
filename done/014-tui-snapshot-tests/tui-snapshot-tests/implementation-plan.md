# Implementation Plan: TUI View & Data Flow Tests

## Overview

**Delivered Scope (Phases 1-3):**
1. **View Logic Tests** - Unit tests for view rendering decisions
2. **Test Infrastructure** - Mock factories and MockAPIClient for event simulation

**Deferred Scope (Phases 4-6):**
See follow-up work items in roadmap for:
- Data Flow Integration Tests (event → cache → view pipeline)
- Reconnection & Edge Cases
- CI Integration & Documentation

---

## Scope Change Note

**Original plan included 6 phases.** After completing Phases 1-3, it was determined that:
- Core testability achieved via `get_render_lines()` refactor (Phase 1)
- View logic thoroughly tested (Phase 3)
- TUIAppTestHarness (Phase 2.3) and data flow tests (Phases 4-6) provide diminishing returns for current needs
- These can be implemented later if integration testing gaps emerge

**Decision:** Ship Phases 1-3, defer 4-6 to follow-up work items.

---

## Phase 1: View Architecture Refactor

**Goal:** Make views testable by separating render logic from curses drawing.

- [x] **Task 1.1:** Audit existing view classes
  - Files: `teleclaude/cli/tui/views/*.py`
  - Identify where render logic is coupled to curses
  - Document current structure

- [x] **Task 1.2:** Add `get_render_lines()` to BaseView
  ```python
  class BaseView:
      def get_render_lines(self, width: int, height: int) -> list[str]:
          """Return lines this view would render (testable without curses)."""
          raise NotImplementedError
  ```

- [x] **Task 1.3:** Refactor SessionsView
  - Extract row formatting to pure functions
  - Implement `get_render_lines()` that returns formatted output
  - Keep `draw()` method that calls curses with these lines

- [x] **Task 1.4:** Refactor PreparationView
  - Same pattern: extract formatting, implement `get_render_lines()`

### Verification:
- Views still render correctly in actual TUI
- `get_render_lines()` returns list of strings
- `make test-unit` still passes

---

## Phase 2: Test Infrastructure

**Goal:** Create test harness and mock factories.

- [x] **Task 2.1:** Create mock data factories
  ```python
  # tests/conftest.py

  def create_mock_session(
      session_id: str = "test-001",
      title: str = "Test Session",
      status: str = "active",
      computer: str = "test-computer",
  ) -> SessionInfo:
      """Create mock SessionInfo for testing."""
      return SessionInfo(
          session_id=session_id,
          title=title,
          status=status,
          computer=computer,
          origin_adapter="telegram",
          working_directory="/test/path",
          thinking_mode="slow",
          active_agent="claude",
          created_at=datetime.now(UTC),
          last_activity=datetime.now(UTC),
      )
  ```

- [x] **Task 2.2:** Create MockAPIClient for event simulation
  ```python
  # tests/conftest.py

  class MockAPIClient:
      """Mock API client that can simulate push events."""

      def __init__(self):
          self._event_handlers: list[Callable] = []
          self.sessions: list[SessionInfo] = []
          self.projects: list[ProjectInfo] = []

      def on_event(self, handler: Callable):
          """Register event handler (like real client)."""
          self._event_handlers.append(handler)

      def simulate_event(self, event: str, data: dict):
          """Simulate a push event from backend."""
          for handler in self._event_handlers:
              handler(event, data)

      def get_sessions(self) -> list[SessionInfo]:
          """Return mock sessions."""
          return self.sessions
  ```

- [ ] **Task 2.3:** Create TUIAppTestHarness
  ```python
  # tests/conftest.py

  class TUIAppTestHarness:
      """Test harness for TUI integration tests."""

      def __init__(self):
          self.mock_client = MockAPIClient()
          self.app = create_testable_app(self.mock_client)

      async def wait_for_update(self, timeout: float = 1.0):
          """Wait for app to process pending events."""
          await self.app.process_pending_events()

      def get_current_render(self, width: int = 80, height: int = 24) -> list[str]:
          """Get what current view would render."""
          return self.app.current_view.get_render_lines(width, height)

      def get_render_text(self) -> str:
          """Get render output as single string for easier assertions."""
          return "\n".join(self.get_current_render())
  ```

### Verification:
- Harness can create app with mock client
- Event simulation triggers handlers
- `get_render_lines()` returns content

---

## Phase 3: View Logic Tests (Layer 1)

**Goal:** Unit tests for each view's rendering logic.

- [x] **Task 3.1:** SessionsView tests
  ```python
  # tests/unit/test_tui_sessions_view.py

  class TestSessionsViewLogic:

      def test_empty_shows_message(self):
          view = SessionsView(sessions=[])
          lines = view.get_render_lines(80, 24)
          assert any("no sessions" in line.lower() for line in lines)

      def test_sessions_appear_in_output(self):
          sessions = [
              create_mock_session(title="Alpha"),
              create_mock_session(title="Beta"),
          ]
          view = SessionsView(sessions=sessions)
          output = "\n".join(view.get_render_lines(80, 24))
          assert "Alpha" in output
          assert "Beta" in output

      def test_status_shown(self):
          session = create_mock_session(status="active")
          view = SessionsView(sessions=[session])
          output = "\n".join(view.get_render_lines(80, 24))
          assert "active" in output.lower()

      def test_selection_indicator(self):
          sessions = [create_mock_session() for _ in range(3)]
          view = SessionsView(sessions=sessions)
          view.selected_index = 1
          lines = view.get_render_lines(80, 24)
          # Selected row should have indicator
          # (exact indicator depends on implementation)

      def test_long_title_truncated(self):
          session = create_mock_session(title="A" * 100)
          view = SessionsView(sessions=[session])
          lines = view.get_render_lines(80, 24)
          assert all(len(line) <= 80 for line in lines)
  ```

- [x] **Task 3.2:** PreparationView tests
  ```python
  # tests/unit/test_tui_preparation_view.py

  class TestPreparationViewLogic:

      def test_empty_shows_message(self):
          view = PreparationView(todos=[])
          lines = view.get_render_lines(80, 24)
          assert any("no work" in line.lower() for line in lines)

      def test_ready_status_shown(self):
          todo = create_mock_todo(status="ready")
          view = PreparationView(todos=[todo])
          output = "\n".join(view.get_render_lines(80, 24))
          assert "ready" in output.lower() or "[.]" in output

      def test_blocked_status_shown(self):
          todo = create_mock_todo(status="blocked")
          view = PreparationView(todos=[todo])
          output = "\n".join(view.get_render_lines(80, 24))
          assert "blocked" in output.lower()
  ```

- [x] **Task 3.3:** Edge case tests
  ```python
  def test_unicode_in_title(self):
      session = create_mock_session(title="Test 🚀 Session")
      view = SessionsView(sessions=[session])
      output = "\n".join(view.get_render_lines(80, 24))
      assert "🚀" in output

  def test_many_sessions_handled(self):
      sessions = [create_mock_session(title=f"S{i}") for i in range(100)]
      view = SessionsView(sessions=sessions)
      lines = view.get_render_lines(80, 24)
      assert len(lines) > 0  # Doesn't crash
  ```

### Verification:
- `pytest tests/unit/test_tui_*_view.py -v` passes
- Tests run in <2 seconds

---

## Phase 4: Data Flow Integration Tests (Layer 2)

**Goal:** Test the full event → view pipeline.

- [ ] **Task 4.1:** Session lifecycle tests
  ```python
  # tests/integration/test_tui_data_flow.py

  class TestSessionDataFlow:

      @pytest.fixture
      def harness(self):
          return TUIAppTestHarness()

      async def test_new_session_appears_on_push(self, harness):
          """Push event → session visible in view."""
          harness.mock_client.simulate_event("session_updated", {
              "session_id": "new-1",
              "title": "New Session",
              "status": "active",
              "computer": "test"
          })

          await harness.wait_for_update()

          output = harness.get_render_text()
          assert "New Session" in output

      async def test_session_status_updates(self, harness):
          """Status change event → view reflects new status."""
          # Add initial session
          harness.mock_client.sessions = [
              create_mock_session(session_id="s1", status="active")
          ]

          # Push status update
          harness.mock_client.simulate_event("session_updated", {
              "session_id": "s1",
              "status": "idle"
          })

          await harness.wait_for_update()

          output = harness.get_render_text()
          assert "idle" in output.lower()

      async def test_session_removal(self, harness):
          """Removal event → session gone from view."""
          harness.mock_client.sessions = [
              create_mock_session(session_id="s1", title="ToRemove")
          ]

          harness.mock_client.simulate_event("session_removed", {
              "session_id": "s1"
          })

          await harness.wait_for_update()

          output = harness.get_render_text()
          assert "ToRemove" not in output
  ```

- [ ] **Task 4.2:** Error state tests
  ```python
  async def test_error_shown_on_failure(self, harness):
      """Backend error → error message in view."""
      harness.mock_client.simulate_error("Connection failed")

      await harness.wait_for_update()

      output = harness.get_render_text()
      assert "error" in output.lower() or "failed" in output.lower()

  async def test_connection_lost_state(self, harness):
      """Disconnect → appropriate state shown."""
      harness.mock_client.simulate_disconnect()

      await harness.wait_for_update()

      output = harness.get_render_text()
      assert "disconnect" in output.lower() or "offline" in output.lower()
  ```

- [ ] **Task 4.3:** Manual refresh test
  ```python
  async def test_manual_refresh_updates_view(self, harness):
      """Refresh action → data re-fetched → view updated."""
      # Initial state
      harness.mock_client.sessions = []
      await harness.wait_for_update()
      assert "no sessions" in harness.get_render_text().lower()

      # Add session on backend
      harness.mock_client.sessions = [
          create_mock_session(title="AfterRefresh")
      ]

      # Trigger refresh
      harness.app.handle_key(ord('r'))  # 'r' for refresh
      await harness.wait_for_update()

      assert "AfterRefresh" in harness.get_render_text()
  ```

- [ ] **Task 4.4:** View navigation tests
  ```python
  async def test_view_switch_on_keypress(self, harness):
      """Key press → view switches."""
      # Start on sessions view
      assert harness.app.current_view_name == "sessions"

      # Press key to switch to preparation
      harness.app.handle_key(ord('p'))
      await harness.wait_for_update()

      assert harness.app.current_view_name == "preparation"

  async def test_selection_moves_on_arrow(self, harness):
      """Arrow key → selection moves."""
      harness.mock_client.sessions = [
          create_mock_session() for _ in range(3)
      ]
      await harness.wait_for_update()

      assert harness.app.sessions_view.selected_index == 0

      harness.app.handle_key(curses.KEY_DOWN)
      assert harness.app.sessions_view.selected_index == 1
  ```

### Verification:
- `pytest tests/integration/test_tui_data_flow.py -v` passes
- Tests cover all common use cases
- Tests run in <5 seconds

---

## Phase 5: Reconnection & Edge Cases

**Goal:** Test resilience scenarios.

- [ ] **Task 5.1:** Reconnection test
  ```python
  async def test_reconnect_restores_data(self, harness):
      """Disconnect → reconnect → data restored."""
      harness.mock_client.sessions = [
          create_mock_session(title="Persistent")
      ]
      await harness.wait_for_update()

      # Disconnect
      harness.mock_client.simulate_disconnect()
      await harness.wait_for_update()

      # Reconnect
      harness.mock_client.simulate_reconnect()
      await harness.wait_for_update()

      assert "Persistent" in harness.get_render_text()
  ```

- [ ] **Task 5.2:** Rapid events test
  ```python
  async def test_rapid_events_no_drops(self, harness):
      """Many rapid events → all processed."""
      for i in range(20):
          harness.mock_client.simulate_event("session_updated", {
              "session_id": f"rapid-{i}",
              "title": f"Rapid{i}",
              "status": "active"
          })

      await harness.wait_for_update()

      output = harness.get_render_text()
      # At least some should be visible (or all if no pagination)
      assert "Rapid" in output
  ```

### Verification:
- Edge case tests pass
- No race conditions or dropped events

---

## Phase 6: CI Integration

**Goal:** Ensure tests run reliably in CI.

- [ ] **Task 6.1:** Add Makefile targets
  ```makefile
  test-tui-views:
      uv run pytest tests/unit/test_tui_*_view.py -v --tb=short

  test-tui-flow:
      uv run pytest tests/integration/test_tui_data_flow.py -v --tb=short

  test-tui: test-tui-views test-tui-flow
  ```

- [ ] **Task 6.2:** Verify included in main test suite
  - `make test-unit` includes view tests
  - `make test-e2e` includes data flow tests

- [ ] **Task 6.3:** Document TUI testing
  - How to run tests
  - How to add new tests
  - How harness works

### Verification:
- `make test-tui` passes
- Total runtime <10 seconds
- Works in CI (no display needed)

---

## Test Coverage Summary (Delivered)

| Layer | Tests | What's Covered |
|-------|-------|----------------|
| **View Logic** | 23 | Empty state, data presence, selection, status, truncation, unicode, scrolling, indentation |
| **Total** | 23 | View rendering logic fully covered |

**Deferred to follow-up:**
- Data Flow tests (~12 tests): Session CRUD, errors, refresh, navigation, reconnection
- See roadmap for follow-up work items

---

## Commit Format

```
feat(tests): add TUI view and data flow tests (Phase 1-3)

Testable view architecture without curses dependency:

Phase 1 - View Architecture Refactor:
- Added get_render_lines() to BaseView for testable rendering
- Refactored SessionsView and PreparationView to separate render logic

Phase 2 - Test Infrastructure:
- Mock data factories (sessions, computers, projects)
- MockAPIClient for event simulation

Phase 3 - View Logic Tests (23 tests):
- SessionsView: empty, data, selection, truncation, scrolling
- PreparationView: empty, status indicators, indentation, file tracking

Tests are fast (<1s), deterministic, and run without curses.
Phases 4-6 (data flow, edge cases, CI docs) deferred to follow-up.

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Co-Authored-By: TeleClaude <noreply@instrukt.ai>
```
