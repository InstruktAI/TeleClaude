"""Controller-owned Linux process isolation shared by release inspectors."""

from __future__ import annotations

import grp
import json
import os
import platform
import pwd
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from time import monotonic

from pydantic import BaseModel, ConfigDict

from tools.release.inspector_fs import FilesystemOperation

_LINUX_SYSTEM = "Linux"
_SUDO_BINARY = "sudo"
_PKILL_BINARY = "pkill"
_PGREP_BINARY = "pgrep"
_PYTHON_BINARY = "python3"
_USERADD_BINARY = "useradd"
_STAT_BINARY = "stat"
_CAT_BINARY = "cat"
_REMOVE_BINARY = "rm"
_SYSTEM_USER_ARGUMENTS = (
    "--system",
    "--user-group",
    "--no-create-home",
    "--home-dir",
    "/nonexistent",
    "--shell",
    "/usr/sbin/nologin",
)
_NOLOGIN_SHELL = "/usr/sbin/nologin"
_NONEXISTENT_HOME = "/nonexistent"
_CONTROLLER_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_SUDO_ENVIRONMENT = {"PATH": _CONTROLLER_PATH, "HOME": "/"}
_USER_ENVIRONMENT_KEYS = frozenset({"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"})
_CODEX_ENVIRONMENT_KEYS = frozenset({"CODEX_HOME"})
_CLAUDE_ENVIRONMENT_KEYS = frozenset({"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN"})
_LAUNCHER = Path(__file__).with_name("inspector_exec.py")
_FILESYSTEM_HELPER = Path(__file__).with_name("inspector_fs.py")
_LAUNCHER_PAYLOAD_SEPARATOR = b"\n"
_ENVIRONMENT_ENCODING = "utf-8"
_SUDO_NONINTERACTIVE = "-n"
_SUDO_USER_FLAG = "-u"
_SUDO_SEPARATOR = "--"
_FILESYSTEM_SOURCE_OPTION = "--source"
_FILESYSTEM_MODE_OPTION = "--mode"
_PRIVATE_FILE_MODE = "600"
_READ_ONLY_DIRECTORY_MODE = 0o555
_READ_ONLY_FILE_MODE = 0o444
_TERMINATE_UID_FLAG = "-TERM"
_KILL_UID_FLAG = "-KILL"
_UID_FLAG = "-u"
_STAT_SIZE_ARGUMENT = "--format=%s"
_OPTION_END = "--"
_RECURSIVE_GLOB = "*"
_RECURSIVE_FLAG = "-r"
_FORCE_FLAG = "-f"
_TIMEOUT_SECONDS = 600
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_PRIVATE_FILE_BYTES = 4 * 1024 * 1024
_CONTROLLER_COMMAND_TIMEOUT_SECONDS = 30
_PROCESS_TERMINATION_GRACE_SECONDS = 2
_TIMEOUT_RETURN_CODE = 124
_UNKNOWN_RETURN_CODE = 125
_INVALID_PLATFORM = "Release inspector isolation requires a Linux hosted runner."
_SYSTEM_TOOL_MISSING = "A required Linux process-isolation command is unavailable."
_USER_CREATION_FAILED = "The dedicated inspector account could not be created."
_USER_IDENTITY_INVALID = "The inspector account does not have a dedicated unprivileged identity."
_USER_PROCESS_REMAINS = "An inspector process remained after its execution boundary closed."
_ENVIRONMENT_INVALID = "The inspector environment contains a capability outside its allowlist."
_WORKING_DIRECTORY_INVALID = "The inspector working directory is unavailable or unsafe."
_INSPECTOR_COMMAND_FAILED = "The isolated inspector process could not be started."
_INSPECTOR_TIMED_OUT = "The isolated inspector exceeded its execution deadline."
_INSPECTOR_OUTPUT_LIMIT = "The isolated inspector exceeded its output bound."
_PRIVATE_PATH_INVALID = "A private inspector path is outside its caller-owned temporary root."
_PRIVATE_FILE_TOO_LARGE = "The private inspector file exceeds its configured size limit."
_CONTROLLER_STAGING_DIRECTORY = "inspector-controller-staging"
_PRINCIPAL_HOME_DIRECTORY = "home"
_PRINCIPAL_TEMP_DIRECTORY = "tmp"
_STATE_DIRECTORY = "state"
_LAUNCHER_ARGUMENT = str(_LAUNCHER)
_COMMA = ","
_EMPTY_BYTES = b""
_COLON = ":"
_NO_PROCESS_STATUS = 1
_PROCESS_FOUND_STATUS = 0
_PRIVATE_FILE_MODE_INT = 0o600
_PRIVATE_ROOT_INITIAL_MODE = 0o700
_CONTROLLER_ROOT_MODE = 0o711
_PROCESS_CLEANUP_FAILED = "The inspector's process boundary could not be fully closed."


