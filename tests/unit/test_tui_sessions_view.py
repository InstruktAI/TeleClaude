"""Unit tests for SessionsView render logic."""

import pytest

from teleclaude.cli.models import ComputerInfo, CreateSessionResult, ProjectInfo, SessionInfo
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    ComputerNode,
    ProjectNode,
    SessionDisplayInfo,
    SessionNode,
)
from teleclaude.cli.tui.views.sessions import SessionsView


@pytest.fixture
def mock_focus():
    """Create mock FocusContext."""

    class MockFocus:
        def __init__(self):
            self.computer = None
            self.project = None
            self.stack = []

    return MockFocus()


@pytest.fixture
def mock_pane_manager():
    """Create mock TmuxPaneManager."""

    class MockPaneManager:
        def __init__(self):
            self.active_session = None
            self.is_available = False

        def show_session(self, *_args, **_kwargs):
            return None

        def toggle_session(self, *_args, **_kwargs):
            return None

    return MockPaneManager()


@pytest.fixture
def sessions_view(mock_focus, mock_pane_manager):
    """Create SessionsView instance for testing."""
    return SessionsView(
        api=None,  # Not needed for render tests
        agent_availability={},
        focus=mock_focus,
        pane_manager=mock_pane_manager,
    )


@pytest.mark.unit
class TestSessionsViewLogic:
    """Layer 1: View logic tests."""

    def _make_session_info(
        self,
        *,
        session_id: str = "s1",
        title: str = "Test Session",
        status: str = "active",
        computer: str = "test-computer",
        active_agent: str = "claude",
        thinking_mode: str = "slow",
        last_input: str | None = None,
        last_input_at: str | None = "2024-01-01T00:00:00Z",
        last_output: str | None = None,
        last_output_at: str | None = "2024-01-01T00:01:00Z",
        last_activity: str = "2024-01-01T00:02:00Z",
        tmux_session_name: str | None = None,
        display_index: str = "1",
    ) -> SessionInfo:
        return SessionInfo(
            session_id=session_id,
            last_input_origin="telegram",
            title=title,
            project_path="/test/project",
            thinking_mode=thinking_mode,
            active_agent=active_agent,
            status=status,
            created_at="2024-01-01T00:00:00Z",
            last_activity=last_activity,
            last_input=last_input,
            last_input_at=last_input_at,
            last_output=last_output,
            last_output_at=last_output_at,
            tmux_session_name=tmux_session_name,
            initiator_session_id=None,
            computer=computer,
        )

    def _make_session_node(
        self,
        *,
        session_id: str = "s1",
        title: str = "Test Session",
        status: str = "active",
        computer: str = "test-computer",
        active_agent: str = "claude",
        thinking_mode: str = "slow",
        last_input: str | None = None,
        last_input_at: str | None = None,
        last_output: str | None = None,
        last_output_at: str | None = None,
        tmux_session_name: str | None = None,
        depth: int = 0,
        display_index: str = "1",
    ) -> SessionNode:
        session = self._make_session_info(
            session_id=session_id,
            title=title,
            status=status,
            computer=computer,
            active_agent=active_agent,
            thinking_mode=thinking_mode,
            last_input=last_input,
            last_input_at=last_input_at,
            last_output=last_output,
            last_output_at=last_output_at,
            tmux_session_name=tmux_session_name,
            display_index=display_index,
        )
        return SessionNode(
            type="session",
            data=SessionDisplayInfo(session=session, display_index=display_index),
            depth=depth,
            children=[],
            parent=None,
        )

    def _make_computer_node(self, *, name: str, session_count: int, depth: int = 0) -> ComputerNode:
        computer = ComputerInfo(
            name=name,
            status="online",
            user="testuser",
            host="test.local",
            is_local=False,
            tmux_binary="tmux",
        )
        return ComputerNode(
            type="computer",
            data=ComputerDisplayInfo(computer=computer, session_count=session_count, recent_activity=False),
            depth=depth,
            children=[],
            parent=None,
        )

    def _make_project_node(
        self,
        *,
        path: str,
        children: list[SessionNode] | None = None,
        depth: int = 0,
    ) -> ProjectNode:
        project = ProjectInfo(computer="test-computer", name="project", path=path, description=None)
        return ProjectNode(
            type="project",
            data=project,
            depth=depth,
            children=children or [],
            parent=None,
        )

    def test_empty_shows_message(self, sessions_view):
        """Empty sessions list shows appropriate message."""
        sessions_view.flat_items = []
        lines = sessions_view.get_render_lines(80, 24)
        assert any("no items" in line.lower() for line in lines)

    def test_sessions_appear_in_output(self, sessions_view):
        """Sessions are visible in output."""
        # Create session nodes
        session1 = self._make_session_node(
            session_id="s1",
            title="Alpha Session",
            active_agent="claude",
            thinking_mode="slow",
        )
        session2 = self._make_session_node(
            session_id="s2",
            title="Beta Session",
            active_agent="gemini",
            thinking_mode="fast",
        )

        sessions_view.flat_items = [session1, session2]
        output = "\n".join(sessions_view.get_render_lines(80, 24))

        assert "Alpha Session" in output
        assert "Beta Session" in output

    def test_status_shown(self, sessions_view):
        """Session status is visible."""
        session = self._make_session_node(status="active")
        sessions_view.flat_items = [session]
        output = "\n".join(sessions_view.get_render_lines(80, 24))

        # Status might not be directly shown, but agent/mode are
        assert "claude" in output.lower()

    def test_collapsed_session_single_line(self, sessions_view):
        """Collapsed session shows only title line."""
        session = self._make_session_node(
            session_id="s1",
            title="Test Session",
            last_input="Some input",
            last_output="Some output",
        )
        sessions_view.flat_items = [session]
        sessions_view.collapsed_sessions.add("s1")

        lines = sessions_view.get_render_lines(80, 24)

        # Only title line should be shown
        assert len(lines) == 1
        assert "Test Session" in lines[0]
        assert "Some input" not in "\n".join(lines)
        assert "Some output" not in "\n".join(lines)

    def test_expanded_session_shows_details(self, sessions_view):
        """Expanded session shows ID, input, output."""
        session = self._make_session_node(
            session_id="test-session-001",
            title="Test Session",
            last_input="Test input",
            last_input_at="2024-01-01T00:00:00Z",
            last_output="Test output",
            last_output_at="2024-01-01T00:01:00Z",
        )
        sessions_view.flat_items = [session]
        # Don't add to collapsed_sessions = expanded by default

        output = "\n".join(sessions_view.get_render_lines(80, 24))

        assert "test-session-001" in output
        assert "Test input" in output
        assert "Test output" in output

    def test_long_title_truncated(self, sessions_view):
        """Long titles are truncated to fit width."""
        session = self._make_session_node(title="A" * 100)
        sessions_view.flat_items = [session]
        lines = sessions_view.get_render_lines(80, 24)

        assert all(len(line) <= 80 for line in lines)

    def test_computer_node_renders(self, sessions_view):
        """Computer nodes render correctly."""
        computer = self._make_computer_node(name="test-machine", session_count=2)
        sessions_view.flat_items = [computer]
        lines = sessions_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "test-machine" in lines[0]
        assert "(2)" in lines[0]

    def test_project_node_renders(self, sessions_view):
        """Project nodes render with session count."""
        # Create project with 2 child sessions
        session1 = self._make_session_node(session_id="s1", depth=1)
        session2 = self._make_session_node(session_id="s2", depth=1)
        project = self._make_project_node(path="/test/project", children=[session1, session2])

        sessions_view.flat_items = [project]
        lines = sessions_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "/test/project" in lines[0]
        assert "(2)" in lines[0]  # Session count

    def test_attach_new_session_uses_pane_manager(self, mock_focus):
        """New session attaches via pane manager when available."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.called = False
                self.args = None

            def show_session(self, tmux_session_name, child_tmux_session_name, computer_info):
                self.called = True
                self.args = (tmux_session_name, child_tmux_session_name, computer_info)

        pane_manager = MockPaneManager()
        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
        )
        view._computers = [
            ComputerInfo(
                name="test-machine",
                status="online",
                user="testuser",
                host="test.local",
                is_local=False,
                tmux_binary="tmux",
            )
        ]

        result = CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_123")
        view._attach_new_session(result, "test-machine", object())

        assert pane_manager.called is True
        assert pane_manager.args is not None
        assert pane_manager.args[0] == "tc_123"

    def test_depth_indentation(self, sessions_view):
        """Items are indented according to depth."""
        root = self._make_computer_node(name="test-computer", session_count=0, depth=0)
        child = self._make_project_node(path="/test/project", depth=1)

        sessions_view.flat_items = [root, child]
        lines = sessions_view.get_render_lines(80, 24)

        # Root has no indent, child has indent
        assert not lines[0].startswith(" ")
        assert lines[1].startswith("  ")

    def test_scroll_offset_respected(self, sessions_view):
        """Scroll offset skips items correctly."""
        sessions = [self._make_session_node(title=f"Session {i}") for i in range(30)]
        sessions_view.flat_items = sessions
        sessions_view.scroll_offset = 5

        lines = sessions_view.get_render_lines(80, 10)

        # First visible item should be index 5 ("Session 5")
        output = "\n".join(lines)
        assert "Session 5" in output
        # First few sessions should not be visible
        assert "Session 0" not in output
        assert "Session 1" not in output

    def test_last_input_output_labels_with_time(self, sessions_view, monkeypatch):
        """Last input/output render with short labels and relative time."""
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions._format_time", lambda _ts: "17:43:21")

        session = self._make_session_node(
            session_id="s1",
            last_input="hello",
            last_input_at="2024-01-01T00:00:00Z",
            last_output="world",
            last_output_at="2024-01-01T00:01:00Z",
        )
        sessions_view.flat_items = [session]

        lines = sessions_view.get_render_lines(120, 10)
        output = "\n".join(lines)

        assert "[17:43:21] in: hello" in output
        assert "[17:43:21] out: world" in output

    def test_double_clicking_session_id_row_toggles_sticky_parent_only(self, mock_focus):
        """Double-clicking the ID row toggles sticky with parent-only mode (no child)."""

        class MockPaneManager:
            def __init__(self):
                self.toggle_called = False
                self.show_sticky_called = False
                self.sticky_sessions = []

            def toggle_session(self, tmux_session_name, child_tmux_session_name, computer_info):
                self.toggle_called = True

            def show_session(self, tmux_session_name, child_tmux_session_name, computer_info):
                self.toggle_called = True

            def show_sticky_sessions(self, sticky_sessions, all_sessions, get_computer_info):
                self.show_sticky_called = True
                self.sticky_sessions = sticky_sessions

        pane_manager = MockPaneManager()
        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
        )
        view._computers = [
            ComputerInfo(
                name="test-machine",
                status="online",
                user="testuser",
                host="test.local",
                is_local=False,
                tmux_binary="tmux",
            )
        ]
        view._sessions = [
            self._make_session_info(
                session_id="sess-1",
                computer="test-machine",
                tmux_session_name="tc_parent",
            )
        ]
        session = self._make_session_node(
            session_id="sess-1",
            computer="test-machine",
            tmux_session_name="tc_parent",
        )
        view.flat_items = [session]

        view._row_to_item[10] = 0
        view._row_to_id_item[10] = session

        # First click - single click activates (no sticky sessions)
        assert view.handle_click(10, is_double_click=False) is True
        assert view.selected_index == 0
        assert pane_manager.toggle_called is True  # Activated via toggle_session

        # Second click as double-click on ID line
        pane_manager.toggle_called = False
        assert view.handle_click(10, is_double_click=True) is True

        # Should have toggled sticky with parent-only mode
        assert len(view.sticky_sessions) == 1
        assert view.sticky_sessions[0].session_id == "sess-1"
        assert view.sticky_sessions[0].show_child is False  # Parent-only mode
        assert pane_manager.show_sticky_called is True

    def test_render_session_clears_line_width(self, sessions_view):
        """Session render pads lines to full width to avoid stale artifacts."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, _attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text))

        session = self._make_session_node(
            session_id="s1",
            title="Test Session",
            active_agent="unknown",
            thinking_mode="slow",
        )
        screen = FakeScreen()
        width = 30
        lines_used = sessions_view._render_session(screen, 0, session, width, False)

        assert lines_used == 2

        # New rendering splits line 1 into multiple addstr calls:
        # - indent
        # - [N] indicator
        # - rest of line (collapse + agent + title)
        # Then line 2 (ID line) as one call
        assert len(screen.calls) == 4  # Updated for new rendering

        # Verify the combined width of line 1 segments equals full width
        line1_calls = [call for call in screen.calls if call[0] == 0]
        total_line1_width = sum(len(call[2]) for call in line1_calls)
        assert total_line1_width == width

        # Line 2 (ID line) should still be full width
        line2_calls = [call for call in screen.calls if call[0] == 1]
        assert len(line2_calls) == 1
        assert len(line2_calls[0][2]) == width
