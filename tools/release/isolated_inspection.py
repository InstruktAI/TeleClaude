"""Private job filesystem and bounded native-client processes on fresh hosted runners."""

from __future__ import annotations

import ctypes
import os
import shutil
import signal
import stat
import subprocess
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, ConfigDict

_PRIVATE_MODE = 0o700
_FILE_MODE = 0o600
_FILE_MODE_TEXT = "600"
_READ_DIRECTORY_MODE = 0o555
_READ_FILE_MODE = 0o444
_GLOB = "*"
_HOME = "home"
_TEMP = "tmp"
_STATE = "state"
_EMPTY = b""
_TIMEOUT = 600
_OUTPUT_BOUND = 16 * 1024 * 1024
_FILE_BOUND = 4 * 1024 * 1024
_GRACE = 2
_TIMEOUT_STATUS = 124
_UNKNOWN_STATUS = 125
_INVALID_PATH = "The owned private job path is unavailable or unsafe."
_INVALID_ENVIRONMENT = "The native client environment contains an undeclared capability."
_BOUNDARY_FAILED = "The native client's descendant boundary could not be closed."
_OUTPUT_FAILED = "The native client exceeded its output bound."
_WRITE_BINARY = "xb"
_PARENT = ".."
_USER_KEYS = frozenset({"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"})
_CODEX_KEYS = frozenset({"CODEX_HOME"})
_CLAUDE_KEYS = frozenset({"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN"})
_CHILDREN = Path("/proc/self/task")
_CHILDREN_FILE = "children"
_SUBREAPER_OPTION = 36


class InspectorRole(StrEnum):
    """Provider-private layout identities; both execute as their own fresh job's runner UID."""

    CODEX = "release-codex-inspector"
    CLAUDE = "release-claude-inspector"


class IsolatedProcessResult(BaseModel):
    """Bounded native output after owned descendants have been reaped."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    return_code: int
    stdout: bytes
    stderr: bytes
    timed_out: bool
    elapsed_seconds: float


class InspectorBoundaryError(RuntimeError):
    """A native-client process boundary could not be proven closed."""


class InspectorSetupError(RuntimeError):
    """Message-free native setup evidence."""

    def __init__(self, *, exception_type: str, errno: int | None = None, native_status: int | None = None) -> None:
        super().__init__(_INVALID_PATH)
        self.exception_type = exception_type
        self.errno = errno
        self.native_status = native_status


def _owned_path(root: Path, target: Path) -> None:
    """Refuse escapes, symlink ancestry and foreign ownership before private mutation."""
    if not root.is_absolute() or not target.is_absolute() or _PARENT in target.parts:
        raise ValueError(_INVALID_PATH)
    if not target.is_relative_to(root) or target == root or root.resolve() != root:
        raise ValueError(_INVALID_PATH)
    for path in (root, *reversed(target.parents[: len(target.parts) - len(root.parts) - 1]), target):
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ValueError(_INVALID_PATH)


def validate_controller_root(root: Path, *, temporary_parent: Path) -> None:
    """Require a strict resolved descendant of the explicitly owned job temporary parent."""
    parent = temporary_parent.resolve()
    if root.is_symlink() or root.resolve() != root or root == parent or not root.is_relative_to(parent):
        raise ValueError(_INVALID_PATH)


def create_controller_root(root: Path, *, temporary_parent: Path) -> Path:
    """Create ordinary private controller storage without changing existing ancestry."""
    validate_controller_root(root, temporary_parent=temporary_parent)
    root.mkdir(mode=_PRIVATE_MODE, parents=True, exist_ok=False)
    root.chmod(_PRIVATE_MODE)
    return root


def create_principal_directory(role: InspectorRole, root: Path, directory: Path) -> Path:
    """Create a contained private provider directory as the current runner."""
    del role
    _owned_path(root, directory)
    directory.mkdir(mode=_PRIVATE_MODE, exist_ok=False)
    directory.chmod(_PRIVATE_MODE)
    return directory


def principal_layout_paths(role: InspectorRole, root: Path) -> tuple[Path, Path, Path]:
    """Return the one provider's private home, temporary and state addresses."""
    principal = root / role.value
    return principal / _HOME, principal / _TEMP, principal / _STATE


def create_principal_layout(role: InspectorRole, root: Path) -> tuple[Path, Path, Path]:
    """Allocate a clean provider-specific configuration without reading the runner home."""
    create_principal_directory(role, root, root / role.value)
    paths = principal_layout_paths(role, root)
    for path in paths:
        create_principal_directory(role, root, path)
    return paths