class InspectorRole(StrEnum):
    """Unprivileged operating-system identities assigned to release providers."""

    CODEX = "release-codex-inspector"
    CLAUDE = "release-claude-inspector"


class IsolatedProcessResult(BaseModel):
    """Captured process output after every child of the dedicated UID is reaped."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    return_code: int
    stdout: bytes
    stderr: bytes
    timed_out: bool
    elapsed_seconds: float


class InspectorBoundaryError(RuntimeError):
    """A process or credential boundary could not be proven closed."""


class FilesystemFailure(BaseModel):
    """Secret-free failure metadata emitted by the privileged filesystem helper."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    exception_type: str
    errno: int | None


class InspectorSetupError(RuntimeError):
    """A controller command failed with bounded, message-free native evidence."""

    def __init__(
        self,
        *,
        exception_type: str,
        errno: int | None = None,
        native_status: int | None = None,
        filesystem_operation: FilesystemOperation | None = None,
    ) -> None:
        super().__init__(_INSPECTOR_COMMAND_FAILED)
        self.exception_type = exception_type
        self.errno = errno
        self.native_status = native_status
        self.filesystem_operation = filesystem_operation


def ensure_inspector_principal(role: InspectorRole) -> pwd.struct_passwd:
    """Create or verify one non-login, single-group service identity on the hosted runner."""
    if platform.system() != _LINUX_SYSTEM:
        raise RuntimeError(_INVALID_PLATFORM)
    try:
        account = pwd.getpwnam(role.value)
    except KeyError:
        useradd = _system_binary(_USERADD_BINARY)
        result = _run_controller_command([useradd, *_SYSTEM_USER_ARGUMENTS, role.value])
        if result.returncode != 0:
            raise RuntimeError(_USER_CREATION_FAILED) from None
        try:
            account = pwd.getpwnam(role.value)
        except KeyError:
            raise RuntimeError(_USER_CREATION_FAILED) from None
    group = grp.getgrgid(account.pw_gid)
    supplementary_groups = os.getgrouplist(account.pw_name, account.pw_gid)
    if (
        account.pw_shell != _NOLOGIN_SHELL
        or account.pw_dir != _NONEXISTENT_HOME
        or group.gr_name != role.value
        or supplementary_groups != [account.pw_gid]
    ):
        raise RuntimeError(_USER_IDENTITY_INVALID)
    return account


def create_principal_directory(role: InspectorRole, root: Path, directory: Path) -> Path:
    """Create a mode-0700 directory owned by the selected isolated provider identity."""
    account = ensure_inspector_principal(role)
    _run_filesystem_operation(FilesystemOperation.CREATE_DIRECTORY, root, directory, account.pw_uid, account.pw_gid)
    return directory


def validate_controller_root(root: Path, *, temporary_parent: Path) -> None:
    """Require a non-symlink controller root within the caller's resolved temporary parent."""
    resolved = root.resolve()
    parent = temporary_parent.resolve()
    if not resolved.is_relative_to(parent) or resolved == parent or root.is_symlink():
        raise ValueError(_PRIVATE_PATH_INVALID)


