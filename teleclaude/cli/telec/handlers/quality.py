"""CLI handlers for ``telec code lint``, ``telec code test``, and ``telec code format``."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd
from teleclaude.quality.lint import LintRunner
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)

_PROCESS_GROUP_TERM_GRACE_SECONDS = 2.0
_PROCESS_GROUP_KILL_GRACE_SECONDS = 2.0


def handle_lint(args: list[str]) -> None:
    """Handle the ``telec code lint`` command.

    A scoped interactive run formats first (best-effort), then runs the
    project-native make lint check leg and the TeleClaude guardrails lane.
    The full/CI run (``--all``, ``CI``, or a no-session shared branch) never
    formats: a rewrite CI discards is indistinguishable from a pass and would
    mask drift, so it stays check-only. ``--step`` is retired.
    """
    run_all = "--all" in args
    files = _positionals(args, allowed_flags={"--all"}, usage="telec code lint [--all] [<files> ...]")
    project_root = resolve_git_root(resolve_invocation_cwd())

    scoped_files = _resolve_quality_scope(project_root, files=files, run_all=run_all)
    if scoped_files == []:
        return

    if scoped_files is not None:
        # Best-effort fix+format over the scoped paths; the developer sees and
        # commits the result. The check leg below stays the authoritative gate,
        # so a non-zero format exit is not surfaced here.
        _run_make("format", project_root, files=scoped_files)

    make_exit = _run_make("lint", project_root, files=scoped_files)
    guardrails_exit = 0
    try:
        LintRunner(project_root=project_root).run(
            files=scoped_files if scoped_files is not None else None,
            run_all=scoped_files is None,
        )
    except SystemExit as exc:
        guardrails_exit = _system_exit_code(exc)

    if guardrails_exit != 0:
        raise SystemExit(guardrails_exit)
    if make_exit != 0:
        raise SystemExit(make_exit)


def handle_test(args: list[str]) -> None:
    """Handle the ``telec code test`` command.

    ``--update-snapshots`` → accept reviewed snapshot diffs.
    """
    update_snapshots = "--update-snapshots" in args
    files = _positionals(
        args,
        allowed_flags={"--all", "--update-snapshots"},
        usage="telec code test [--all] [--update-snapshots]",
    )
    if files:
        print("ERROR: telec code test does not accept file operands", file=sys.stderr)
        raise SystemExit(2)
    project_root = resolve_git_root(resolve_invocation_cwd())
    variables = {"SNAPSHOT_UPDATE": "1"} if update_snapshots else None
    exit_code = _run_make("test", project_root, variables=variables)
    if exit_code != 0:
        raise SystemExit(exit_code)


def handle_format(args: list[str]) -> None:
    """Handle the ``telec code format`` command.

    No args → project-native make format.
    Positional args → make format scoped via FILES_FROM.
    """
    run_all = "--all" in args
    project_root = resolve_git_root(resolve_invocation_cwd())
    files = _positionals(args, allowed_flags={"--all"}, usage="telec code format [--all] [<files> ...]")
    scoped_files = None
    if files:
        scoped_files = _validate_or_exit(files, project_root)
        if not scoped_files:
            return
    elif run_all:
        scoped_files = None

    exit_code = _run_make("format", project_root, files=scoped_files)
    if exit_code != 0:
        raise SystemExit(exit_code)


def handle_install(args: list[str]) -> None:
    """Handle the ``telec code install`` command."""
    files = _positionals(args, allowed_flags=set(), usage="telec code install")
    if files:
        print("ERROR: telec code install does not accept operands", file=sys.stderr)
        raise SystemExit(2)
    project_root = resolve_git_root(resolve_invocation_cwd())
    exit_code = _run_make("install", project_root)
    if exit_code != 0:
        raise SystemExit(exit_code)


def _positionals(args: list[str], *, allowed_flags: set[str], usage: str) -> list[str]:
    files: list[str] = []
    for arg in args:
        if arg in allowed_flags:
            continue
        if arg.startswith("-"):
            print(f"ERROR: unknown flag or unsafe leading-dash path: {arg}\nUsage: {usage}", file=sys.stderr)
            raise SystemExit(2)
        files.append(arg)
    return files


def _resolve_quality_scope(project_root: Path, *, files: list[str], run_all: bool) -> list[str] | None:
    if files:
        return _validate_or_exit(files, project_root)
    if run_all or os.environ.get("CI"):
        return None

    scope_resolution = resolve_workspace_scope_resolution(project_root)
    if scope_resolution.kind is WorkspaceScopeKind.SHARED_BRANCH and not scope_resolution.has_session_identity:
        return None

    scoped = _validate_or_exit(list(scope_resolution.scoped_existing_paths), project_root)
    if not scoped:
        return []
    return scoped


def _validate_or_exit(files: list[str], project_root: Path) -> list[str]:
    scoped = validate_scoped_paths(files, project_root)
    if len(scoped) != len(files):
        print("ERROR: one or more paths were rejected by scoped path validation", file=sys.stderr)
        raise SystemExit(1)
    return scoped


def _run_make(
    target: str,
    project_root: Path,
    *,
    files: list[str] | None = None,
    variables: dict[str, str] | None = None,
) -> int:
    cmd = ["make", target]
    if variables:
        cmd.extend(f"{key}={value}" for key, value in variables.items())
    if files is None:
        return _run_in_process_group(cmd, cwd=str(project_root))
    with _nul_file(files) as files_from:
        cmd.append(f"FILES_FROM={files_from}")
        return _run_in_process_group(cmd, cwd=str(project_root))


def _run_in_process_group(cmd: list[str], *, cwd: str) -> int:
    """Run ``cmd`` as its own session/process-group leader and guarantee the
    whole group dies with this runner.

    ``start_new_session=True`` makes the child a process-group/session leader, so
    its descendants (``make`` → ``bash`` → ``pytest`` → ``execnet`` workers) share
    one group. On abnormal exit — a catchable ``SIGINT``/``SIGTERM`` to this
    runner, a ``KeyboardInterrupt``, or any propagating exception — the group is
    torn down so no worker reparents to PID 1.

    Explicit signal forwarding is required because ``start_new_session=True``
    detaches the child from the parent's controlling-terminal signal delivery: a
    bare Ctrl-C or ``SIGTERM`` reaches only this runner, not the detached group.
    A ``SIGKILL`` to this runner itself cannot be defended in userspace and is out
    of scope. Return code and ``FILES_FROM``/``variables`` plumbing are unchanged
    from a plain run.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, start_new_session=True)
    previous: dict[int, Any] = {}

    def _forward(signum: int, _frame: object) -> None:
        # Only unwind here; teardown runs in the except block below, outside the
        # interrupted ``proc.wait()`` so it does not contend for Popen's waitpid
        # lock. Raising propagates out of the blocked wait (PEP 475 suppresses the
        # EINTR retry), releasing that lock on the way out.
        raise _SignalReceived(signum)

    installable = threading.current_thread() is threading.main_thread()
    try:
        if installable:
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.signal(sig, _forward)
        try:
            return proc.wait()
        except _SignalReceived as received:
            _kill_process_group(proc)
            # Signal transparency: reset to the OS default and re-send, so this
            # runner dies with the correct WIFSIGNALED status and no traceback.
            # The os.kill terminates the process; the SystemExit is only a
            # fall-through guard (conventional 128+signum, no traceback).
            signal.signal(received.signum, signal.SIG_DFL)
            os.kill(os.getpid(), received.signum)
            raise SystemExit(128 + received.signum) from None
        except BaseException:
            _kill_process_group(proc)
            raise
    finally:
        for stored_signum, handler in previous.items():
            signal.signal(stored_signum, handler)


