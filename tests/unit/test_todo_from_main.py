"""Tests for teleclaude.todo_scaffold — from-main skeleton and session file collection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from teleclaude.core.todos_db import TodosDb, get_todos_db_sync
from teleclaude.session_scoping import ScopedPathsResult
from teleclaude.todo_scaffold import NoSessionTouchedFiles, _collect_session_touched_files, create_from_main_skeleton

# Patch targets — these are lazy-imported inside create_from_main_skeleton
_WT = "teleclaude.core.next_machine.worktrees"
_SI = "teleclaude.core.next_machine.state_io"
_COLLECT = "teleclaude.todo_scaffold._collect_session_touched_files"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo_ns(
    *,
    branch: str = "main",
    status: str = " M src/app.py\n?? src/new.py",
    diff_stat: str = " src/app.py | 10 +++++-----\n 1 file changed",
) -> SimpleNamespace:
    """Build a SimpleNamespace that mimics a GitPython Repo for tests."""

    def update_environment(**_kwargs: str) -> dict[str, str]:
        return {}

    def show_ref(ref: str) -> str:
        return f"clean-content-of-{ref}"

    git = SimpleNamespace(
        status=MagicMock(return_value=status),
        diff=MagicMock(return_value=diff_stat),
        show=MagicMock(side_effect=show_ref),
        add=MagicMock(),
        commit=MagicMock(),
        checkout=MagicMock(),
        reset=MagicMock(),
        update_environment=update_environment,
    )
    active_branch = SimpleNamespace(name=branch)
    return SimpleNamespace(git=git, active_branch=active_branch)


def _setup_project(tmp_path: Path) -> Path:
    """Create minimal project structure with dirty files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("modified content")
    (tmp_path / "src" / "new.py").write_text("new file content")
    (tmp_path / "todos").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateFromMainSkeleton:
    """Tests for the from-main entry ramp."""

    def test_rejects_non_main_branch(self, tmp_path: Path) -> None:
        """Must be on main branch."""
        repo = _make_repo_ns(branch="feature-x")

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            pytest.raises(ValueError, match="from-main requires being on the main branch"),
        ):
            create_from_main_skeleton(str(tmp_path), "test-slug")

    def test_rejects_clean_working_tree(self, tmp_path: Path) -> None:
        """Must have uncommitted changes."""
        repo = _make_repo_ns(status="")

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            pytest.raises(ValueError, match="No uncommitted changes"),
        ):
            create_from_main_skeleton(str(tmp_path), "test-slug")

    def test_happy_path_creates_worktree_and_cleans_main(self, tmp_path: Path) -> None:
        """Full happy path: scaffold, worktree, transfer, clean, state."""
        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "test-slug"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)

        main_repo = _make_repo_ns()
        worktree_repo = _make_repo_ns(status="")
        call_order = MagicMock()
        call_order.attach_mock(worktree_repo.git.commit, "worktree_commit")
        call_order.attach_mock(main_repo.git.checkout, "main_checkout")

        def _repo_factory(path: str) -> SimpleNamespace:
            return worktree_repo if Path(path) == worktree_path else main_repo

        with (
            patch("teleclaude.git.Repo", side_effect=_repo_factory),
            patch(_COLLECT, return_value={"src/app.py", "src/new.py"}),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state") as mock_phase,
        ):
            output = create_from_main_skeleton(str(project), "test-slug", description="Test changes")

        # Verify output
        assert "Todo created: test-slug" in output
        assert "trees/test-slug/" in output
        assert "/next-work" not in output
        assert "telec sessions run" not in output

        # Verify todo artifacts were written to DB
        db = get_todos_db_sync(str(worktree_path))
        requirements = db.read_artifact_sync("test-slug", "requirements") or ""
        implementation_plan = db.read_artifact_sync("test-slug", "implementation-plan") or ""
        quality_checklist = db.read_artifact_sync("test-slug", "quality-checklist") or ""

        assert requirements.startswith("<!-- from-main:")
        assert "Test changes" in requirements
        assert implementation_plan.startswith("<!-- from-main:")
        assert quality_checklist.startswith("<!-- from-main:")

        # Verify files were transferred to worktree
        assert (worktree_path / "src" / "app.py").exists()
        assert (worktree_path / "src" / "new.py").exists()

        worktree_repo.git.add.assert_called_once_with("-A")
        worktree_repo.git.commit.assert_called_once_with("-m", "chore(test-slug): from-main handoff")
        assert call_order.mock_calls.index(call.worktree_commit("-m", "chore(test-slug): from-main handoff")) < (
            call_order.mock_calls.index(call.main_checkout("HEAD", "--", "src/app.py"))
        )

        # Verify main was cleaned — modified files restored from HEAD
        main_repo.git.checkout.assert_any_call("HEAD", "--", "src/app.py")

        # Verify untracked file removed from main
        assert not (project / "src" / "new.py").exists()

        # Verify apply_prepared_state was called to stamp DOR, grounding, verdicts
        mock_phase.assert_called_once_with(str(worktree_path), "test-slug")

    def test_db_roadmap_and_artifacts_bootstrapped(self, tmp_path: Path) -> None:
        """DB roadmap entry and stub artifacts exist before apply_prepared_state is called."""
        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "test-slug"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)

        repo = _make_repo_ns()

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, return_value={"src/app.py"}),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state"),
            patch(
                "teleclaude.core.next_machine.state_io.resolve_main_repo_root",
                return_value=Path(project),
            ),
        ):
            create_from_main_skeleton(str(project), "test-slug", description="DB bootstrap test")

        # Verify roadmap entry and artifacts were written to the worktree DB
        db_path = str(project / ".teleclaude" / "todos.db")
        db = TodosDb(db_path)
        db.initialize_sync()
        conn = db._sync_conn()
        try:
            roadmap_row = conn.execute(
                "SELECT slug FROM roadmap WHERE slug = ? AND status != 'delivered'",
                ("test-slug",),
            ).fetchone()
            assert roadmap_row is not None, "roadmap entry was not bootstrapped"

            artifact_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM todo_artifacts WHERE slug = ?",
                    ("test-slug",),
                ).fetchall()
            }
            assert "requirements" in artifact_names
            assert "implementation-plan" in artifact_names
            assert "quality-checklist" in artifact_names
        finally:
            conn.close()

    def test_deleted_files_removed_from_worktree(self, tmp_path: Path) -> None:
        """Deleted files on main should be removed from the worktree."""
        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "del-slug"
        worktree_path.mkdir(parents=True)
        # File exists in worktree (from origin/main) but deleted on main
        (worktree_path / "removed.py").write_text("to be deleted")

        repo = _make_repo_ns(status=" D removed.py")

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, return_value={"removed.py"}),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state"),
        ):
            create_from_main_skeleton(str(project), "del-slug")

        assert not (worktree_path / "removed.py").exists()

    def test_push_skips_when_not_a_repo(self, tmp_path: Path) -> None:
        """If scaffold push fails because not a repo, do not raise."""
        project = _setup_project(tmp_path)
        repo = _make_repo_ns()

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, return_value={"src/app.py", "src/new.py"}),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state"),
        ):
            create_from_main_skeleton(str(project), "not-a-repo-slug")

    def test_description_defaults_to_see_diff(self, tmp_path: Path) -> None:
        """Without --description, requirements.md shows default text."""
        project = _setup_project(tmp_path)
        worktree_path = project / "trees" / "no-desc"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)
        repo = _make_repo_ns()

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, return_value={"src/app.py", "src/new.py"}),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state"),
        ):
            create_from_main_skeleton(str(project), "no-desc")

        db = get_todos_db_sync(str(worktree_path))
        req_content = db.read_artifact_sync("no-desc", "requirements") or ""
        assert "See diff for details." in req_content

    def test_session_scoping_filters_to_touched_files_only(self, tmp_path: Path) -> None:
        """Only files touched by the session should be transferred."""
        project = _setup_project(tmp_path)
        (project / "docs").mkdir()
        (project / "docs" / "guide.md").write_text("modified guide", encoding="utf-8")

        worktree_path = project / "trees" / "scoped-slug"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)
        (worktree_path / "docs").mkdir(parents=True)

        # Status has both src and docs dirty, but session only touched src
        repo = _make_repo_ns(status=" M src/app.py\n M docs/guide.md\n?? src/new.py")

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, return_value={"src/app.py", "src/new.py"}),
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state"),
        ):
            create_from_main_skeleton(str(project), "scoped-slug")

        # Session-touched files transferred
        assert (worktree_path / "src" / "app.py").exists()
        assert (worktree_path / "src" / "new.py").exists()
        # Non-session files left on main
        assert not (worktree_path / "docs" / "guide.md").exists()
        assert (project / "docs" / "guide.md").read_text(encoding="utf-8") == "modified guide"

    def test_no_session_id_raises_value_error(self, tmp_path: Path) -> None:
        """from-main fails hard when not in an agent session."""
        project = _setup_project(tmp_path)
        repo = _make_repo_ns()

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, side_effect=ValueError("from-main requires an active agent session")),
            pytest.raises(ValueError, match="active agent session"),
        ):
            create_from_main_skeleton(str(project), "no-session")

    def test_empty_session_files_raises_value_error(self, tmp_path: Path) -> None:
        """from-main fails when transcript yields no files."""
        project = _setup_project(tmp_path)
        repo = _make_repo_ns()

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, side_effect=ValueError("Could not determine session-touched files")),
            pytest.raises(ValueError, match="Could not determine"),
        ):
            create_from_main_skeleton(str(project), "empty-files")

    def test_all_files_true_transfers_without_session_scoping(self, tmp_path: Path) -> None:
        """all_files=True transfers all dirty files without invoking _collect_session_touched_files."""
        project = _setup_project(tmp_path)
        (project / "docs").mkdir()
        (project / "docs" / "guide.md").write_text("guide content", encoding="utf-8")

        worktree_path = project / "trees" / "all-slug"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir(parents=True)
        (worktree_path / "docs").mkdir(parents=True)

        repo = _make_repo_ns(status=" M src/app.py\n M docs/guide.md\n?? src/new.py")

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT) as mock_collect,
            patch(f"{_WT}._create_or_attach_worktree", return_value=True),
            patch(
                f"{_WT}._decide_worktree_prep",
                return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
            ),
            patch(f"{_SI}.apply_prepared_state"),
        ):
            create_from_main_skeleton(str(project), "all-slug", all_files=True)

        # _collect_session_touched_files must NOT be called
        mock_collect.assert_not_called()
        # All dirty files transferred
        assert (worktree_path / "src" / "app.py").exists()
        assert (worktree_path / "src" / "new.py").exists()
        assert (worktree_path / "docs" / "guide.md").exists()

    def test_no_intersection_between_session_and_status_raises(self, tmp_path: Path) -> None:
        """ValueError when session-touched files don't overlap with git status."""
        project = _setup_project(tmp_path)
        repo = _make_repo_ns()

        with (
            patch("teleclaude.git.Repo", return_value=repo),
            patch(_COLLECT, return_value={"completely/unrelated.py"}),
            pytest.raises(ValueError, match="No uncommitted changes to transfer"),
        ):
            create_from_main_skeleton(str(project), "no-overlap")