def create_controller_root(root: Path, *, temporary_parent: Path) -> Path:
    """Create the private controller parent that contains isolated UID state and staging files."""
    validate_controller_root(root, temporary_parent=temporary_parent)
    if root.exists():
        raise ValueError(_PRIVATE_PATH_INVALID)
    root.mkdir(mode=_PRIVATE_ROOT_INITIAL_MODE, parents=True)
    root.chmod(_CONTROLLER_ROOT_MODE)
    return root


def create_principal_layout(role: InspectorRole, root: Path) -> tuple[Path, Path, Path]:
    """Create isolated HOME, temporary, and provider-state directories."""
    principal_root = root / role.value
    create_principal_directory(role, root, principal_root)
    home = create_principal_directory(role, root, principal_root / _PRINCIPAL_HOME_DIRECTORY)
    temporary = create_principal_directory(role, root, principal_root / _PRINCIPAL_TEMP_DIRECTORY)
    state = create_principal_directory(role, root, principal_root / _STATE_DIRECTORY)
    return home, temporary, state


def install_principal_file(
    role: InspectorRole,
    temporary_root: Path,
    destination: Path,
    content: bytes,
    *,
    mode: str = _PRIVATE_FILE_MODE,
    max_bytes: int = _MAX_PRIVATE_FILE_BYTES,
) -> None:
    """Install controller bytes into the isolated identity's private state directory."""
    account = ensure_inspector_principal(role)
    if len(content) > max_bytes:
        raise ValueError(_PRIVATE_FILE_TOO_LARGE)
    staging = temporary_root / _CONTROLLER_STAGING_DIRECTORY
    if staging.exists() and (staging.is_symlink() or not staging.is_dir()):
        raise ValueError(_PRIVATE_PATH_INVALID)
    staging.mkdir(mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=staging, delete=False) as source:
        source.write(content)
        staging_path = Path(source.name)
    os.chmod(staging_path, _PRIVATE_FILE_MODE_INT)
    try:
        _run_filesystem_operation(
            FilesystemOperation.INSTALL_FILE,
            temporary_root,
            destination,
            account.pw_uid,
            account.pw_gid,
            (_FILESYSTEM_SOURCE_OPTION, str(staging_path), _FILESYSTEM_MODE_OPTION, mode),
        )
    finally:
        staging_path.unlink(missing_ok=True)


def read_principal_file(role: InspectorRole, path: Path, max_bytes: int = _MAX_PRIVATE_FILE_BYTES) -> bytes:
    """Read one private inspector-owned file through the trusted controller boundary."""
    account = ensure_inspector_principal(role)
    stat_binary = _system_binary(_STAT_BINARY)
    stat_result = _run_controller_command(
        [_SUDO_USER_FLAG, account.pw_name, _SUDO_SEPARATOR, stat_binary, _STAT_SIZE_ARGUMENT, str(path)]
    )
    if stat_result.returncode != 0:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED)
    try:
        size = int(stat_result.stdout.strip())
    except ValueError:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED) from None
    if size > max_bytes:
        raise ValueError(_PRIVATE_FILE_TOO_LARGE)
    cat = _system_binary(_CAT_BINARY)
    read_result = _run_controller_command(
        [_SUDO_USER_FLAG, account.pw_name, _SUDO_SEPARATOR, cat, _OPTION_END, str(path)]
    )
    if read_result.returncode != 0 or len(read_result.stdout) > max_bytes:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED)
    return read_result.stdout


