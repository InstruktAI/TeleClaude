"""Functional tmux-backed coverage for the inline document pane flow."""

from __future__ import annotations

import json
import shlex
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import pytest

from teleclaude import config as config_module
from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.state import DocPreviewState
from teleclaude.cli.tui.views.preparation import PreparationView
from teleclaude.core.todos_db import TodosDb

pytestmark = [pytest.mark.functional, pytest.mark.timeout(45)]

_API_SOCKET_ENV = "TELECLAUDE_API_SOCKET_PATH"


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
    timeout_seconds: float = 10.0,
) -> str:
    """Poll pane output until it matches the expected shape."""
    deadline = time.monotonic() + timeout_seconds
    latest = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [str(wrapper), "capture-pane", "-p", "-t", pane_id],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            time.sleep(0.2)
            continue
        latest = result.stdout.strip()
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
    conn = db._sync_conn()
    try:
        conn.execute(
            "INSERT INTO roadmap "  # guard: raw-sql
            "(id, slug, group_slug, description, status, delivered_at, "
            "delivered_commit, children, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, slug, None, None, "active", None, None, None, now, now),
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


def _start_artifact_api(socket_path: Path, db: TodosDb) -> threading.Thread:
    """Serve one artifact write request over a Unix socket for the spawned editor."""
    ready = threading.Event()
    errors: list[BaseException] = []

    def _serve() -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.settimeout(12)
        try:
            socket_path.unlink(missing_ok=True)
            server.bind(str(socket_path))
            server.listen(1)
            ready.set()
            conn, _addr = server.accept()
            with conn:
                request = b""
                while b"\r\n\r\n" not in request:
                    request += conn.recv(4096)
                head, body = request.split(b"\r\n\r\n", 1)
                header_lines = head.decode("iso-8859-1").split("\r\n")
                method, path, _version = header_lines[0].split(" ", 2)
                headers = {
                    key.lower(): value.strip()
                    for line in header_lines[1:]
                    if ":" in line
                    for key, value in [line.split(":", 1)]
                }
                content_length = int(headers.get("content-length", "0"))
                while len(body) < content_length:
                    body += conn.recv(4096)

                prefix = "/todos/artifacts/"
                if method != "POST" or not path.startswith(prefix):
                    _send_response(conn, 404, {"detail": "not found"})
                    return
                slug_raw, artifact_raw = path[len(prefix) :].split("/", 1)
                payload = json.loads(body[:content_length].decode("utf-8"))
                db.write_artifact_sync(
                    unquote(slug_raw),
                    unquote(artifact_raw),
                    str(payload["content"]),
                    updated_by="functional-test",
                )
                _send_response(conn, 200, {"status": "ok"})
        except BaseException as exc:
            errors.append(exc)
        finally:
            server.close()
            socket_path.unlink(missing_ok=True)

    thread = threading.Thread(target=_serve, name="artifact-api-test", daemon=True)
    thread.errors = errors
    thread.start()
    assert ready.wait(2), errors
    return thread


def _send_response(conn: socket.socket, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload).encode("utf-8")
    reason = "OK" if status == 200 else "Not Found"
    conn.sendall(
        (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        + body
    )


def _editor_command(*, project_root: Path, slug: str, artifact_name: str, view: bool) -> str:
    """Return the exact artifact editor command emitted by the preparation view."""
    prep = type("_PrepCommandStub", (), {"app": None})()
    return PreparationView._editor_command(
        prep,
        project_path=str(project_root),
        slug=slug,
        artifact_name=artifact_name,
        view=view,
    )


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

    subprocess.run([str(wrapper), "new-session", "-d", "-c", "/tmp", "-s", session_name, "sh"], check=True)
    pane_id = _run_tmux(wrapper, "list-panes", "-t", session_name, "-F", "#{pane_id}")

    api_socket_path = Path(f"/tmp/telec-api-{uuid.uuid4().hex[:8]}.sock")
    monkeypatch.setenv("TMUX", "functional-test")
    monkeypatch.setenv("TMUX_PANE", pane_id)
    monkeypatch.setenv(_API_SOCKET_ENV, str(api_socket_path))

    monkeypatch.setattr(config_module.config.computer, "tmux_binary", str(wrapper))

    project_root = tmp_path / "project"
    db = _seed_project_artifact(project_root)
    slug = "todo-1"
    artifact_name = "requirements"
    doc_id = f"artifact:{project_root}:{slug}:{artifact_name}"
    view_command = _editor_command(project_root=project_root, slug=slug, artifact_name=artifact_name, view=True)
    edit_command = (
        f"{_API_SOCKET_ENV}={shlex.quote(str(api_socket_path))} "
        f"{_editor_command(project_root=project_root, slug=slug, artifact_name=artifact_name, view=False)}"
    )

    manager = TmuxPaneManager()
    api_thread: threading.Thread | None = None
    try:
        manager.apply_layout(
            active_session_id=None,
            sticky_session_ids=[],
            get_computer_info=lambda _name: None,
            active_doc_preview=DocPreviewState(
                doc_id=doc_id,
                command=view_command,
                title="requirements",
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
                title="requirements",
            ),
            focus=False,
        )

        assert manager.state.session_to_pane[f"doc:{doc_id}"] == preview_pane_id
        edit_capture = _wait_for_capture(
            wrapper,
            preview_pane_id,
            lambda output: "1  # Hello" in output and "Esc save+close" in output,
        )
        assert "1  # Hello" in edit_capture
        assert "Esc save+close" in edit_capture
        api_thread = _start_artifact_api(api_socket_path, db)
        _run_tmux(wrapper, "send-keys", "-t", preview_pane_id, "X", "Enter", "Y", "Escape")
        persisted = _wait_for_artifact_content(
            db,
            slug,
            artifact_name,
            lambda content: content.startswith("X\nY# Hello"),
        )
        assert persisted.startswith("X\nY# Hello")
        api_thread.join(timeout=2)
        assert not getattr(api_thread, "errors", [])
    finally:
        manager.cleanup()
        if api_thread is not None and api_thread.is_alive():
            api_thread.join(timeout=1)
        subprocess.run([str(wrapper), "kill-server"], check=False)