class TestCollectSessionTouchedFiles:
    """Direct unit tests for _collect_session_touched_files.

    Patches target source modules (where lazy imports resolve from),
    not teleclaude.todo_scaffold.
    """

    # Source-module patch targets for lazy imports inside _collect_session_touched_files
    _SQL_SESSION = "sqlmodel.Session"
    _SYNC_ENGINE = "teleclaude.hooks.receiver._session._create_sync_engine"
    _DB_MODELS = "teleclaude.core.db_models"
    _GET_AGENT = "teleclaude.core.agents.get_default_agent"
    _AGENT_NAME = "teleclaude.core.agents.AgentName"
    _CURRENT_CODEX_TRANSCRIPT = "teleclaude.core.codex_transcript.discover_current_codex_transcript_path"
    _DISCOVER_CODEX_TRANSCRIPT = "teleclaude.core.codex_transcript.discover_codex_transcript_path"
    _RESOLVE_SCOPED_PATHS = "teleclaude.session_scoping.resolve_scoped_paths"

    def test_happy_path_returns_touched_files(self) -> None:
        """Returns set of files from the shared session-scoping API."""
        mock_row = SimpleNamespace(native_log_file="/tmp/transcript.jsonl")
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        scoped_paths = ScopedPathsResult(
            paths=("src/app.py", "src/utils.py"),
            scope_mode="session_dirty",
            workspace_kind="git_shared",
            strategy="claude_structured_fallback",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-123"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            patch(self._GET_AGENT, return_value="claude"),
            patch(self._AGENT_NAME) as mock_agent_name,
            patch(self._RESOLVE_SCOPED_PATHS, return_value=scoped_paths),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_agent_name.from_str.return_value = mock_agent_name.CLAUDE

            result = _collect_session_touched_files("/project")

        assert result == {"src/app.py", "src/utils.py"}

    def test_missing_session_id_raises(self) -> None:
        """Raises ValueError when session marker file is not found."""
        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value=None),
            pytest.raises(ValueError, match="active agent session"),
        ):
            _collect_session_touched_files("/project")

    def test_session_not_in_db_raises(self) -> None:
        """Raises ValueError when session ID not found in database."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-missing"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            pytest.raises(ValueError, match="Session sess-missing not found"),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            _collect_session_touched_files("/project")

    def test_missing_transcript_raises(self) -> None:
        """Raises ValueError when session has no native_log_file."""
        mock_row = SimpleNamespace(native_log_file=None)
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-no-log"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            pytest.raises(ValueError, match="No transcript found"),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            _collect_session_touched_files("/project")

    def test_empty_timeline_raises(self) -> None:
        """Raises ValueError when shared session scoping returns no touched files."""
        mock_row = SimpleNamespace(native_log_file="/tmp/transcript.jsonl")
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-empty"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            patch(self._GET_AGENT, return_value="claude"),
            patch(self._AGENT_NAME) as mock_agent_name,
            patch(
                self._RESOLVE_SCOPED_PATHS,
                return_value=ScopedPathsResult(
                    paths=(),
                    scope_mode="session_dirty",
                    workspace_kind="git_shared",
                    strategy="claude_structured_fallback",
                    ledger_updated=False,
                ),
            ),
            pytest.raises(NoSessionTouchedFiles, match="Could not determine session-touched files"),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_agent_name.from_str.return_value = mock_agent_name.CLAUDE

            _collect_session_touched_files("/project")

    def test_no_touched_files_raises(self) -> None:
        """Raises ValueError when shared session scoping yields no owned dirty files."""
        mock_row = SimpleNamespace(native_log_file="/tmp/transcript.jsonl")
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-no-files"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            patch(self._GET_AGENT, return_value="claude"),
            patch(self._AGENT_NAME) as mock_agent_name,
            patch(
                self._RESOLVE_SCOPED_PATHS,
                return_value=ScopedPathsResult(
                    paths=(),
                    scope_mode="session_dirty",
                    workspace_kind="git_shared",
                    strategy="claude_structured_fallback",
                    ledger_updated=False,
                ),
            ),
            pytest.raises(NoSessionTouchedFiles, match="Could not determine session-touched files"),
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_agent_name.from_str.return_value = mock_agent_name.CLAUDE

            _collect_session_touched_files("/project")

    def test_codex_prefers_live_thread_transcript_when_db_points_to_stale_subagent(self) -> None:
        """Codex sessions pass the live transcript hint into shared session scoping."""
        mock_row = SimpleNamespace(
            active_agent="codex",
            native_log_file="/tmp/stale-subagent.jsonl",
            native_session_id="native-stale",
        )
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        scoped_paths = ScopedPathsResult(
            paths=("teleclaude/daemon_hook_outbox.py",),
            scope_mode="session_dirty",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-codex"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            patch(self._CURRENT_CODEX_TRANSCRIPT, return_value="/tmp/live-parent.jsonl"),
            patch(self._RESOLVE_SCOPED_PATHS, return_value=scoped_paths) as resolve_scoped_mock,
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = _collect_session_touched_files("/project")

        assert result == {"teleclaude/daemon_hook_outbox.py"}
        assert resolve_scoped_mock.call_args.kwargs["transcript_path"] == "/tmp/live-parent.jsonl"

    def test_codex_discovers_transcript_from_native_session_id_when_log_is_missing(self) -> None:
        """Codex sessions fall back to transcript discovery before calling shared scoping."""
        mock_row = SimpleNamespace(active_agent="codex", native_log_file=None, native_session_id="native-parent")
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        scoped_paths = ScopedPathsResult(
            paths=("teleclaude/todo_scaffold.py",),
            scope_mode="session_dirty",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-codex"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            patch(self._DISCOVER_CODEX_TRANSCRIPT, return_value="/tmp/discovered-parent.jsonl"),
            patch(self._CURRENT_CODEX_TRANSCRIPT, return_value=None),
            patch(self._RESOLVE_SCOPED_PATHS, return_value=scoped_paths) as resolve_scoped_mock,
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = _collect_session_touched_files("/project")

        assert result == {"teleclaude/todo_scaffold.py"}
        assert resolve_scoped_mock.call_args.kwargs["transcript_path"] == "/tmp/discovered-parent.jsonl"

    def test_from_main_uses_session_dirty_scope(self) -> None:
        """from-main requests session_dirty from the shared session-scoping API."""
        mock_row = SimpleNamespace(
            active_agent="codex",
            native_log_file="/tmp/parent.jsonl",
            native_session_id="parent-thread",
        )
        mock_db = MagicMock()
        mock_db.get.return_value = mock_row

        scoped_paths = ScopedPathsResult(
            paths=(
                "teleclaude/core/codex_transcript.py",
                "teleclaude/todo_scaffold.py",
                "tests/unit/core/test_codex_transcript.py",
            ),
            scope_mode="session_dirty",
            workspace_kind="git_shared",
            strategy="codex_structured",
            ledger_updated=False,
        )

        with (
            patch("teleclaude.todo_scaffold._get_session_id", return_value="sess-codex"),
            patch(self._SYNC_ENGINE, return_value=MagicMock()),
            patch(self._SQL_SESSION) as mock_session_cls,
            patch(self._CURRENT_CODEX_TRANSCRIPT, return_value="/tmp/parent.jsonl"),
            patch(self._RESOLVE_SCOPED_PATHS, return_value=scoped_paths) as resolve_scoped_mock,
        ):
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = _collect_session_touched_files("/project")

        assert result == {
            "teleclaude/todo_scaffold.py",
            "teleclaude/core/codex_transcript.py",
            "tests/unit/core/test_codex_transcript.py",
        }
        assert resolve_scoped_mock.call_args.kwargs == {
            "session_id": "sess-codex",
            "workspace_root": "/project",
            "agent_name": "codex",
            "scope_mode": "session_dirty",
            "transcript_path": "/tmp/parent.jsonl",
            "native_session_id": "parent-thread",
        }


def test_all_files_skips_session_scoping(tmp_path: Path) -> None:
    """all_files=True transfers all dirty files without calling _collect_session_touched_files."""
    project = tmp_path
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("modified content")
    (project / "todos").mkdir()

    worktree_path = project / "trees" / "all-files-slug"
    worktree_path.mkdir(parents=True)
    (worktree_path / "src").mkdir(parents=True)

    def update_environment(**_kwargs: str) -> dict[str, str]:
        return {}

    # Status has both a modified file and an added (staged) file
    repo_ns = SimpleNamespace(
        git=SimpleNamespace(
            status=MagicMock(return_value=" M src/app.py\nA  src/staged.py"),
            diff=MagicMock(return_value=""),
            show=MagicMock(return_value=""),
            add=MagicMock(),
            commit=MagicMock(),
            checkout=MagicMock(),
            reset=MagicMock(),
            update_environment=update_environment,
        ),
        active_branch=SimpleNamespace(name="main"),
    )

    collect_mock = MagicMock()
    with (
        patch("teleclaude.git.Repo", return_value=repo_ns),
        patch(_COLLECT, collect_mock),
        patch(f"{_WT}._create_or_attach_worktree", return_value=True),
        patch(
            f"{_WT}._decide_worktree_prep",
            return_value=SimpleNamespace(should_prepare=False, inputs_digest="x"),
        ),
        patch(f"{_SI}.apply_prepared_state"),
    ):
        create_from_main_skeleton(str(project), "all-files-slug", all_files=True)

    # Session scoping must not be called when all_files=True
    collect_mock.assert_not_called()
