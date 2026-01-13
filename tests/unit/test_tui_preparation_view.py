"""Unit tests for PreparationView render logic."""

import pytest

from teleclaude.cli.tui.views.preparation import PreparationView, PrepTreeNode
from tests.conftest import create_mock_computer, create_mock_project


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
def prep_view(mock_focus):
    """Create PreparationView instance for testing."""

    class MockPaneManager:
        @property
        def is_available(self) -> bool:
            return False

    return PreparationView(
        api=None,  # Not needed for render tests
        agent_availability={},
        focus=mock_focus,
        pane_manager=MockPaneManager(),
    )


@pytest.mark.unit
class TestPreparationViewLogic:
    """Layer 1: View logic tests for PreparationView."""

    def test_empty_shows_message(self, prep_view):
        """Empty todos list shows appropriate message."""
        prep_view.flat_items = []
        lines = prep_view.get_render_lines(80, 24)
        assert any("no items" in line.lower() for line in lines)

    def test_ready_status_shown(self, prep_view):
        """Ready status indicator is shown."""
        todo = PrepTreeNode(
            type="todo",
            data={
                "slug": "test-todo",
                "status": "ready",
                "has_requirements": True,
                "has_impl_plan": True,
            },
            depth=0,
        )
        prep_view.flat_items = [todo]
        output = "\n".join(prep_view.get_render_lines(80, 24))

        assert "[.]" in output or "ready" in output.lower()

    def test_pending_status_shown(self, prep_view):
        """Pending status indicator is shown."""
        todo = PrepTreeNode(
            type="todo",
            data={
                "slug": "test-todo",
                "status": "pending",
                "has_requirements": False,
                "has_impl_plan": False,
            },
            depth=0,
        )
        prep_view.flat_items = [todo]
        output = "\n".join(prep_view.get_render_lines(80, 24))

        assert "[ ]" in output or "pending" in output.lower()

    def test_in_progress_status_shown(self, prep_view):
        """In-progress status indicator is shown."""
        todo = PrepTreeNode(
            type="todo",
            data={
                "slug": "test-todo",
                "status": "in_progress",
                "has_requirements": True,
                "has_impl_plan": True,
            },
            depth=0,
        )
        prep_view.flat_items = [todo]
        output = "\n".join(prep_view.get_render_lines(80, 24))

        assert "[>]" in output or "in_progress" in output.lower()

    def test_build_review_status_shown(self, prep_view):
        """Build and review status are shown if available."""
        todo = PrepTreeNode(
            type="todo",
            data={
                "slug": "test-todo",
                "status": "in_progress",
                "build_status": "complete",
                "review_status": "pending",
            },
            depth=0,
        )
        prep_view.flat_items = [todo]
        lines = prep_view.get_render_lines(80, 24)

        # Should have 2 lines: title + status line
        assert len(lines) == 2
        output = "\n".join(lines)
        assert "Build: complete" in output
        assert "Review: pending" in output

    def test_computer_node_renders(self, prep_view):
        """Computer nodes render correctly."""
        computer = PrepTreeNode(
            type="computer",
            data={
                **create_mock_computer(name="test-machine"),
                "project_count": 3,
                "todo_count": 7,
            },
            depth=0,
        )
        prep_view.flat_items = [computer]
        lines = prep_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "[C]" in lines[0]
        assert "test-machine" in lines[0]
        assert "(3)" in lines[0]

    def test_project_node_renders(self, prep_view):
        """Project nodes render with todo count."""
        # Create project with 2 child todos
        todo1 = PrepTreeNode(type="todo", data={"slug": "todo1", "status": "pending"}, depth=1)
        todo2 = PrepTreeNode(type="todo", data={"slug": "todo2", "status": "ready"}, depth=1)

        project = PrepTreeNode(
            type="project",
            data=create_mock_project(path="/test/project"),
            depth=0,
            children=[todo1, todo2],
        )

        prep_view.flat_items = [project]
        lines = prep_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "[P]" in lines[0]
        assert "/test/project" in lines[0]
        assert "(2)" in lines[0]  # Todo count

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
        view = PreparationView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
        )
        view._computers = [create_mock_computer(name="test-machine")]

        view._attach_new_session({"tmux_session_name": "tc_456"}, "test-machine", object())

        assert pane_manager.called is True
        assert pane_manager.args is not None
        assert pane_manager.args[0] == "tc_456"

    def test_file_node_renders(self, prep_view):
        """File nodes render with index and name."""
        file_node = PrepTreeNode(
            type="file",
            data={
                "filename": "requirements.md",
                "display_name": "Requirements",
                "exists": True,
                "index": 1,
            },
            depth=2,
        )
        prep_view.flat_items = [file_node]
        lines = prep_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "1. Requirements" in lines[0]

    def test_collapsed_todo_no_files(self, prep_view):
        """Collapsed todo doesn't show file children."""
        todo = PrepTreeNode(
            type="todo",
            data={"slug": "test-todo", "status": "pending"},
            depth=0,
        )
        prep_view.flat_items = [todo]
        # Don't add to expanded_todos = collapsed by default

        lines = prep_view.get_render_lines(80, 24)

        # Only todo line, no file lines
        assert len(lines) == 1
        assert "test-todo" in lines[0]

    def test_depth_indentation(self, prep_view):
        """Items are indented according to depth."""
        computer = PrepTreeNode(type="computer", data=create_mock_computer(), depth=0)
        project = PrepTreeNode(type="project", data=create_mock_project(), depth=1)
        todo = PrepTreeNode(type="todo", data={"slug": "test", "status": "pending"}, depth=2)

        prep_view.flat_items = [computer, project, todo]
        lines = prep_view.get_render_lines(80, 24)

        # Each level adds 2 spaces
        assert not lines[0].startswith(" ")
        assert lines[1].startswith("  ")
        assert lines[2].startswith("    ")

    def test_long_content_truncated(self, prep_view):
        """Long content is truncated to fit width."""
        todo = PrepTreeNode(
            type="todo",
            data={"slug": "A" * 100, "status": "pending"},
            depth=0,
        )
        prep_view.flat_items = [todo]
        lines = prep_view.get_render_lines(80, 24)

        assert all(len(line) <= 80 for line in lines)

    def test_scroll_offset_respected(self, prep_view):
        """Scroll offset skips items correctly."""
        todos = [
            PrepTreeNode(type="todo", data={"slug": f"todo-{i:02d}", "status": "pending"}, depth=0) for i in range(30)
        ]
        prep_view.flat_items = todos
        prep_view.scroll_offset = 5

        lines = prep_view.get_render_lines(80, 10)

        # First visible item should be index 5 ("todo-05")
        output = "\n".join(lines)
        assert "todo-05" in output
        # First few todos should not be visible
        assert "todo-00" not in output
        assert "todo-01" not in output

    def test_height_limit_respected(self, prep_view):
        """Output respects height limit."""
        todos = [
            PrepTreeNode(type="todo", data={"slug": f"todo-{i}", "status": "pending"}, depth=0) for i in range(100)
        ]
        prep_view.flat_items = todos

        lines = prep_view.get_render_lines(80, 10)

        # Should not exceed height
        assert len(lines) <= 10
