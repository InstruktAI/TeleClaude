"""Unit tests for SessionsView render logic."""

import curses
import time

import pytest

from teleclaude.cli.models import (
    ComputerInfo,
    CreateSessionResult,
    ProjectInfo,
    ProjectWithTodosInfo,
    SessionInfo,
)
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.state import Intent, IntentType, PreviewState, TuiState
from teleclaude.cli.tui.theme import get_sticky_badge_attr
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    ComputerNode,
    ProjectNode,
    SessionDisplayInfo,
    SessionNode,
)
from teleclaude.cli.tui.types import StickySessionInfo
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

    @pytest.mark.asyncio
    async def test_refresh_backfills_last_summary_from_session_data(self, sessions_view):
        """Refresh should repopulate last_summary from persisted session summaries."""
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
            self._make_session_info(
                session_id="sess-summary",
                tmux_session_name="tmux-summary",
                last_output_summary="persisted summary text",
            )
        ]

        await sessions_view.refresh(computers, projects, sessions)

        assert sessions_view.state.sessions.last_summary["sess-summary"] == "persisted summary text"

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

    def test_temp_output_highlight_shows_working_placeholder_for_codex(self, sessions_view, monkeypatch):
        """Codex temp output highlight should show working placeholder for synthetic start."""
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions._format_time", lambda _ts: "17:43:21")
        monkeypatch.setattr(curses, "A_ITALIC", 0, raising=False)

        session = self._make_session_node(session_id="s-codex-temp", active_agent="codex")
        sessions_view.state.sessions.last_summary["s-codex-temp"] = "final answer text"
        sessions_view.state.sessions.temp_output_highlights.add("s-codex-temp")
        sessions_view.flat_items = [session]

        output = "\n".join(sessions_view.get_render_lines(120, 10))

        assert "[17:43:21] out: **...**" in output
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

        assert "[17:43:21] out: **...**" in output
        assert "final answer text" not in output

    def test_codex_input_highlight_preserves_last_output(self, sessions_view, monkeypatch):
        """Codex sessions should follow the same event-driven Working placeholder behavior."""
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions._format_time", lambda _ts: "17:43:21")
        monkeypatch.setattr(curses, "A_ITALIC", 0, raising=False)

        session = self._make_session_node(session_id="s-codex-input", active_agent="codex")
        sessions_view.state.sessions.last_summary["s-codex-input"] = "latest codex answer"
        sessions_view.state.sessions.input_highlights.add("s-codex-input")
        sessions_view.flat_items = [session]

        output = "\n".join(sessions_view.get_render_lines(120, 10))

        assert "[17:43:21] out: **...**" in output
        assert "latest codex answer" not in output

    def test_double_clicking_session_id_row_toggles_sticky_parent_only(self, mock_focus):
        """Double-clicking the ID row toggles sticky with parent-only mode (no child)."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.show_sticky_called = False
                self.sticky_sessions = []
                self.apply_called = False
                self.focus_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.show_session_called = True

            def show_sticky_sessions(self, sticky_sessions, get_computer_info):
                self.show_sticky_called = True
                self.sticky_sessions = sticky_sessions

            def focus_pane_for_session(self, session_id):
                self.focus_called = True
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
        # First click should select, while keeping focus in the tree.
        assert view.handle_click(10, is_double_click=False) is True
        view.apply_pending_activation()
        controller.apply_pending_layout()
        assert view.selected_index == 0
        assert view.state.sessions.preview == PreviewState(session_id="sess-1")
        assert pane_manager.focus_called is False

        # Second click as double-click
        pane_manager.toggle_called = False
        pane_manager.apply_called = False
        pane_manager.focus_called = False
        assert view.handle_click(10, is_double_click=True) is True
        controller.apply_pending_layout()

        # Should have toggled sticky
        assert len(view.sticky_sessions) == 1
        assert view.sticky_sessions[0].session_id == "sess-1"
        assert pane_manager.focus_called is False

    def test_click_session_preview_works_with_duplicate_sticky_state(self, mock_focus):
        """Single click preview should work even with duplicated sticky entries."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                pass

            def show_session(self, *_args, **_kwargs):
                pass

            def focus_pane_for_session(self, _session_id):
                self.focus_called = True
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
        view.sticky_sessions = [
            StickySessionInfo("sticky-a"),
            StickySessionInfo("sticky-a"),
            StickySessionInfo("sticky-b"),
        ]
        view.flat_items = [
            self._make_session_node(
                session_id="preview-session",
                computer="local-machine",
                tmux_session_name="tc-preview",
            )
        ]
        view._row_to_item[10] = 0
        view._computers = [
            ComputerInfo(
                name="local-machine",
                status="online",
                user="me",
                host="local",
                is_local=True,
                tmux_binary="tmux",
            )
        ]

        assert view.handle_click(10, is_double_click=False) is True
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.state.sessions.preview == PreviewState(session_id="preview-session")
        assert pane_manager.focus_called is False

    def test_space_activates_sticky_session(self, mock_focus):
        """Space on a sticky session should only move highlight in the tree."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.apply_called = False
                self.focus_called = False

            def toggle_session(self, *_args, **_kwargs):
                self.toggle_called = True

            def show_session(self, *_args, **_kwargs):
                self.show_session_called = True

            def focus_pane_for_session(self, _session_id):
                self.focus_called = True
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
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view.selected_index = 0

        view.handle_key(ord(" "), None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert len(view.sticky_sessions) == 1
        assert view.sticky_sessions[0].session_id == "sess-sticky"
        assert view.state.sessions.preview is None
        assert pane_manager.focus_called is False

    def test_space_on_sticky_session_clears_active_preview_via_clear_preview_intent(self, mock_focus):
        """Space on a sticky session should dispatch CLEAR_PREVIEW instead of SET_PREVIEW."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                return None

            def show_session(self, *_args, **_kwargs):
                return None

            def focus_pane_for_session(self, _session_id):
                return True

            def apply_layout(self, **_kwargs):
                self.apply_called = True
                return None

        pane_manager = MockPaneManager()
        state = TuiState()
        state.sessions.preview = PreviewState(session_id="previewed-other")
        controller = TuiController(state, pane_manager, lambda _name: None)
        original_dispatch = controller.dispatch
        dispatched_intents = []

        def recording_dispatch(intent: Intent, defer_layout: bool = False) -> None:
            dispatched_intents.append(intent.type)
            return original_dispatch(intent, defer_layout=defer_layout)

        controller.dispatch = recording_dispatch

        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view.selected_index = 0

        view.handle_key(ord(" "), None)

        assert view.state.sessions.preview is None
        assert IntentType.CLEAR_PREVIEW in dispatched_intents
        assert IntentType.SET_PREVIEW not in dispatched_intents
        assert IntentType.SET_SELECTION in dispatched_intents
        assert view._pending_activate_request is None

    def test_click_on_sticky_session_clears_active_preview_via_intent(self, mock_focus):
        """Single click on a sticky row should clear active preview with clear-preview intent."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                return None

            def show_session(self, *_args, **_kwargs):
                return None

            def focus_pane_for_session(self, _session_id):
                return True

            def apply_layout(self, **_kwargs):
                self.apply_called = True
                return None

        pane_manager = MockPaneManager()
        state = TuiState()
        state.sessions.preview = PreviewState(session_id="previewed-other")
        controller = TuiController(state, pane_manager, lambda _name: None)
        original_dispatch = controller.dispatch
        dispatched_intents = []

        def recording_dispatch(intent: Intent, defer_layout: bool = False) -> None:
            dispatched_intents.append(intent.type)
            return original_dispatch(intent, defer_layout=defer_layout)

        controller.dispatch = recording_dispatch

        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view._row_to_item[10] = 0
        view._computers = [
            ComputerInfo(
                name="local-machine",
                status="online",
                user="me",
                host="local",
                is_local=True,
                tmux_binary="tmux",
            )
        ]

        assert view.handle_click(10, is_double_click=False) is True
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.state.sessions.preview is None
        assert IntentType.CLEAR_PREVIEW in dispatched_intents
        assert IntentType.SET_PREVIEW not in dispatched_intents
        assert IntentType.SET_SELECTION in dispatched_intents
        assert view.selected_index == 0

    def test_double_click_sticky_session_toggles_off_and_clears_preview(self, mock_focus):
        """Double click on a sticky row should remove sticky state and keep preview cleared."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                return None

            def show_session(self, *_args, **_kwargs):
                return None

            def focus_pane_for_session(self, _session_id):
                return True

            def apply_layout(self, **_kwargs):
                self.apply_called = True
                return None

        pane_manager = MockPaneManager()
        state = TuiState()
        state.sessions.preview = PreviewState(session_id="previewed-other")
        controller = TuiController(state, pane_manager, lambda _name: None)
        original_dispatch = controller.dispatch
        dispatched_intents = []

        def recording_dispatch(intent: Intent, defer_layout: bool = False) -> None:
            dispatched_intents.append(intent.type)
            return original_dispatch(intent, defer_layout=defer_layout)

        controller.dispatch = recording_dispatch

        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view._row_to_item[10] = 0
        view._computers = [
            ComputerInfo(
                name="local-machine",
                status="online",
                user="me",
                host="local",
                is_local=True,
                tmux_binary="tmux",
            )
        ]

        assert view.handle_click(10, is_double_click=True) is True
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert len(view.sticky_sessions) == 0
        assert view.state.sessions.preview is None
        assert IntentType.CLEAR_PREVIEW in dispatched_intents
        assert IntentType.TOGGLE_STICKY in dispatched_intents
        assert IntentType.SET_PREVIEW not in dispatched_intents

    def test_double_space_on_sticky_session_toggles_off(self, mock_focus, monkeypatch):
        """Double Space on a sticky row should remove sticky state and clear preview."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                return None

            def show_session(self, *_args, **_kwargs):
                return None

            def focus_pane_for_session(self, _session_id):
                return True

            def apply_layout(self, **_kwargs):
                self.apply_called = True
                return None

        pane_manager = MockPaneManager()
        state = TuiState()
        state.sessions.preview = PreviewState(session_id="previewed-other")
        controller = TuiController(state, pane_manager, lambda _name: None)
        original_dispatch = controller.dispatch
        dispatched_intents = []

        def recording_dispatch(intent: Intent, defer_layout: bool = False) -> None:
            dispatched_intents.append(intent.type)
            return original_dispatch(intent, defer_layout=defer_layout)

        controller.dispatch = recording_dispatch

        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view._sessions = [view.flat_items[0].data.session]
        view.selected_index = 0

        base_time = 1_000.0
        monkeypatch.setattr(time, "perf_counter", lambda: base_time)
        view.handle_key(ord(" "), None)
        monkeypatch.setattr(time, "perf_counter", lambda: base_time + 0.1)
        view.handle_key(ord(" "), None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert len(view.sticky_sessions) == 0
        assert view.state.sessions.preview is None
        assert IntentType.CLEAR_PREVIEW in dispatched_intents
        assert IntentType.TOGGLE_STICKY in dispatched_intents
        assert IntentType.SET_PREVIEW not in dispatched_intents

    def test_space_on_non_sticky_session_keeps_preview_request_flow(self, mock_focus):
        """Non-sticky Space should request preview without clearing current preview."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                return None

            def show_session(self, *_args, **_kwargs):
                return None

            def focus_pane_for_session(self, _session_id):
                return True

            def apply_layout(self, **_kwargs):
                self.apply_called = True
                return None

        pane_manager = MockPaneManager()
        state = TuiState()
        state.sessions.preview = PreviewState(session_id="previewed-other")
        controller = TuiController(state, pane_manager, lambda _name: None)
        original_dispatch = controller.dispatch
        dispatched_intents = []

        def recording_dispatch(intent: Intent, defer_layout: bool = False) -> None:
            dispatched_intents.append(intent.type)
            return original_dispatch(intent, defer_layout=defer_layout)

        controller.dispatch = recording_dispatch

        view = SessionsView(
            api=None,
            agent_availability={},
            focus=mock_focus,
            pane_manager=pane_manager,
            state=state,
            controller=controller,
        )
        view.sticky_sessions = []
        view.flat_items = [
            self._make_session_node(
                session_id="sess-nonsticky",
                computer="local-machine",
                tmux_session_name="tc-nonsticky",
            )
        ]
        view.selected_index = 0

        view.handle_key(ord(" "), None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.state.sessions.preview == PreviewState(session_id="sess-nonsticky")
        assert IntentType.CLEAR_PREVIEW not in dispatched_intents
        assert IntentType.SET_PREVIEW in dispatched_intents

    def test_click_sticky_session_activates_existing_pane(self, mock_focus):
        """Single click on a sticky session should not force pane focus."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.apply_called = False
                self.focus_called = False

            def toggle_session(self, *_args, **_kwargs):
                self.toggle_called = True

            def show_session(self, *_args, **_kwargs):
                self.show_session_called = True

            def focus_pane_for_session(self, _session_id):
                self.focus_called = True
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
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view._row_to_item[10] = 0
        view._computers = [
            ComputerInfo(
                name="local-machine",
                status="online",
                user="me",
                host="local",
                is_local=True,
                tmux_binary="tmux",
            )
        ]

        assert view.handle_click(10, is_double_click=False) is True
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.selected_index == 0
        assert view.state.sessions.preview is None
        assert pane_manager.focus_called is False

    def test_enter_focuses_preview_pane_for_session(self, mock_focus):
        """Pressing Enter on a session should request pane focus."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.show_session_called = True

            def focus_pane_for_session(self, session_id):
                self.focus_called = True
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
        view.flat_items = [
            self._make_session_node(
                session_id="sess-enter",
                computer="local-machine",
                tmux_session_name="tc-enter",
            )
        ]
        view.selected_index = 0

        view.handle_enter(None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.selected_index == 0
        assert pane_manager.focus_called is True
        assert pane_manager.apply_called is True

    def test_enter_on_sticky_session_reuses_existing_pane(self, mock_focus):
        """Pressing Enter on a sticky session should not create a new active preview."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                self.toggle_called = True

            def show_session(self, *_args, **_kwargs):
                self.show_session_called = True

            def focus_pane_for_session(self, _session_id):
                self.focus_called = True
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
        view.sticky_sessions = [StickySessionInfo("sess-sticky")]
        view.flat_items = [
            self._make_session_node(
                session_id="sess-sticky",
                computer="local-machine",
                tmux_session_name="tc-sticky",
            )
        ]
        view.selected_index = 0
        # Simulate state where a preview may still be stale from previous interaction.
        view.state.sessions.preview = PreviewState(session_id="sess-other")

        view.handle_enter(None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert len(view.sticky_sessions) == 1
        assert view.state.sessions.preview is None
        assert pane_manager.focus_called is True

    def test_space_key_previews_without_focus(self, mock_focus):
        """Pressing Space on a session should highlight only and keep focus in the tree."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.show_session_called = True

            def focus_pane_for_session(self, session_id):
                self.focus_called = True
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
        view._space_double_press_threshold = 0.0
        view.flat_items = [
            self._make_session_node(
                session_id="sess-space",
                computer="local-machine",
                tmux_session_name="tc-space",
            )
        ]
        view.selected_index = 0
        view._double_click_threshold = 0.0

        view.handle_key(ord(" "), None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.selected_index == 0
        assert pane_manager.focus_called is False
        assert pane_manager.toggle_called is False
        assert view.state.sessions.preview == PreviewState(session_id="sess-space")
        assert pane_manager.apply_called is True

    def test_space_key_preview_works_with_duplicate_sticky_state(self, mock_focus):
        """Space preview should still work when sticky state contains duplicate entries."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, *_args, **_kwargs):
                pass

            def show_session(self, *_args, **_kwargs):
                pass

            def focus_pane_for_session(self, _session_id):
                self.focus_called = True
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
        view.sticky_sessions = [
            StickySessionInfo("sticky-a"),
            StickySessionInfo("sticky-a"),
            StickySessionInfo("sticky-b"),
            StickySessionInfo("sticky-b"),
        ]
        view.flat_items = [
            self._make_session_node(
                session_id="preview-session",
                computer="local-machine",
                tmux_session_name="tc-preview",
            )
        ]
        view.selected_index = 0

        view.handle_key(ord(" "), None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.state.sessions.preview == PreviewState(session_id="preview-session")
        assert pane_manager.focus_called is False

    def test_space_double_press_toggles_sticky_for_session(self, mock_focus):
        """Pressing Space twice on a session quickly should toggle sticky mode."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.show_session_called = True

            def focus_pane_for_session(self, session_id):
                self.focus_called = True
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
        view.flat_items = [
            self._make_session_node(
                session_id="sess-space-double",
                computer="local-machine",
                tmux_session_name="tc-space-double",
            )
        ]
        view.selected_index = 0

        view.handle_key(ord(" "), None)
        # Simulate a fast second press like a double-click.
        view._last_space_press_time = time.perf_counter() - 0.1
        view.handle_key(ord(" "), None)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view._pending_activate_session_id is None
        assert view._pending_activate_at is None
        assert len(view.sticky_sessions) == 1
        assert view.sticky_sessions[0].session_id == "sess-space-double"
        assert view.state.sessions.preview == PreviewState(session_id="sess-space-double")
        assert pane_manager.focus_called is False
        assert pane_manager.apply_called is True
        assert view.selected_index == 0

    def test_double_space_press_previews_and_toggles_sticky(self, monkeypatch, mock_focus):
        """Double space should toggle sticky."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.show_session_called = True

            def focus_pane_for_session(self, session_id):
                self.focus_called = True
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
        session_node = self._make_session_node(
            session_id="sess-space-double",
            computer="local-machine",
            tmux_session_name="tc-space-double",
        )
        view.flat_items = [session_node]
        view._sessions = [session_node.data.session]
        view.selected_index = 0

        base_time = 1_000.0
        monkeypatch.setattr(time, "perf_counter", lambda: base_time)
        view.handle_key(ord(" "), None)

        monkeypatch.setattr(time, "perf_counter", lambda: base_time + 0.1)
        view.handle_key(ord(" "), None)

        monkeypatch.setattr(time, "perf_counter", lambda: base_time + 1.0)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        # Double-space for sticky toggle still enqueues a preview request to ensure
        # the session is visible.
        assert view.state.sessions.preview == PreviewState(session_id="sess-space-double")
        assert pane_manager.focus_called is False
        assert len(view.sticky_sessions) == 1
        assert view.sticky_sessions[0].session_id == "sess-space-double"

    def test_rapid_third_space_press_does_not_reactivate_after_double_toggle(self, monkeypatch, mock_focus):
        """A rapid third space after a double-press should remain non-activating."""

        class MockPaneManager:
            def __init__(self):
                self.is_available = True
                self.toggle_called = False
                self.show_session_called = False
                self.focus_called = False
                self.apply_called = False

            def toggle_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.toggle_called = True

            def show_session(self, tmux_session_name, active_agent, computer_info=None, session_id=None):
                self.show_session_called = True

            def focus_pane_for_session(self, session_id):
                self.focus_called = True
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
        view.flat_items = [
            self._make_session_node(
                session_id="sess-space-guard",
                computer="local-machine",
                tmux_session_name="tc-space-guard",
            )
        ]
        view.selected_index = 0

        base_time = 2_000.0
        monkeypatch.setattr(time, "perf_counter", lambda: base_time)
        view.handle_key(ord(" "), None)
        monkeypatch.setattr(time, "perf_counter", lambda: base_time + 0.1)
        view.handle_key(ord(" "), None)
        # Third quick press falls inside the double-press guard.
        monkeypatch.setattr(time, "perf_counter", lambda: base_time + 0.2)
        view.handle_key(ord(" "), None)

        monkeypatch.setattr(time, "perf_counter", lambda: base_time + 0.7)
        view.apply_pending_activation()
        view.apply_pending_focus()
        controller.apply_pending_layout()

        assert view.state.sessions.preview == PreviewState(session_id="sess-space-guard")
        assert pane_manager.focus_called is False
        assert view._pending_activate_session_id is None
        assert len(view.sticky_sessions) == 1

    def test_render_session_clears_line_width(self, sessions_view, monkeypatch):
        """Detail lines are padded to full width to avoid stale artifacts."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, _attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text))

        session = self._make_session_node(
            session_id="s1",
            title="Test Session",
            active_agent="claude",
            thinking_mode="slow",
        )
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)
        screen = FakeScreen()
        width = 30
        lines_used = sessions_view._render_session(screen, 0, session, width, False, 3)

        assert lines_used == 2

        # Rendering uses three calls for line 1 (idx, agent/mode, title) and one for line 2
        assert len(screen.calls) == 4

        # Line 1 does not guarantee full width padding
        line1_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line1_calls) == 3

        # Line 2 (ID line) should still be full width
        line2_calls = [call for call in screen.calls if call[0] == 1]
        assert len(line2_calls) == 1
        assert len(line2_calls[0][2]) == width

    def test_headless_session_mutes_header_lines_only(self, sessions_view, monkeypatch):
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
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name=None,
        )
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)
        sessions_view.state.sessions.last_summary["headless-1"] = "agent output"
        sessions_view.state.sessions.output_highlights.add("headless-1")

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 80, False, 4)

        assert lines_used == 3

        # Header/title line (row 0): [idx], agent/mode, and title should be muted for headless.
        row0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(row0_calls) == 3
        assert row0_calls[0][3] == 1
        assert row0_calls[1][3] == 1
        assert row0_calls[2][3] == 1

        # Line 2 ID row is also muted for headless.
        row1_calls = [call for call in screen.calls if call[0] == 1]
        assert len(row1_calls) == 1
        assert row1_calls[0][3] == 1

        # Output row keeps activity highlight behavior.
        row2_calls = [call for call in screen.calls if call[0] == 2]
        assert len(row2_calls) == 1
        assert row2_calls[0][3] == 3

    def test_selected_headless_session_headers_show_keyboard_focus(self, sessions_view, monkeypatch):
        """Selected headless rows should use muted focus colors during navigation."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="headless-selected",
            title="Headless Selected",
            status="headless",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name=None,
        )
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 80, True, 3)

        assert lines_used == 2
        row0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(row0_calls) == 3
        focused_headless_selection_attr = 37 | curses.A_BOLD
        assert row0_calls[0][3] == focused_headless_selection_attr
        assert row0_calls[1][3] == focused_headless_selection_attr
        assert row0_calls[2][3] == focused_headless_selection_attr

    def test_preview_session_uses_highlight_attrs(self, sessions_view, monkeypatch):
        """Previewed non-selected sessions use muted background with agent color."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="previewed",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-preview",
        )
        sessions_view._preview = PreviewState(session_id="previewed")
        sessions_view.state.sessions.preview = PreviewState(session_id="previewed")
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        screen_calls = screen.calls
        sessions_view._render_session(screen, 0, session, 80, False, 3)

        line0_calls = [call for call in screen_calls if call[0] == 0]
        assert len(line0_calls) == 3
        # Previewed non-selected rows remain distinct via muted background,
        # without using focused selection color.
        assert line0_calls[0][3] == 27
        assert line0_calls[1][3] == 27
        assert line0_calls[2][3] == 27
        assert line0_calls[2][2].endswith(" ")

    def test_selected_preview_session_keeps_selection_highlight(self, sessions_view, monkeypatch):
        """Selected preview rows keep reverse-selection emphasis."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="preview-selected",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-preview-selected",
        )
        sessions_view._preview = PreviewState(session_id="preview-selected")
        sessions_view.state.sessions.preview = PreviewState(session_id="preview-selected")
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        session_calls = screen.calls
        sessions_view._render_session(screen, 0, session, 80, True, 3)

        line0_calls = [call for call in session_calls if call[0] == 0]
        assert len(line0_calls) == 3
        assert line0_calls[0][3] == (37 | curses.A_BOLD)
        assert line0_calls[1][3] == (37 | curses.A_BOLD)
        assert line0_calls[2][3] == (37 | curses.A_BOLD)
        assert line0_calls[2][2].endswith(" ")

    def test_selected_non_preview_session_uses_focus_muted_colors(self, sessions_view, monkeypatch):
        """Non-preview selected rows use muted focus colors while navigating."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="focused",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-focused",
        )
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        sessions_view._render_session(screen, 0, session, 80, True, 3)

        line0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line0_calls) == 3
        assert line0_calls[0][3] == (37 | curses.A_BOLD)
        assert line0_calls[1][3] == (37 | curses.A_BOLD)
        assert line0_calls[2][3] == (37 | curses.A_BOLD)
        assert line0_calls[2][2].endswith(" ")

    def test_selected_sticky_session_badge_is_bolded(self, sessions_view, monkeypatch):
        """Sticky row selection should bold only the index badge."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="sticky-focused",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-sticky-focused",
        )
        sessions_view.sticky_sessions = [StickySessionInfo(session_id="sticky-focused")]
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        sessions_view._render_session(screen, 0, session, 80, True, 3)

        line0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line0_calls) == 3
        assert line0_calls[0][3] == (get_sticky_badge_attr() | curses.A_BOLD)

    def test_unselected_sticky_session_badge_is_bolded_and_uses_base_color(self, sessions_view, monkeypatch):
        """Sticky row badges stay on base colors and stay bold when not selected."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="sticky-idle",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-sticky-idle",
        )
        sessions_view.sticky_sessions = [StickySessionInfo(session_id="sticky-idle")]
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        sessions_view._render_session(screen, 0, session, 80, False, 3)

        line0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line0_calls) >= 1
        assert line0_calls[0][3] == get_sticky_badge_attr()

    def test_previewed_sticky_session_badge_uses_base_colors(self, sessions_view, monkeypatch):
        """Previewed sticky row badges stay on base colors while keeping boldness."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="sticky-preview",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-sticky-preview",
        )
        sessions_view.sticky_sessions = [StickySessionInfo(session_id="sticky-preview")]
        sessions_view._preview = PreviewState(session_id="sticky-preview")
        sessions_view.state.sessions.preview = PreviewState(session_id="sticky-preview")
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        sessions_view._render_session(screen, 0, session, 80, False, 3)

        line0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line0_calls) >= 1
        # Sticky rows are never 'previewed' to keep their badges stable.
        assert line0_calls[0][3] == get_sticky_badge_attr()

    def test_selected_previewed_sticky_session_badge_uses_base_colors(self, sessions_view, monkeypatch):
        """Selected previewed sticky rows keep badge colors and stay bold."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        session = self._make_session_node(
            session_id="sticky-selected-preview",
            active_agent="claude",
            thinking_mode="slow",
            tmux_session_name="tc-sticky-selected-preview",
        )
        sessions_view.sticky_sessions = [StickySessionInfo(session_id="sticky-selected-preview")]
        sessions_view._preview = PreviewState(session_id="sticky-selected-preview")
        sessions_view.state.sessions.preview = PreviewState(session_id="sticky-selected-preview")
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)

        screen = FakeScreen()
        sessions_view._render_session(screen, 0, session, 80, True, 3)

        line0_calls = [call for call in screen.calls if call[0] == 0]
        assert len(line0_calls) >= 1
        assert line0_calls[0][3] == (get_sticky_badge_attr() | curses.A_BOLD)

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
        assert len(row0_calls) == 3
        assert row0_calls[0][3] == 1  # claude muted pair
        assert row0_calls[1][3] == 1  # claude muted pair
        assert row0_calls[2][3] == 1  # claude muted pair

    def test_temp_output_highlight_uses_italic_attr_when_available(self, sessions_view, monkeypatch):
        """When italics are supported, only placeholder text is italicized."""

        class FakeScreen:
            def __init__(self):
                self.calls = []

            def addstr(self, row, col, text, attr):  # noqa: D401, ANN001
                self.calls.append((row, col, text, attr))

        monkeypatch.setattr(curses, "A_ITALIC", 2048, raising=False)
        monkeypatch.setattr(curses, "color_pair", lambda pair_id: pair_id)
        session = self._make_session_node(
            session_id="temp-italic",
            active_agent="claude",
        )
        sessions_view.state.sessions.temp_output_highlights.add("temp-italic")

        screen = FakeScreen()
        lines_used = sessions_view._render_session(screen, 0, session, 120, False, 4)

        assert lines_used == 3
        output_row_calls = [call for call in screen.calls if call[0] == 2]
        assert len(output_row_calls) == 2
        # Prefix line is non-italic
        assert "out:" in output_row_calls[0][2]
        assert output_row_calls[0][3] == 3
        # Placeholder overlay is italicized
        assert "Thinking" in output_row_calls[1][2]
        assert "**Thinking" not in output_row_calls[1][2]
        assert output_row_calls[1][3] == (3 | curses.A_ITALIC)

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
        assert "..." in output_row_calls[1][2]
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

    def test_watched_preview_output_highlight_auto_clears_after_3s(self, sessions_view, monkeypatch):
        """Selected + actively previewed sessions should auto-clear output highlight quickly."""
        session_id = "watch-1"
        sessions_view.state.sessions.selected_session_id = session_id
        sessions_view.state.sessions.preview = PreviewState(session_id=session_id)
        sessions_view.state.sessions.output_highlights.add(session_id)

        tick = iter([100.0, 102.0, 103.2])
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions.time.monotonic", lambda: next(tick))

        sessions_view._update_viewing_timer()
        assert sessions_view._viewing_timer_session == session_id
        assert session_id in sessions_view.state.sessions.output_highlights

        sessions_view._update_viewing_timer()
        assert session_id in sessions_view.state.sessions.output_highlights

        sessions_view._update_viewing_timer()
        assert sessions_view._viewing_timer_session is None
        assert session_id not in sessions_view.state.sessions.output_highlights

    def test_output_highlight_persists_when_session_not_actively_previewed(self, sessions_view, monkeypatch):
        """Without active preview watch, output highlight should stay persistent."""
        session_id = "not-watched-1"
        sessions_view.state.sessions.selected_session_id = session_id
        sessions_view.state.sessions.preview = None
        sessions_view.state.sessions.output_highlights.add(session_id)

        tick = iter([200.0, 205.0, 210.0])
        monkeypatch.setattr("teleclaude.cli.tui.views.sessions.time.monotonic", lambda: next(tick))

        sessions_view._update_viewing_timer()
        sessions_view._update_viewing_timer()
        sessions_view._update_viewing_timer()

        assert sessions_view._viewing_timer_session is None
        assert session_id in sessions_view.state.sessions.output_highlights