def install_principal_file(
    role: InspectorRole,
    temporary_root: Path,
    destination: Path,
    content: bytes,
    *,
    mode: str = _FILE_MODE_TEXT,
    max_bytes: int = _FILE_BOUND,
) -> None:
    """Write exclusive private bytes directly; no privileged transfer or secret argv."""
    del role
    _owned_path(temporary_root, destination)
    if len(content) > max_bytes:
        raise ValueError(_INVALID_PATH)
    with destination.open(_WRITE_BINARY) as output:
        os.fchmod(output.fileno(), int(mode, 8))
        output.write(content)


def validate_principal_file_absent(role: InspectorRole, temporary_root: Path, target: Path) -> None:
    """Validate a fresh contained report output without following links."""
    del role
    _owned_path(temporary_root, target)
    if target.exists() or target.is_symlink():
        raise ValueError(_INVALID_PATH)


def validate_principal_file(role: InspectorRole, root: Path, target: Path, *, mode: str = _FILE_MODE_TEXT) -> None:
    """Require owned regular private files with the exact declared mode."""
    del role
    _owned_path(root, target)
    metadata = target.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != int(mode, 8):
        raise ValueError(_INVALID_PATH)


def read_principal_file(role: InspectorRole, path: Path, max_bytes: int = _FILE_BOUND) -> bytes:
    """Read bounded owned regular private files using a no-follow descriptor."""
    del role
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, mode=_READ_BINARY) as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_size > max_bytes:
            raise ValueError(_INVALID_PATH)
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(_INVALID_PATH)
    return bytes(content)


_READ_BINARY = "rb"


def make_read_only_tree(root: Path) -> None:
    """Make immutable evidence readable; native model-tool controls enforce write denial."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError(_INVALID_PATH)
    for path in (*root.rglob(_GLOB), root):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(_INVALID_PATH)
        path.chmod(_READ_DIRECTORY_MODE if path.is_dir() else _READ_FILE_MODE)


def _subreaper() -> None:
    """Adopt detached native descendants in this single-purpose Linux controller process."""
    if ctypes.CDLL(None, use_errno=True).prctl(_SUBREAPER_OPTION, 1, 0, 0, 0) != 0:
        raise InspectorBoundaryError(_BOUNDARY_FAILED)


def settle_inspector_principal(role: InspectorRole) -> None:
    """Reap this controller's adopted children without targeting other runner processes."""
    del role
    deadline = monotonic() + _GRACE
    children = _CHILDREN / str(os.getpid()) / _CHILDREN_FILE
    while True:
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        pending = [int(pid) for pid in children.read_text().split()]
        if not pending:
            return
        for pid in pending:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if monotonic() > deadline:
            raise InspectorBoundaryError(_BOUNDARY_FAILED)


def run_isolated_process(
    role: InspectorRole,
    executable: Path,
    arguments: Sequence[str],
    working_directory: Path,
    environment: Mapping[str, str],
    *,
    controller_directory: Path,
    stdin: bytes = _EMPTY,
    timeout_seconds: int = _TIMEOUT,
) -> IsolatedProcessResult:
    """Run the native CLI directly with exact stdin, explicit env and bounded descendants."""
    allowed = _USER_KEYS | (_CODEX_KEYS if role is InspectorRole.CODEX else _CLAUDE_KEYS)
    if not environment or not set(environment).issubset(allowed):
        raise ValueError(_INVALID_ENVIRONMENT)
    if controller_directory.is_symlink() or not working_directory.is_dir() or working_directory.is_symlink():
        raise ValueError(_INVALID_PATH)
    _subreaper()
    started = monotonic()
    timed_out = False
    with subprocess.Popen(
        [str(executable), *arguments],
        cwd=working_directory,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    ) as process:
        try:
            output = process.communicate(stdin, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=_GRACE)
            settle_inspector_principal(role)
            output = process.communicate(timeout=_GRACE)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            settle_inspector_principal(role)
        status = process.returncode if process.returncode is not None else _UNKNOWN_STATUS
    if any(len(part) > _OUTPUT_BOUND for part in output):
        raise InspectorBoundaryError(_OUTPUT_FAILED)
    return IsolatedProcessResult(
        return_code=_TIMEOUT_STATUS if timed_out else status,
        stdout=output[0],
        stderr=output[1],
        timed_out=timed_out,
        elapsed_seconds=monotonic() - started,
    )


def remove_principal_tree(role: InspectorRole, root: Path, target: Path) -> None:
    """Remove only a contained owned private provider tree."""
    settle_inspector_principal(role)
    _owned_path(root, target)
    shutil.rmtree(target)


def remove_controller_root(root: Path, *, temporary_parent: Path) -> None:
    """Remove only owned job-local controller state after native process settlement."""
    validate_controller_root(root, temporary_parent=temporary_parent)
    if root.stat().st_uid != os.getuid():
        raise ValueError(_INVALID_PATH)
    shutil.rmtree(root)