class _SignalReceived(BaseException):
    """Raised inside the termination handler to unwind a blocked ``proc.wait()``."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    """Tear down the child's process group: ``SIGTERM``, a brief grace, then
    ``SIGKILL``. Idempotent and safe after the child has already exited."""
    pgid = proc.pid
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pass
    if not _process_group_exists(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return
    if not _wait_process_group(proc, pgid, timeout=_PROCESS_GROUP_TERM_GRACE_SECONDS):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
        _wait_process_group(proc, pgid, timeout=_PROCESS_GROUP_KILL_GRACE_SECONDS)


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_process_group(proc: subprocess.Popen[bytes], pgid: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        proc.poll()
        if not _process_group_exists(pgid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))


@contextmanager
def _nul_file(files: list[str]) -> Iterator[str]:
    handle = tempfile.NamedTemporaryFile(delete=False)
    try:
        with handle:
            # NUL-terminate every path (not NUL-separate). The Makefile reads this
            # via `while read -r -d "" path`, which returns non-zero on a final
            # record with no trailing NUL — silently dropping the last file from
            # the scoped format/lint set. The trailing terminator keeps it in.
            handle.write(b"".join(path.encode("utf-8") + b"\0" for path in files))
        yield handle.name
    finally:
        Path(handle.name).unlink(missing_ok=True)


def _system_exit_code(exc: SystemExit) -> int:
    if isinstance(exc.code, int):
        return exc.code
    return 1
