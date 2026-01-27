"""Unit tests for PreparationView render logic."""

import pytest

from teleclaude.cli.models import ComputerInfo, CreateSessionResult, ProjectWithTodosInfo
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.state import TuiState
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.views.preparation import (
    PreparationView,
    PrepComputerDisplayInfo,
    PrepComputerNode,
    PrepFileDisplayInfo,
    PrepFileNode,
    PrepProjectDisplayInfo,
    PrepProjectNode,
    PrepTodoDisplayInfo,
    PrepTodoNode,
)


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

    pane_manager = MockPaneManager()
    state = TuiState()
    controller = TuiController(state, pane_manager, lambda _name: None)
    return PreparationView(
        api=None,  # Not needed for render tests
        agent_availability={},
        focus=mock_focus,
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )


@pytest.mark.unit
class TestPreparationViewLogic:
    """Layer 1: View logic tests for PreparationView."""

    def _make_todo_node(
        self,
        *,
        slug: str,
        status: str,
        has_requirements: bool = False,
        has_impl_plan: bool = False,
        build_status: str | None = None,
        review_status: str | None = None,
        depth: int = 0,
    ) -> PrepTodoNode:
        todo = TodoItem(
            slug=slug,
            status=status,
            description=None,
            has_requirements=has_requirements,
            has_impl_plan=has_impl_plan,
            build_status=build_status,
            review_status=review_status,
        )
        return PrepTodoNode(
            type="todo",
            data=PrepTodoDisplayInfo(todo=todo, project_path="/test/project", computer="test-computer"),
            depth=depth,
        )

    def _make_computer_node(
        self,
        *,
        name: str,
        project_count: int,
        todo_count: int,
        depth: int = 0,
    ) -> PrepComputerNode:
        computer = ComputerInfo(
            name=name,
            status="online",
            user="testuser",
            host="test.local",
            is_local=False,
            tmux_binary="tmux",
        )
        return PrepComputerNode(
            type="computer",
            data=PrepComputerDisplayInfo(computer=computer, project_count=project_count, todo_count=todo_count),
            depth=depth,
        )

    def _make_project_node(
        self,
        *,
        path: str,
        children: list[PrepTodoNode] | None = None,
        depth: int = 0,
    ) -> PrepProjectNode:
        project = ProjectWithTodosInfo(
            computer="test-computer",
            name="project",
            path=path,
            description=None,
            todos=[],
        )
        return PrepProjectNode(
            type="project",
            data=PrepProjectDisplayInfo(project=project),
            depth=depth,
            children=children or [],
        )

    def _make_file_node(
        self,
        *,
        filename: str,
        display_name: str,
        exists: bool,
        index: int,
        depth: int = 2,
    ) -> PrepFileNode:
        return PrepFileNode(
            type="file",
            data=PrepFileDisplayInfo(
                filename=filename,
                display_name=display_name,
                exists=exists,
                index=index,
                slug="test-todo",
                project_path="/test/project",
                computer="test-computer",
            ),
            depth=depth,
        )

    def test_empty_shows_message(self, prep_view):
        """Empty todos list shows appropriate message."""
        prep_view.flat_items = []
        lines = prep_view.get_render_lines(80, 24)
        assert any("no items" in line.lower() for line in lines)

    def test_ready_status_shown(self, prep_view):
        """Ready status indicator is shown."""
        todo = self._make_todo_node(slug="test-todo", status="ready", has_requirements=True, has_impl_plan=True)
        prep_view.flat_items = [todo]
        output = "\n".join(prep_view.get_render_lines(80, 24))

        assert "[.]" in output or "ready" in output.lower()

    def test_pending_status_shown(self, prep_view):
        """Pending status indicator is shown."""
        todo = self._make_todo_node(slug="test-todo", status="pending")
        prep_view.flat_items = [todo]
        output = "\n".join(prep_view.get_render_lines(80, 24))

        assert "[ ]" in output or "pending" in output.lower()

    def test_in_progress_status_shown(self, prep_view):
        """In-progress status indicator is shown."""
        todo = self._make_todo_node(slug="test-todo", status="in_progress", has_requirements=True, has_impl_plan=True)
        prep_view.flat_items = [todo]
        output = "\n".join(prep_view.get_render_lines(80, 24))

        assert "[>]" in output or "in_progress" in output.lower()

    def test_build_review_status_shown(self, prep_view):
        """Build and review status are shown if available."""
        todo = self._make_todo_node(
            slug="test-todo",
            status="in_progress",
            build_status="complete",
            review_status="pending",
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
        computer = self._make_computer_node(name="test-machine", project_count=3, todo_count=7)
        prep_view.flat_items = [computer]
        lines = prep_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "🖥" in lines[0]
        assert "test-machine" in lines[0]
        assert "(3)" in lines[0]

    def test_project_node_renders(self, prep_view):
        """Project nodes render with todo count."""
        # Create project with 2 child todos
        todo1 = self._make_todo_node(slug="todo1", status="pending", depth=1)
        todo2 = self._make_todo_node(slug="todo2", status="ready", depth=1)
        project = self._make_project_node(path="/test/project", children=[todo1, todo2])

        prep_view.flat_items = [project]
        lines = prep_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "📁" in lines[0]
        assert "/test/project" in lines[0]
        assert "(2)" in lines[0]  # Todo count

    def test_attach_new_session_uses_pane_manager(self, mock_focus):
        """New session attaches via pane manager when available."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.called = False
                self.args = None

            def show_session(
                self, tmux_session_name, active_agent, child_tmux_session_name, computer_info, session_id=None
            ):
                self.called = True
                self.args = (tmux_session_name, active_agent, child_tmux_session_name, computer_info, session_id)

        pane_manager = MockPaneManager()
        state = TuiState()
        controller = TuiController(state, pane_manager, lambda _name: None)
        view = PreparationView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
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

        result = CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_456", agent="claude")
        view._attach_new_session(result, "test-machine", object())

        assert pane_manager.called is True
        assert pane_manager.args is not None
        assert pane_manager.args[0] == "tc_456"
        assert pane_manager.args[1] == "claude"

    def test_file_node_renders(self, prep_view):
        """File nodes render with index and name."""
        file_node = self._make_file_node(
            filename="requirements.md",
            display_name="Requirements",
            exists=True,
            index=1,
        )
        prep_view.flat_items = [file_node]
        lines = prep_view.get_render_lines(80, 24)

        assert len(lines) == 1
        assert "1. Requirements" in lines[0]

    def test_collapsed_todo_no_files(self, prep_view):
        """Collapsed todo doesn't show file children."""
        todo = self._make_todo_node(slug="test-todo", status="pending")
        prep_view.flat_items = [todo]
        # Don't add to expanded_todos = collapsed by default

        lines = prep_view.get_render_lines(80, 24)

        # Only todo line, no file lines
        assert len(lines) == 1
        assert "test-todo" in lines[0]

    def test_depth_indentation(self, prep_view):
        """Items are indented according to depth."""
        computer = self._make_computer_node(name="test-computer", project_count=0, todo_count=0, depth=0)
        project = self._make_project_node(path="/test/project", depth=1)
        todo = self._make_todo_node(slug="test", status="pending", depth=2)

        prep_view.flat_items = [computer, project, todo]
        lines = prep_view.get_render_lines(80, 24)

        # Each level adds 2 spaces
        assert not lines[0].startswith(" ")
        assert lines[1].startswith("  ")
        assert lines[2].startswith("    ")

    def test_long_content_truncated(self, prep_view):
        """Long content is truncated to fit width."""
        todo = self._make_todo_node(slug="A" * 100, status="pending")
        prep_view.flat_items = [todo]
        lines = prep_view.get_render_lines(80, 24)

        assert all(len(line) <= 80 for line in lines)

    def test_scroll_offset_respected(self, prep_view):
        """Scroll offset skips items correctly."""
        todos = [self._make_todo_node(slug=f"todo-{i:02d}", status="pending") for i in range(30)]
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
        todos = [self._make_todo_node(slug=f"todo-{i}", status="pending") for i in range(100)]
        prep_view.flat_items = todos

        lines = prep_view.get_render_lines(80, 10)

        # Should not exceed height
        assert len(lines) <= 10
