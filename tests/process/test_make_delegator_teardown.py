"""Process meta coverage for telec code make delegation teardown."""

from __future__ import annotations

import os
import shlex
import signal
import time
import warnings
from pathlib import Path

import pytest

from teleclaude.cli.telec.handlers import quality

pytestmark = pytest.mark.process

_SPEC = "general/spec/tools/telec-cli"


@pytest.mark.spec(_SPEC, "code-quality-delegation")
def test_test_handler_teardown_kills_sigterm_ignoring_make_descendant(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    child_script = f"trap '' TERM; printf '%s' $$$$ > {shlex.quote(str(child_pid_file))}; sleep 30"
    (tmp_path / "Makefile").write_text(f"test:\n\t@sh -c {shlex.quote(child_script)}\n")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*use of fork.*")
        runner_pid = os.fork()
    runner_status: int | None = None
    if runner_pid == 0:
        try:
            quality.resolve_invocation_cwd = lambda: tmp_path
            quality.resolve_git_root = lambda _cwd: tmp_path
            quality._PROCESS_GROUP_TERM_GRACE_SECONDS = 0.2
            quality._PROCESS_GROUP_KILL_GRACE_SECONDS = 0.8
            quality.handle_test([])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            os._exit(code)
        except BaseException:
            os._exit(120)
        os._exit(0)

    try:
        deadline = time.monotonic() + 5
        while not child_pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid_file.exists()

        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        os.kill(runner_pid, signal.SIGTERM)
        runner_status = _wait_pid(runner_pid, timeout=3)
        assert runner_status is not None
        assert os.WIFSIGNALED(runner_status)
        assert os.WTERMSIG(runner_status) == signal.SIGTERM

        deadline = time.monotonic() + 1
        while _pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)

        assert not _pid_exists(child_pid)
    finally:
        if runner_status is None:
            try:
                os.kill(runner_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(runner_pid, 0)
            except ChildProcessError:
                pass
        if child_pid_file.exists():
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.spec(_SPEC, "UC-CQD1")
def test_test_handler_teardown_reaps_normal_exit_descendant(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    quoted_child_pid_file = shlex.quote(str(child_pid_file))
    child_script = f"printf '%s' $$$$ > {quoted_child_pid_file}; exec sleep 30"
    make_script = (
        f"sh -c {shlex.quote(child_script)} & "
        f"for _ in {' '.join(str(i) for i in range(100))}; "
        f"do [ -s {quoted_child_pid_file} ] && break; sleep 0.02; done; "
        "exit 2"
    )
    (tmp_path / "Makefile").write_text(f"test:\n\t@sh -c {shlex.quote(make_script)}\n")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*use of fork.*")
        runner_pid = os.fork()
    runner_status: int | None = None
    if runner_pid == 0:
        try:
            quality.resolve_invocation_cwd = lambda: tmp_path
            quality.resolve_git_root = lambda _cwd: tmp_path
            quality._PROCESS_GROUP_TERM_GRACE_SECONDS = 0.2
            quality._PROCESS_GROUP_KILL_GRACE_SECONDS = 0.8
            quality.handle_test([])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            os._exit(code)
        except BaseException:
            os._exit(120)
        os._exit(0)

    try:
        runner_status = _wait_pid(runner_pid, timeout=3)
        assert runner_status is not None
        assert os.WIFEXITED(runner_status)
        assert os.WEXITSTATUS(runner_status) == 2
        assert child_pid_file.exists()

        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 1
        while _pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)

        assert not _pid_exists(child_pid)
    finally:
        if runner_status is None:
            try:
                os.kill(runner_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(runner_pid, 0)
            except ChildProcessError:
                pass
        if child_pid_file.exists():
            child_pid = int(child_pid_file.read_text(encoding="utf-8"))
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _wait_pid(pid: int, *, timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while True:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.02, remaining))


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
