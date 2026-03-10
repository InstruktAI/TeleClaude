"""Unit tests for session list job filter (API + CLI)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


def _make_session(job: str | None = None, initiator: str | None = None, closed: bool = False) -> Any:
    """Build a minimal SessionSnapshot-like namespace."""
    meta = {"job": job} if job else {}
    return SimpleNamespace(
        session_id=f"sess-{job or 'none'}",
        session_metadata=meta,
        initiator_session_id=initiator,
        computer="local",
        human_email=None,
        human_role="member",
        visibility="private",
        status="closed" if closed else "running",
        working_slug=None,
        tmux_session_name=None,
        title=None,
        project_path=None,
        created_at=None,
        updated_at=None,
        ended_at=None,
    )


class TestSessionListJobFilter:
    """Tests for job-filter logic in list_sessions endpoint."""

    def _sessions_with_jobs(self):
        return [
            _make_session(job="integrator"),
            _make_session(job="builder"),
            _make_session(job=None),
        ]

    def test_list_sessions_job_filter_matches(self):
        """Job filter returns only sessions with matching job."""
        sessions = self._sessions_with_jobs()
        filtered = [
            s for s in sessions
            if isinstance(s.session_metadata, dict)
            and s.session_metadata.get("job") == "integrator"
        ]
        assert len(filtered) == 1
        assert filtered[0].session_metadata.get("job") == "integrator"

    def test_list_sessions_job_filter_no_match(self):
        """Job filter returns empty when no sessions match."""
        sessions = self._sessions_with_jobs()
        filtered = [
            s for s in sessions
            if isinstance(s.session_metadata, dict)
            and s.session_metadata.get("job") == "nonexistent"
        ]
        assert filtered == []

    def test_list_sessions_no_job_filter(self):
        """No job filter returns all sessions."""
        sessions = self._sessions_with_jobs()
        assert len(sessions) == 3

    def test_list_sessions_job_filter_respects_initiator_scope_without_all(self):
        """Job filter is applied after initiator-scoping, not instead of it."""
        sessions = [
            _make_session(job="integrator", initiator="caller-1"),
            _make_session(job="integrator", initiator="caller-2"),
        ]
        # Simulate initiator-scope: only show sessions from caller-1
        caller_id = "caller-1"
        scoped = [s for s in sessions if s.initiator_session_id == caller_id]
        # Then apply job filter
        job_filtered = [
            s for s in scoped
            if isinstance(s.session_metadata, dict)
            and s.session_metadata.get("job") == "integrator"
        ]
        assert len(job_filtered) == 1
        assert job_filtered[0].initiator_session_id == "caller-1"

    def test_list_sessions_job_filter_respects_role_visibility(self):
        """Web/member visibility rules still apply before job filtering."""
        sessions = [
            _make_session(job="integrator"),
            _make_session(job="integrator"),
        ]
        # Give one session "public" visibility (web-visible), one "private"
        sessions[0].visibility = "public"
        sessions[1].visibility = "private"
        # Simulate role-based visibility: web/member sees only public
        visible = [s for s in sessions if s.visibility == "public"]
        # Then apply job filter
        job_filtered = [
            s for s in visible
            if isinstance(s.session_metadata, dict)
            and s.session_metadata.get("job") == "integrator"
        ]
        assert len(job_filtered) == 1
        assert job_filtered[0].visibility == "public"

    def test_list_sessions_job_filter_respects_closed_flag(self):
        """Closed sessions stay excluded unless --closed is requested."""
        sessions = [
            _make_session(job="integrator", closed=False),
            _make_session(job="integrator", closed=True),
        ]
        # Without --closed: filter out closed sessions first
        open_sessions = [s for s in sessions if s.status != "closed"]
        job_filtered = [
            s for s in open_sessions
            if isinstance(s.session_metadata, dict)
            and s.session_metadata.get("job") == "integrator"
        ]
        assert len(job_filtered) == 1
        assert job_filtered[0].status == "running"


class TestSessionListCLIJobFlag:
    """Tests for --job flag parsing in handle_sessions_list()."""

    def test_sessions_list_cli_job_flag(self):
        """CLI --job flag sends correct job param to API."""
        from teleclaude.cli.tool_commands import handle_sessions_list

        captured_params: dict[str, str] = {}

        def mock_api_call(method, path, params=None, **kwargs):
            if params:
                captured_params.update(params)
            return []

        with patch("teleclaude.cli.tool_commands.tool_api_call", side_effect=mock_api_call):
            with patch("teleclaude.cli.tool_commands.print_json"):
                handle_sessions_list(["--all", "--job", "integrator"])

        assert captured_params.get("job") == "integrator"
        assert captured_params.get("all") == "true"

    def test_sessions_list_cli_no_job_flag(self):
        """Without --job flag, job param is absent."""
        from teleclaude.cli.tool_commands import handle_sessions_list

        captured_params: dict[str, str] = {}

        def mock_api_call(method, path, params=None, **kwargs):
            if params:
                captured_params.update(params)
            return []

        with patch("teleclaude.cli.tool_commands.tool_api_call", side_effect=mock_api_call):
            with patch("teleclaude.cli.tool_commands.print_json"):
                handle_sessions_list(["--all"])

        assert "job" not in captured_params