def make_read_only_tree(root: Path) -> None:
    """Make every source-evidence file readable but immutable to isolated principals."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError(_WORKING_DIRECTORY_INVALID)
    for path in root.rglob(_RECURSIVE_GLOB):
        if path.is_symlink():
            raise ValueError(_WORKING_DIRECTORY_INVALID)
        path.chmod(_READ_ONLY_DIRECTORY_MODE if path.is_dir() else _READ_ONLY_FILE_MODE)
    root.chmod(_READ_ONLY_DIRECTORY_MODE)


def run_isolated_process(
    role: InspectorRole,
    executable: Path,
    arguments: Sequence[str],
    working_directory: Path,
    environment: Mapping[str, str],
    *,
    stdin: bytes = _EMPTY_BYTES,
    timeout_seconds: int = _TIMEOUT_SECONDS,
) -> IsolatedProcessResult:
    """Run one CLI with a strict child environment and reap its UID before returning."""
    account = ensure_inspector_principal(role)
    _validate_environment(role, environment)
    if not working_directory.is_dir() or working_directory.is_symlink():
        raise ValueError(_WORKING_DIRECTORY_INVALID)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise FileNotFoundError(_SYSTEM_TOOL_MISSING)
    sudo = _system_binary(_SUDO_BINARY)
    python = _system_binary(_PYTHON_BINARY)
    command = [
        sudo,
        _SUDO_NONINTERACTIVE,
        _SUDO_USER_FLAG,
        account.pw_name,
        _SUDO_SEPARATOR,
        python,
        _LAUNCHER_ARGUMENT,
        str(executable),
        *arguments,
    ]
    payload = json.dumps(dict(environment), separators=(_COMMA, _COLON)).encode(_ENVIRONMENT_ENCODING)
    started = monotonic()
    process: subprocess.Popen[bytes] | None = None
    timed_out = False
    output = (_EMPTY_BYTES, _EMPTY_BYTES)
    try:
        process = subprocess.Popen(
            command,
            cwd=working_directory,
            env=_SUDO_ENVIRONMENT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
        output = process.communicate(payload + _LAUNCHER_PAYLOAD_SEPARATOR + stdin, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        if process is not None:
            output = _terminate_process_tree(process, account.pw_name)
    except OSError:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED) from None
    finally:
        if process is not None and process.poll() is None:
            output = _terminate_process_tree(process, account.pw_name)
        _reap_principal(account.pw_name)
    elapsed = monotonic() - started
    if len(output[0]) > _MAX_OUTPUT_BYTES or len(output[1]) > _MAX_OUTPUT_BYTES:
        raise RuntimeError(_INSPECTOR_OUTPUT_LIMIT)
    if _principal_has_processes(account.pw_name):
        raise RuntimeError(_USER_PROCESS_REMAINS)
    if timed_out:
        return IsolatedProcessResult(
            return_code=_TIMEOUT_RETURN_CODE,
            stdout=output[0],
            stderr=output[1],
            timed_out=True,
            elapsed_seconds=elapsed,
        )
    if process is None:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED)
    return IsolatedProcessResult(
        return_code=process.returncode if process.returncode is not None else _UNKNOWN_RETURN_CODE,
        stdout=output[0],
        stderr=output[1],
        timed_out=False,
        elapsed_seconds=elapsed,
    )


def remove_principal_tree(role: InspectorRole, root: Path, target: Path) -> None:
    """Remove a generated private principal tree after all of its processes have exited."""
    account = ensure_inspector_principal(role)
    if not target.resolve().is_relative_to(root.resolve()) or target.resolve() == root.resolve():
        raise ValueError(_PRIVATE_PATH_INVALID)
    if target.is_symlink():
        raise ValueError(_PRIVATE_PATH_INVALID)
    if _principal_has_processes(account.pw_name):
        raise RuntimeError(_USER_PROCESS_REMAINS)
    remove = _system_binary(_REMOVE_BINARY)
    result = _run_controller_command([remove, _RECURSIVE_FLAG, _FORCE_FLAG, _OPTION_END, str(target)])
    if result.returncode != 0:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED)


def remove_controller_root(root: Path, *, temporary_parent: Path) -> None:
    """Remove the now-empty controller root after isolated principals are removed."""
    validate_controller_root(root, temporary_parent=temporary_parent)
    shutil.rmtree(root)


def _validate_environment(role: InspectorRole, environment: Mapping[str, str]) -> None:
    """Reject every child environment key outside the provider's declared allowlist."""
    allowed = _USER_ENVIRONMENT_KEYS
    if role is InspectorRole.CODEX:
        allowed = allowed | _CODEX_ENVIRONMENT_KEYS
    else:
        allowed = allowed | _CLAUDE_ENVIRONMENT_KEYS
    if not environment or not set(environment).issubset(allowed):
        raise ValueError(_ENVIRONMENT_INVALID)


