"""Functional tmux-backed coverage for the inline document pane flow."""
# pylint: disable=duplicate-code,too-many-locals

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from teleclaude import config as config_module
from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.state import DocPreviewState
from teleclaude.core.todos_db import TodosDb

pytestmark = [pytest.mark.functional, pytest.mark.timeout(10)]


def _write_tmux_wrapper(path: Path, socket_name: str) -> None:
    """Write a wrapper that pins all tmux calls to a temporary server socket."""
    path.write_text(f'#!/bin/sh\nexec tmux -L {socket_name} "$@"\n', encoding="utf-8")
    path.chmod(0o755)


def _run_tmux(wrapper: Path, *args: str) -> str:
    """Run tmux against the temporary server and return stdout."""
    result = subprocess.run(
        [str(wrapper), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _wait_for_capture(
    wrapper: Path,
    pane_id: str,
    predicate: Callable[[str], bool],
    *,
    timeout_seconds: float = 4.0,
) -> str:
    """Poll pane output until it matches the expected shape."""
    deadline = time.monotonic() + timeout_seconds
    latest = ""
    while time.monotonic() < deadline:
        latest = _run_tmux(wrapper, "capture-pane", "-p", "-t", pane_id)
        if predicate(latest):
            return latest
        time.sleep(0.2)
    raise AssertionError(f"Pane output did not satisfy predicate. Last capture:\n{latest}")


def _seed_project_artifact(
    project_root: Path,
    *,
    slug: str = "todo-1",
    artifact_name: str = "requirements",
    content: str = "# Hello\n",
) -> TodosDb:
    """Create a project-local todos.db containing one artifact."""
    db = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
    db.initialize_sync()
    row_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        conn.execute(
            "INSERT INTO roadmap "  # guard: raw-sql
            "(id, slug, position, group_slug, description, status, delivered_at, "
            "delivered_commit, children, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, slug, 0, None, None, "active", None, None, None, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    db.write_artifact_sync(slug, artifact_name, content)
    return db


def _wait_for_artifact_content(
    db: TodosDb,
    slug: str,
    artifact_name: str,
    predicate: Callable[[str], bool],
    *,
    timeout_seconds: float = 4.0,
) -> str:
    """Poll todos.db until the artifact content matches the expected shape."""
    deadline = time.monotonic() + timeout_seconds
    latest = ""
    while time.monotonic() < deadline:
        latest = db.read_artifact_sync(slug, artifact_name)
        if predicate(latest):
            return latest
        time.sleep(0.2)
    raise AssertionError(f"Artifact content did not satisfy predicate. Last content:\n{latest}")


@pytest.mark.functional
def test_tmux_pane_manager_renders_preview_then_editor_in_same_doc_pane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spawn a real tmux doc pane, then respawn it from markdown preview to editor."""
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    socket_name = f"telec-test-{uuid.uuid4().hex[:8]}"
    session_name = f"tc_tui_func_{uuid.uuid4().hex[:6]}"
    wrapper = tmp_path / "tmux-wrapper"
    _write_tmux_wrapper(wrapper, socket_name)

    subprocess.run([str(wrapper), "new-session", "-d", "-s", session_name, "sh"], check=True)
    pane_id = _run_tmux(wrapper, "list-panes", "-t", session_name, "-F", "#{pane_id}")

    monkeypatch.setenv("TMUX", "functional-test")
    monkeypatch.setenv("TMUX_PANE", pane_id)

    monkeypatch.setattr(config_module.config.computer, "tmux_binary", str(wrapper))

    project_root = tmp_path / "project"
    db = _seed_project_artifact(project_root)
    root = Path.cwd()
    python_bin = shlex.quote(sys.executable)
    root_arg = shlex.quote(str(root))
    project_arg = shlex.quote(str(project_root))
    slug = "todo-1"
    artifact_name = "requirements"
    doc_id = f"artifact:{project_root}:{slug}:{artifact_name}"
    view_command = (
        f"env PYTHONPATH={root_arg} {python_bin} -m teleclaude.cli.editor "
        f"--project-root {project_arg} --artifact-slug {slug} --artifact-name {artifact_name} --view"
    )
    edit_command = (
        f"env PYTHONPATH={root_arg} {python_bin} -m teleclaude.cli.editor "
        f"--project-root {project_arg} --artifact-slug {slug} --artifact-name {artifact_name}"
    )

    manager = TmuxPaneManager()
    try:
        manager.apply_layout(
            active_session_id=None,
            sticky_session_ids=[],
            get_computer_info=lambda _name: None,
            active_doc_preview=DocPreviewState(
                doc_id=doc_id,
                command=view_command,
                title="requirements.md",
            ),
            focus=False,
        )

        preview_pane_id = manager.state.session_to_pane[f"doc:{doc_id}"]
        preview_capture = _wait_for_capture(
            wrapper,
            preview_pane_id,
            lambda output: "Hello" in output and "1  # Hello" not in output,
        )
        assert "Hello" in preview_capture
        assert "1  # Hello" not in preview_capture

        manager.apply_layout(
            active_session_id=None,
            sticky_session_ids=[],
            get_computer_info=lambda _name: None,
            active_doc_preview=DocPreviewState(
                doc_id=doc_id,
                command=edit_command,
                title="requirements.md",
            ),
            focus=False,
        )

        assert manager.state.session_to_pane[f"doc:{doc_id}"] == preview_pane_id
        edit_capture = _wait_for_capture(
            wrapper,
            preview_pane_id,
            lambda output: "1  # Hello" in output,
        )
        assert "1  # Hello" in edit_capture
        _run_tmux(wrapper, "send-keys", "-t", preview_pane_id, "X", "Escape")
        persisted = _wait_for_artifact_content(
            db,
            slug,
            artifact_name,
            lambda content: content.startswith("X# Hello"),
        )
        assert persisted.startswith("X# Hello")
    finally:
        manager.cleanup()
        subprocess.run([str(wrapper), "kill-server"], check=False)
