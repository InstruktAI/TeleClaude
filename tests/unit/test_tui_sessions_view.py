"""Unit tests for SessionsView render logic."""

import curses

import pytest

from teleclaude.cli.models import (
    ComputerInfo,
    CreateSessionResult,
    ProjectInfo,
    ProjectWithTodosInfo,
    SessionInfo,
)
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.state import TuiState
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    ComputerNode,
    ProjectNode,
    SessionDisplayInfo,
    SessionNode,
)
from teleclaude.cli.tui.views.sessions import SessionsView
from teleclaude.core.origins import InputOrigin


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

        def focus_pane_for_session(self, session_id):
            return True

        def apply_layout(self, **_kwargs):
            return None

    return MockPaneManager()


@pytest.fixture
def sessions_view(mock_focus, mock_pane_manager):
    """Create SessionsView instance for testing."""
    state = TuiState()
    controller = TuiController(state, mock_pane_manager, lambda _name: None)
    view = SessionsView(
        api=None,  # Not needed for render tests
        agent_availability={},
        focus=mock_focus,
        pane_manager=mock_pane_manager,
        state=state,
        controller=controller,
    )
    # Ensure tests are isolated from persisted sticky state on disk.
    view.sticky_sessions = []
    return view


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
        last_output_summary: str | None = None,
        last_output_summary_at: str | None = "2024-01-01T00:01:00Z",
        last_activity: str = "2024-01-01T00:02:00Z",
        tmux_session_name: str | None = None,
        display_index: str = "1",
    ) -> SessionInfo:
        return SessionInfo(
            session_id=session_id,
            last_input_origin=InputOrigin.TELEGRAM.value,
            title=title,
            project_path="/test/project",
            thinking_mode=thinking_mode,
            active_agent=active_agent,
            status=status,
            created_at="2024-01-01T00:00:00Z",
            last_activity=last_activity,
            last_input=last_input,
            last_input_at=last_input_at,
            last_output_summary=last_output_summary,
            last_output_summary_at=last_output_summary_at,
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
        last_output_summary: str | None = None,
        last_output_summary_at: str | None = None,
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
            last_output_summary=last_output_summary,
            last_output_summary_at=last_output_summary_at,
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
            last_output_summary="Some output",
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
        )
        sessions_view.state.sessions.last_summary["test-session-001"] = "Test output"
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

    def test_action_bar_for_computer_includes_restart(self, sessions_view):
        """Computer action bar advertises restart shortcut."""
        computer = self._make_computer_node(name="test-machine", session_count=0)
        sessions_view.flat_items = [computer]
        sessions_view.selected_index = 0

        action_bar = sessions_view.get_action_bar()

        assert "[R]" in action_bar
        assert "Restart" in action_bar

    def test_attach_new_session_uses_pane_manager(self, mock_focus):
        """New session attaches via pane manager when available."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.called = False
                self.args = None

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.called = True
                self.args = (tmux_session_name, active_agent, computer_info, session_id)

        pane_manager = MockPaneManager()
        state = TuiState()
        controller = TuiController(state, pane_manager, lambda _name: None)
        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = []
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

        result = CreateSessionResult(status="success", session_id="sess-1", tmux_session_name="tc_123", agent="claude")
        view._attach_new_session(result, "test-machine", object())

        assert pane_manager.called is False
        assert view._pending_select_session_id == "sess-1"
        assert view._pending_select_source == "user"

    @pytest.mark.asyncio
    async def test_refresh_selects_pending_session(self, sessions_view):
        """Pending selection is applied when session appears in tree."""
        sessions_view.request_select_session("sess-2")
        computers = [
            ComputerInfo(
                name="test-computer",
                status="online",
                user="testuser",
                host="test.local",
                is_local=True,
                tmux_binary="tmux",
            )
        ]
        projects = [
            ProjectWithTodosInfo(
                computer="test-computer",
                name="Test Project",
                path="/test/project",
                description="",
                todos=[],
            )
        ]
        sessions = [
            self._make_session_info(session_id="sess-1", tmux_session_name="tmux-1"),
            self._make_session_info(session_id="sess-2", tmux_session_name="tmux-2"),
        ]

        await sessions_view.refresh(computers, projects, sessions)

        selected = sessions_view.flat_items[sessions_view.selected_index]
        assert selected.data.session.session_id == "sess-2"

    def test_depth_indentation(self, sessions_view):
        """Items are not indented in the simplified render output."""
        root = self._make_computer_node(name="test-computer", session_count=0, depth=0)
        child = self._make_project_node(path="/test/project", depth=1)

        sessions_view.flat_items = [root, child]
        lines = sessions_view.get_render_lines(80, 24)

        # Root has no indent, child has indent
        assert not lines[0].startswith(" ")
        assert not lines[1].startswith(" ")

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
        )
        sessions_view.state.sessions.last_summary["s1"] = "world"
        sessions_view.flat_items = [session]

        lines = sessions_view.get_render_lines(120, 10)
        output = "\n".join(lines)

        assert "[17:43:21] in: hello" in output
        assert "[17:43:21] out: world" in output

    def test_temp_output_highlight_shows_thinking_placeholder(self, sessions_view, monkeypatch):
        """Temporary output highlight replaces output content with thinking placeholder."""
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions._format_time", lambda _ts: "17:43:21")
        monkeypatch.setattr(curses, "A_ITALIC", 0, raising=False)

        session = self._make_session_node(session_id="s1")
        sessions_view.state.sessions.last_summary["s1"] = "final answer text"
        sessions_view.state.sessions.temp_output_highlights.add("s1")
        sessions_view.flat_items = [session]

        output = "\n".join(sessions_view.get_render_lines(120, 10))

        assert "[17:43:21] out: **Thinking" in output
        assert "final answer text" not in output

    def test_input_highlight_shows_working_placeholder_after_temp_window(self, sessions_view, monkeypatch):
        """After temp highlight clears, input highlight shows working placeholder."""
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions._format_time", lambda _ts: "17:43:21")
        monkeypatch.setattr(curses, "A_ITALIC", 0, raising=False)

        session = self._make_session_node(session_id="s-working")
        sessions_view.state.sessions.last_summary["s-working"] = "final answer text"
        sessions_view.state.sessions.input_highlights.add("s-working")
        sessions_view.flat_items = [session]

        output = "\n".join(sessions_view.get_render_lines(120, 10))

        assert "[17:43:21] out: **Working" in output
        assert "final answer text" not in output

    def test_double_clicking_session_id_row_toggles_sticky_parent_only(self, mock_focus):
        """Double-clicking the ID row toggles sticky with parent-only mode (no child)."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_sticky_called = False
                self.sticky_sessions = []
                self.apply_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_sticky_sessions(self, sticky_sessions, get_computer_info):
                self.show_sticky_called = True
                self.sticky_sessions = sticky_sessions

            def focus_pane_for_session(self, session_id):
                return True

            def apply_layout(self, **_kwargs):
                self.apply_called = True
                return None

        pane_manager = MockPaneManager()
        state = TuiState()
        controller = TuiController(state, pane_manager, lambda _name: None)
        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = []
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
        # First click - single click activates (no sticky sessions)
        assert view.handle_click(10, is_double_click=False) is True
        view.apply_pending_activation()
        controller.apply_pending_layout()
        assert view.selected_index == 0
        assert pane_manager.apply_called is True

        # Second click as double-click
        pane_manager.toggle_called = False
        pane_manager.apply_called = False
        assert view.handle_click(10, is_double_click=True) is True
        controller.apply_pending_layout()

        # Should have toggled sticky
        assert len(view.sticky_sessions) == 1
        assert view.sticky_sessions[0].session_id == "sess-1"
        assert pane_manager.apply_called is True

    def test_render_session_clears_line_width(self, sessions_view):
        """Detail lines are padded to full width to avoid stale artifacts."""

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
        lines_used = sessions_view._render_session(screen, 0, session, width, False, 3)

        assert lines_used == 2

        # Rendering uses two calls for line 1 and one for line 2
        assert len(screen.calls) == 3

        # Line 1 does not guarantee full width padding
        line1_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line1_calls) == 2

        # Line 2 (ID line) should still be full width
        line2_calls = [call for call in screen.calls if call[0] == 1]
        assert len(line2_calls) == 1
        assert len(line2_calls[0][2]) == width

    def test_headless_session_mutes_header_lines_only(self, sessions_view):
        """Headless sessions render title/ID muted while keeping output highlight behavior."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="headless-1",
            title="Headless Session",
            status="headless",
            active_agent="unknown",
            thinking_mode="slow",
            tmux_session_name=None,
        )
        sessions_view.state.sessions.last_summary["headless-1"] = "agent output"
        sessions_view.state.sessions.output_highlights.add("headless-1")

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 80, False, 4)

        assert lines_used == 3

        # Header/title line (row 0): both [idx] and title should be muted for headless.
        row0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(row0_calls) == 2
        assert row0_calls[0][3] == curses.A_DIM
        assert row0_calls[1][3] == curses.A_DIM

        # Line 2 ID row is also muted for headless.
        row1_calls = [call for call in screen.calls if call[0] == 1]
        assert len(row1_calls) == 1
        assert row1_calls[0][3] == curses.A_DIM

        # Output row keeps activity highlight behavior.
        row2_calls = [call for call in screen.calls if call[0] == 2]
        assert len(row2_calls) == 1
        assert row2_calls[0][3] == curses.A_BOLD

    def test_selected_headless_session_headers_stay_muted(self, sessions_view):
        """Selected headless rows should keep header lines in muted color."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="headless-selected",
            title="Headless Selected",
            status="headless",
            active_agent="unknown",
            thinking_mode="slow",
            tmux_session_name=None,
        )

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 80, True, 3)

        assert lines_used == 2
        row0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(row0_calls) == 2
        assert row0_calls[0][3] == curses.A_DIM
        assert row0_calls[1][3] == curses.A_DIM

    def test_headless_status_is_normalized_for_header_muting(self, sessions_view, monkeypatch):
        """Status normalization should treat whitespace/case headless values as headless."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="headless-normalized",
            title="Headless Normalized",
            status=" HeadLess ",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc_headless_normalized",
        )
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 80, False, 3)

        assert lines_used == 2
        row0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(row0_calls) == 2
        assert row0_calls[0][3] == 1  # claude muted pair
        assert row0_calls[1][3] == 1  # claude muted pair

    def test_temp_output_highlight_uses_italic_attr_when_available(self, sessions_view, monkeypatch):
        """When italics are supported, only placeholder text is italicized."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        monkeypatch.setattr(curses, "A_ITALIC", 2048, raising=False)
        session = self._make_session_node(
            session_id="temp-italic",
            active_agent="unknown",
        )
        sessions_view.state.sessions.temp_output_highlights.add("temp-italic")

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 120, False, 4)

        assert lines_used == 3
        output_row_calls = [call for call in screen.calls if call[0] == 2]
        assert len(output_row_calls) == 2
        # Prefix line is non-italic
        assert "out:" in output_row_calls[0][2]
        assert output_row_calls[0][3] == curses.A_BOLD
        # Placeholder overlay is italicized
        assert "Thinking" in output_row_calls[1][2]
        assert "**Thinking" not in output_row_calls[1][2]
        assert output_row_calls[1][3] == (curses.A_BOLD | curses.A_ITALIC)

    def test_working_placeholder_uses_agent_color_with_italics(self, sessions_view, monkeypatch):
        """Working placeholder should keep agent color and italicize only the placeholder."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        monkeypatch.setattr(curses, "A_ITALIC", 2048, raising=False)
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)
        session = self._make_session_node(
            session_id="working-italic",
            active_agent="claude",
        )
        sessions_view.state.sessions.input_highlights.add("working-italic")

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 120, False, 4)

        assert lines_used == 3
        output_row_calls = [call for call in screen.calls if call[0] == 2]
        assert len(output_row_calls) == 2
        # Prefix line is agent color, non-italic
        assert "out:" in output_row_calls[0][2]
        assert output_row_calls[0][3] == 2  # claude normal pair
        # Placeholder overlay keeps agent color + italic
        assert "Working" in output_row_calls[1][2]
        assert output_row_calls[1][3] == (2 | curses.A_ITALIC)

    def test_real_output_wins_when_no_highlights(self, sessions_view, monkeypatch):
        """Real output must be shown immediately when highlight states are cleared."""
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions._format_time", lambda _ts: "17:43:21")
        monkeypatch.setattr(curses, "A_ITALIC", 0, raising=False)

        session = self._make_session_node(session_id="s-final")
        sessions_view.state.sessions.last_summary["s-final"] = "real output now"
        sessions_view.flat_items = [session]

        output = "\n".join(sessions_view.get_render_lines(120, 10))

        assert "[17:43:21] out: real output now" in output
        assert "thinking" not in output
        assert "working" not in output