def _system_binary(name: str) -> str:
    """Resolve a controller system utility from the trusted runner path."""
    binary = shutil.which(name, path=_CONTROLLER_PATH)
    if binary is None:
        raise FileNotFoundError(_SYSTEM_TOOL_MISSING)
    return binary


def _run_controller_command(arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    """Run a small trusted setup command through sudo without passing secrets in argv."""
    # The hosted runner's native account APIs cannot create or switch a POSIX UID; sudo is the platform boundary.
    sudo = _system_binary(_SUDO_BINARY)
    command = [sudo, _SUDO_NONINTERACTIVE, *arguments]
    try:
        return subprocess.run(
            command,
            env=_SUDO_ENVIRONMENT,
            input=_EMPTY_BYTES,
            capture_output=True,
            check=False,
            timeout=_CONTROLLER_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InspectorSetupError(
            exception_type=type(error).__name__, errno=error.errno if isinstance(error, OSError) else None
        ) from None


def _run_filesystem_operation(
    operation: FilesystemOperation,
    root: Path,
    target: Path,
    uid: int,
    gid: int,
    options: Sequence[str] = (),
) -> None:
    """Check and mutate private paths within the same privileged process, never the controller UID."""
    python = _system_binary(_PYTHON_BINARY)
    result = _run_controller_command(
        [python, str(_FILESYSTEM_HELPER), operation, str(root), str(target), str(uid), str(gid), *options]
    )
    if result.returncode != 0:
        try:
            failure = FilesystemFailure.model_validate_json(result.stdout)
        except ValueError:
            raise InspectorSetupError(
                exception_type=RuntimeError.__name__, native_status=result.returncode, filesystem_operation=operation
            ) from None
        raise InspectorSetupError(
            exception_type=failure.exception_type,
            errno=failure.errno,
            native_status=result.returncode,
            filesystem_operation=operation,
        ) from None


def _terminate_process_tree(process: subprocess.Popen[bytes], username: str) -> tuple[bytes, bytes]:
    """Terminate the group and UID, then reap bounded pipe readers."""
    pkill = _system_binary(_PKILL_BINARY)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _run_controller_command([pkill, _TERMINATE_UID_FLAG, _UID_FLAG, username])
    try:
        return process.communicate(timeout=_PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _run_controller_command([pkill, _KILL_UID_FLAG, _UID_FLAG, username])
        try:
            return process.communicate(timeout=_PROCESS_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            raise InspectorBoundaryError(_PROCESS_CLEANUP_FAILED) from None


def _reap_principal(username: str) -> None:
    """Kill any descendants the process group could not reap, then verify the UID is idle."""
    pkill = _system_binary(_PKILL_BINARY)
    pgrep = _system_binary(_PGREP_BINARY)
    _run_controller_command([pkill, _TERMINATE_UID_FLAG, _UID_FLAG, username])
    _run_controller_command([pkill, _KILL_UID_FLAG, _UID_FLAG, username])
    if _principal_has_processes(username, pgrep=pgrep):
        raise InspectorBoundaryError(_USER_PROCESS_REMAINS)


def _principal_has_processes(username: str, *, pgrep: str | None = None) -> bool:
    """Check whether the dedicated UID has any remaining processes."""
    process_grep = pgrep if pgrep is not None else _system_binary(_PGREP_BINARY)
    result = _run_controller_command([process_grep, _UID_FLAG, username])
    if result.returncode not in {_NO_PROCESS_STATUS, _PROCESS_FOUND_STATUS}:
        raise RuntimeError(_INSPECTOR_COMMAND_FAILED)
    return result.returncode == 0
