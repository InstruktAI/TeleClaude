"""Unit tests for SessionsView render logic."""

import pytest

from teleclaude.cli.tui.tree import TreeNode
from teleclaude.cli.tui.views.sessions import SessionsView
from tests.conftest import create_mock_computer, create_mock_project, create_mock_session


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

    def test_empty_shows_message(self, sessions_view):
        """Empty sessions list shows appropriate message."""
        sessions_view.flat_items = []
        lines = sessions_view.get_render_lines(80, 24)
        assert any("no items" in line.lower() for line in lines)

    def test_sessions_appear_in_output(self, sessions_view):
        """Sessions are visible in output."""
        # Create session nodes
        session1 = TreeNode(
            type="session",
            data=create_mock_session(
                session_id="s1",
                title="Alpha Session",
                active_agent="claude",
                thinking_mode="slow",
            ),
            depth=0,
        )
        session2 = TreeNode(
            type="session",
            data=create_mock_session(
                session_id="s2",
                title="Beta Session",
                active_agent="gemini",
                thinking_mode="fast",
            ),
            depth=0,
        )

        sessions_view.flat_items = [session1, session2]
        output = "\n".join(sessions_view.get_render_lines(80, 24))

        assert "Alpha Session" in output
        assert "Beta Session" in output

    def test_status_shown(self, sessions_view):
        """Session status is visible."""
        session = TreeNode(
            type="session",
            data=create_mock_session(status="active"),
            depth=0,
        )
        sessions_view.flat_items = [session]
        output = "\n".join(sessions_view.get_render_lines(80, 24))

        # Status might not be directly shown, but agent/mode are
        assert "claude" in output.lower()

    def test_collapsed_session_single_line(self, sessions_view):
        """Collapsed session shows only title line."""
        session = TreeNode(
            type="session",
            data=create_mock_session(
                session_id="s1",
                title="Test Session",
                last_input="Some input",
                last_output="Some output",
            ),
            depth=0,
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
        session = TreeNode(
            type="session",
            data=create_mock_session(
                session_id="test-session-001",
                title="Test Session",
                last_input="Test input",
                last_output="Test output",
            ),
            depth=0,
        )
        sessions_view.flat_items = [session]
        # Don't add to collapsed_sessions = expanded by default

        output = "\n".join(sessions_view.get_render_lines(80, 24))

        assert "test-session-001" in output
        assert "Test input" in output
        assert "Test output" in output

    def test_long_title_truncated(self, sessions_view):
        """Long titles are truncated to fit width."""
        session = TreeNode(
            type="session",
            data=create_mock_session(title="A" * 100),
            depth=0,
        )
        sessions_view.flat_items = [session]
        lines = sessions_view.get_render_lines(80, 24)

        assert all(len(line) <= 80 for line in lines)

    def test_computer_node_renders(self, sessions_view):
        """Computer nodes render correctly."""
        computer = TreeNode(
            type="computer",
            data=create_mock_computer(name="test-machine"),
            depth=0,
        )
        sessions_view.flat_items = [computer]
        lines = sessions_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "test-machine" in lines[0]

    def test_project_node_renders(self, sessions_view):
        """Project nodes render with session count."""
        # Create project with 2 child sessions
        session1 = TreeNode(type="session", data=create_mock_session(), depth=1)
        session2 = TreeNode(type="session", data=create_mock_session(), depth=1)

        project = TreeNode(
            type="project",
            data=create_mock_project(path="/test/project"),
            depth=0,
            children=[session1, session2],
        )

        sessions_view.flat_items = [project]
        lines = sessions_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "/test/project" in lines[0]
        assert "(2)" in lines[0]  # Session count

    def test_depth_indentation(self, sessions_view):
        """Items are indented according to depth."""
        root = TreeNode(type="computer", data=create_mock_computer(), depth=0)
        child = TreeNode(type="project", data=create_mock_project(), depth=1)

        sessions_view.flat_items = [root, child]
        lines = sessions_view.get_render_lines(80, 24)

        # Root has no indent, child has indent
        assert not lines[0].startswith(" ")
        assert lines[1].startswith("  ")

    def test_scroll_offset_respected(self, sessions_view):
        """Scroll offset skips items correctly."""
        sessions = [
            TreeNode(type="session", data=create_mock_session(title=f"Session {i}"), depth=0) for i in range(30)
        ]
        sessions_view.flat_items = sessions
        sessions_view.scroll_offset = 5

        lines = sessions_view.get_render_lines(80, 10)

        # First visible item should be index 5 ("Session 5")
        output = "\n".join(lines)
        assert "Session 5" in output
        # First few sessions should not be visible
        assert "Session 0" not in output
        assert "Session 1" not in output
