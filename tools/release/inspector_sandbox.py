"""Bounded Linux observations for a credential-free, controller-owned sandbox probe."""

from __future__ import annotations

import array
import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal, TypedDict, cast


class NativeSyscall(StrEnum):
    """Closed set of native operations permitted in retained trace metadata."""

    EXECVE = "execve"
    EXECVEAT = "execveat"
    CLONE = "clone"
    CLONE3 = "clone3"
    FORK = "fork"
    VFORK = "vfork"
    UNSHARE = "unshare"
    SETNS = "setns"
    PRCTL = "prctl"
    CAPGET = "capget"
    CAPSET = "capset"
    SOCKET = "socket"
    SENDMSG = "sendmsg"
    IOCTL = "ioctl"


class NativeErrno(StrEnum):
    """Recognized errno dispositions; unrecognized native errors remain unspecified."""

    EACCES = "EACCES"
    EPERM = "EPERM"
    EINVAL = "EINVAL"
    ENOSYS = "ENOSYS"
    ENOENT = "ENOENT"
    EIO = "EIO"
    ENOSPC = "ENOSPC"
    EAGAIN = "EAGAIN"
    ENOMEM = "ENOMEM"
    EBADF = "EBADF"
    EFAULT = "EFAULT"
    EOPNOTSUPP = "EOPNOTSUPP"


class DiagnosticGap(StrEnum):
    """Shared closed vocabulary for unavailable owned sandbox observations."""

    STRACE = "trusted_strace_unavailable"
    AUDIT = "correlated_kernel_audit_not_collected"
    PROCESS = "fast_or_inaccessible_process_metadata_may_be_absent"
    UID = "provider_uid_metadata_unavailable"
    POLICY = "effective_native_policy_not_observed"
    HELPER = "selected_helper_identity_or_version_not_observed"
    OWNER = "namespace_owner_uid_not_collected"
    PLATFORM = "platform_metadata_incomplete"


SANDBOX_ARGUMENTS = (
    "sandbox",
    "--profile",
    "release-inspector",
    "--permission-profile",
    "release-inspector",
    "--include-managed-config",
    "--",
    "/bin/true",
)
SNAPSHOT_OPTION = "--snapshot"
TRACE_OPTION = "--trace"
_PROC = Path("/proc")
_SHARED_PARENT = Path("/tmp")
_STATUS = "status"
_STAT = "stat"
_UID_MAP = "uid_map"
_GID_MAP = "gid_map"
_LABEL = "attr/current"
_EXE = "exe"
_CMDLINE = "cmdline"
_USER_NAMESPACE = "ns/user"
_NETWORK_NAMESPACE = "ns/net"
_SELF = "self"
_UTF8 = "utf-8"
_COLON = ":"
_NUL = b"\0"
_SHA256 = "sha256:"
_STATUS_KEYS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs", "Seccomp", "Seccomp_filters")
_UIDS = "Uid"
_GIDS = "Gid"
_UNSIGNED_INT = "I"
_NS_GET_OWNER_UID = 0xB704
_HEX = re.compile(r"[0-9a-fA-F]{1,32}")
_INTEGER = re.compile(r"[0-9]{1,20}")
_SYSCALLS = frozenset(NativeSyscall)
_TRACE_SELECTION = "trace=" + ",".join(sorted(_SYSCALLS))
_TRACE_FLAGS = ("-f", "-qq", "-e", _TRACE_SELECTION, "-e", "raw=all", "-o")
_SYSCALL_RESULT = re.compile(r"(?:(\d+)\s+)?([a-z][a-z0-9_]*)\(.*\)\s+=\s+(-?\d+|0x[0-9a-f]+)(?:\s+([A-Z][A-Z0-9_]+))?")
_SUDO = "/usr/bin/sudo"
_PYTHON = "/usr/bin/python3"
_STRACE = Path("/usr/bin/strace")
_CONTROLLER = "controller"
_PRIVATE = "inspector-controller-staging"
_CLAIM = "ownership.json"
_LAUNCHER = "inspector-launcher/inspector_exec.py"
_TOOLCHAIN = "toolchain"
_CODEX = "bin/codex"
_NODE = "bin/node"
_EVIDENCE = "evidence"
_ROLE = "release-codex-inspector"
_HOME = "home"
_TEMP = "tmp"
_CONFIG = "state/codex-home"
_AUTH = "auth.json"
_PREFIX = "teleclaude-inspection-"
_NONEXISTENT = "/nonexistent"
_NOLOGIN = "/usr/sbin/nologin"
_SYSTEM_PATH = ":/usr/local/bin:/usr/bin:/bin"
_ROOT_ENVIRONMENT = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/"}
_ENV_HOME = "HOME"
_ENV_PATH = "PATH"
_ENV_TEMP = "TMPDIR"
_ENV_CONFIG = "CODEX_HOME"
_ENV_LANG = "LANG"
_ENV_LOCALE = "LC_ALL"
_LANGUAGE = "C.UTF-8"
_NEWLINE = b"\n"
_EMPTY = b""
_PERMISSION_ARGUMENT = b"--permission-profile"
_POLICY_TYPE = "type"
_NETWORK = "network"
_FILESYSTEM = "file_system"
_ENTRIES = "entries"
_ACCESS = "access"
_READ = "read"
_WRITE = "write"
_DENY = "deny"
_INVALID = "Sandbox diagnostic request refused."
_REQUEST_KEYS = frozenset({"namespace", "owner_uid", "device", "inode", "claim"})
_REQUEST_NAMESPACE: Final = "namespace"
_REQUEST_UID: Final = "owner_uid"
_REQUEST_DEVICE: Final = "device"
_REQUEST_INODE: Final = "inode"
_REQUEST_CLAIM: Final = "claim"
_MAX_REQUEST = 16384
_MAX_PROC_READ = 131072
_MAX_TRACE = 4 * 1024 * 1024
_MAX_OBSERVATIONS = 64
_MAX_EXECUTABLE = 256 * 1024 * 1024
_TIMEOUT = 60
_POLL_INTERVAL = 0.005
_TRACE_PREFIX = "sandbox-numeric-trace-"
_EXCEPTION_KEY = "exception_type"
_ERRNO_KEY = "errno"
_KNOWN_ERRORS = frozenset(NativeErrno)


class TraceRequest(TypedDict):
    """A fixed owned locator supplies no execution or process-selection capability."""

    namespace: object
    owner_uid: object
    device: object
    inode: object
    claim: object


class ExecutableIdentity(StrEnum):
    """Only fixed executable categories are exported, never observed paths."""

    CODEX = "owned_codex"
    NODE = "owned_node"
    BWRAP = "system_bwrap"
    DESCRIPTOR = "descriptor_backed"
    OTHER = "other"


class Enforcement(StrEnum):
    """Pinned native permission-profile enforcement tags."""

    MANAGED = "managed"
    DISABLED = "disabled"
    EXTERNAL = "external"


class NetworkPolicy(StrEnum):
    """Pinned native network policy variants."""

    RESTRICTED = "restricted"
    ENABLED = "enabled"


class FileSystemPolicy(StrEnum):
    """Pinned native managed filesystem variants."""

    RESTRICTED = "restricted"
    UNRESTRICTED = "unrestricted"


@dataclass(frozen=True)
class ExecutableFacts:
    """Observed executable content, including a deleted or memfd-backed executable."""

    sha256: str
    owner_uid: int
    owner_gid: int
    mode: int
    descriptor_backed: bool
    owned_runtime: bool
    identity: ExecutableIdentity


@dataclass(frozen=True)
class PolicyFacts:
    """Only recognized fields from an observed native helper policy, never its path payload."""

    sha256: str
    enforcement: Enforcement
    network: NetworkPolicy | None
    filesystem: FileSystemPolicy | None
    read_entries: int
    write_entries: int
    deny_entries: int


@dataclass(frozen=True)
class ProcessFacts:
    """Facts sampled from one owned process; absent fields are observation gaps."""

    pid: int
    uids: list[int]
    gids: list[int]
    uid_map: list[list[int]]
    gid_map: list[list[int]]
    status: dict[str, str]
    user_namespace: int | None
    user_namespace_owner_uid: int | None
    network_namespace: int | None
    lsm_label_sha256: str | None
    executable: ExecutableFacts | None
    policy: PolicyFacts | None


@dataclass(frozen=True)
class SyscallFacts:
    """Numeric raw tracing supplies outcomes without argument or output bodies."""

    pid: int | None
    syscall: NativeSyscall
    errno: NativeErrno | None
    failed: bool
    occurrences: int


@dataclass(frozen=True)
class TraceFacts:
    """At most one failure-only trace, bounded observations and explicit collection gaps."""

    native_status: int | None = None
    timed_out: bool = False
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    strace_sha256: str | None = None
    processes: list[ProcessFacts] = field(default_factory=list)
    syscalls: list[SyscallFacts] = field(default_factory=list)
    gaps: list[DiagnosticGap] = field(default_factory=lambda: [DiagnosticGap.AUDIT, DiagnosticGap.PROCESS])


def _hash(content: bytes) -> str:
    """Hash content without exporting its representation."""
    return _SHA256 + hashlib.sha256(content).hexdigest()


def _bounded_read(path: Path, maximum: int = _MAX_PROC_READ) -> bytes:
    """Bound transient proc/request reads before decoding."""
    with path.open(_BINARY_READ) as source:
        content = source.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError(_INVALID)
    return content


_BINARY_READ: Literal["rb"] = "rb"


def _map(path: Path) -> list[list[int]]:
    """Export numeric mappings only."""
    lines = _bounded_read(path).decode(_UTF8).splitlines()
    if len(lines) > 16:
        raise ValueError(_INVALID)
    return [
        [int(value) for value in line.split()] for line in lines if all(_INTEGER.fullmatch(v) for v in line.split())
    ]


def _executable(path: Path, runtime: Path | None) -> ExecutableFacts | None:
    """Read only the executable of the process being sampled, not arbitrary file descriptors."""
    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_EXECUTABLE:
            return None
        target = path.resolve()
        identity = ExecutableIdentity.OTHER
        if not target.exists():
            identity = ExecutableIdentity.DESCRIPTOR
        elif target == _SYSTEM_BWRAP:
            identity = ExecutableIdentity.BWRAP
        elif runtime is not None and target.is_relative_to(runtime):
            if target.name == _NODE_NAME:
                identity = ExecutableIdentity.NODE
            elif target.name == _CODEX_NAME:
                identity = ExecutableIdentity.CODEX
        digest = hashlib.sha256()
        with path.open(_BINARY_READ) as source:
            while content := source.read(_MAX_PROC_READ):
                digest.update(content)
        return ExecutableFacts(
            _SHA256 + digest.hexdigest(),
            metadata.st_uid,
            metadata.st_gid,
            stat.S_IMODE(metadata.st_mode),
            not target.exists(),
            runtime is not None and target.is_relative_to(runtime),
            identity,
        )
    except OSError:
        return None


def _policy(path: Path) -> PolicyFacts | None:
    """Discard argv after inspecting only a native JSON permission-profile field."""
    arguments = _bounded_read(path).split(_NUL)
    if arguments.count(_PERMISSION_ARGUMENT) != 1:
        return None
    index = arguments.index(_PERMISSION_ARGUMENT) + 1
    if index >= len(arguments):
        return None
    try:
        content = arguments[index]
        payload: object = json.loads(content)
        if not isinstance(payload, dict):
            return None
        enforcement = payload.get(_POLICY_TYPE)
        if enforcement not in frozenset(Enforcement):
            return None
        network = payload.get(_NETWORK)
        filesystem = payload.get(_FILESYSTEM)
        kind = filesystem.get(_POLICY_TYPE) if isinstance(filesystem, dict) else None
        entries = filesystem.get(_ENTRIES, []) if isinstance(filesystem, dict) else []
        if not isinstance(entries, list) or len(entries) > 4096:
            return None
        modes = [entry.get(_ACCESS) for entry in entries if isinstance(entry, dict)]
        return PolicyFacts(
            _hash(content),
            Enforcement(enforcement),
            NetworkPolicy(network) if network in frozenset(NetworkPolicy) else None,
            FileSystemPolicy(kind) if kind in frozenset(FileSystemPolicy) else None,
            modes.count(_READ),
            modes.count(_WRITE),
            modes.count(_DENY),
        )
    except (ValueError, UnicodeError, TypeError):
        return None


def process_facts(pid: int, runtime: Path | None = None) -> ProcessFacts:
    """Sample only the calling process or a descendant selected by the fixed trace supervisor."""
    root = _PROC / str(pid)
    policy = _policy(root / _CMDLINE)
    status: dict[str, str] = {}
    uids: list[int] = []
    gids: list[int] = []
    for line in _bounded_read(root / _STATUS).decode(_UTF8).splitlines():
        key, separator, value = line.partition(_COLON)
        value = value.strip()
        if separator and key in _STATUS_KEYS and (_HEX.fullmatch(value) or _INTEGER.fullmatch(value)):
            status[key] = value
        if separator and key in {_UIDS, _GIDS} and all(_INTEGER.fullmatch(v) for v in value.split()):
            if key == _UIDS:
                uids = [int(v) for v in value.split()]
            else:
                gids = [int(v) for v in value.split()]
    label = None
    try:
        label = _hash(_bounded_read(root / _LABEL))
    except OSError:
        pass
    user_ns, network_ns, namespace_owner = None, None, None
    try:
        user_ns = (root / _USER_NAMESPACE).stat().st_ino
        network_ns = (root / _NETWORK_NAMESPACE).stat().st_ino
        with (root / _USER_NAMESPACE).open(_BINARY_READ) as namespace:
            owner = array.array(_UNSIGNED_INT, [0])
            fcntl.ioctl(namespace.fileno(), _NS_GET_OWNER_UID, owner, True)
            namespace_owner = owner[0]
    except OSError:
        pass
    return ProcessFacts(
        pid,
        uids,
        gids,
        _map(root / _UID_MAP),
        _map(root / _GID_MAP),
        status,
        user_ns,
        namespace_owner,
        network_ns,
        label,
        _executable(root / _EXE, runtime),
        policy,
    )


def _check_path(path: Path, uid: int, mode: int, *, directory: bool) -> None:
    """Refuse links and unexpected content authority for fixed controller-owned paths."""
    metadata = path.lstat()
    if (
        metadata.st_uid != uid
        or stat.S_IMODE(metadata.st_mode) != mode
        or not (stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode))
    ):
        raise ValueError(_INVALID)


def _request() -> tuple[Path, int]:
    """Accept only one fresh owned namespace; no PID, executable, environment or command selectors."""
    raw = sys.stdin.buffer.read(_MAX_REQUEST + 1)
    request: object = json.loads(raw)
    if len(raw) > _MAX_REQUEST or not isinstance(request, dict):
        raise ValueError(_INVALID)
    request = cast(TraceRequest, request)
    if frozenset(request) != _REQUEST_KEYS:
        raise ValueError(_INVALID)
    namespace_value, uid = request[_REQUEST_NAMESPACE], request[_REQUEST_UID]
    if not isinstance(namespace_value, str) or type(uid) is not int or uid <= 0:
        raise ValueError(_INVALID)
    device, inode, claim_value = request[_REQUEST_DEVICE], request[_REQUEST_INODE], request[_REQUEST_CLAIM]
    if type(device) is not int or type(inode) is not int or not isinstance(claim_value, str):
        raise ValueError(_INVALID)
    namespace = Path(namespace_value)
    if _SHARED_PARENT.is_symlink() or namespace.parent != _SHARED_PARENT or not namespace.name.startswith(_PREFIX):
        raise ValueError(_INVALID)
    _check_path(namespace, uid, 0o711, directory=True)
    metadata = namespace.lstat()
    if namespace.resolve() != namespace or (metadata.st_dev, metadata.st_ino) != (
        request[_REQUEST_DEVICE],
        request[_REQUEST_INODE],
    ):
        raise ValueError(_INVALID)
    controller = namespace / _CONTROLLER
    _check_path(controller, uid, 0o711, directory=True)
    _check_path(controller / _PRIVATE, uid, 0o700, directory=True)
    claim = controller / _PRIVATE / _CLAIM
    _check_path(claim, uid, 0o600, directory=False)
    if _bounded_read(claim).decode(_UTF8) != request[_REQUEST_CLAIM]:
        raise ValueError(_INVALID)
    launcher = controller / _LAUNCHER
    _check_path(launcher.parent, uid, 0o555, directory=True)
    _check_path(launcher, uid, 0o444, directory=False)
    if _bounded_read(launcher) != Path(__file__).with_name(_LAUNCHER_FILENAME).read_bytes():
        raise ValueError(_INVALID)
    for path in (namespace / _TOOLCHAIN / _CODEX, namespace / _TOOLCHAIN / _NODE):
        resolved = path.resolve(strict=True)
        if (
            not resolved.is_relative_to(namespace / _TOOLCHAIN)
            or resolved.stat().st_uid != uid
            or resolved.stat().st_mode & 0o222
        ):
            raise ValueError(_INVALID)
    account = pwd.getpwnam(_ROLE)
    if (
        account.pw_uid == uid
        or account.pw_uid == 0
        or account.pw_dir != _NONEXISTENT
        or account.pw_shell != _NOLOGIN
        or os.getgrouplist(_ROLE, account.pw_gid) != [account.pw_gid]
    ):
        raise ValueError(_INVALID)
    if (controller / _ROLE / _CONFIG / _AUTH).exists():
        raise ValueError(_INVALID)
    return namespace, uid


_LAUNCHER_FILENAME = "inspector_exec.py"


def _descendants(root_pid: int) -> set[int]:
    """Follow only kernel-maintained child lists starting at this supervisor's trace process."""
    children = {root_pid}
    pending = [root_pid]
    while pending and len(children) <= 256:
        pid = pending.pop()
        try:
            for task in (_PROC / str(pid) / _TASK).iterdir():
                for value in _bounded_read(task / _CHILDREN).split():
                    child = int(value)
                    if child not in children:
                        pending.append(child)
                        children.add(child)
        except (OSError, ValueError):
            continue
    return children


_TASK = "task"
_CHILDREN = "children"


def _trace_outcomes(content: bytes) -> list[SyscallFacts]:
    """Ignore everything except allowlisted syscall names and canonical errno dispositions."""
    counts: dict[tuple[int | None, NativeSyscall, NativeErrno | None, bool], int] = {}
    for line in content.decode(_UTF8, errors=_DECODE_ERRORS).splitlines():
        match = _SYSCALL_RESULT.match(line.strip())
        if match is None or match[2] not in _SYSCALLS:
            continue
        errno = NativeErrno(match[4]) if match[4] in _KNOWN_ERRORS else None
        key = (int(match[1]) if match[1] else None, NativeSyscall(match[2]), errno, match[3].startswith(_MINUS))
        counts[key] = counts.get(key, 0) + 1
    return [
        SyscallFacts(pid, name, error, failed, count)
        for (pid, name, error, failed), count in sorted(counts.items(), key=lambda item: (item[0][0] or 0, item[0][1]))
    ]


_DECODE_ERRORS = "replace"
_MINUS = "-"
_SYSTEM_BWRAP = Path("/usr/bin/bwrap")
_NODE_NAME = "node"
_CODEX_NAME = "codex"


def trace_probe() -> TraceFacts:
    """Trace one fixed sandbox command as its actual UID; retain no raw output or arguments."""
    namespace, _ = _request()
    if not _STRACE.exists():
        return TraceFacts(gaps=[DiagnosticGap.STRACE, DiagnosticGap.AUDIT, DiagnosticGap.PROCESS])
    metadata = _STRACE.stat()
    if metadata.st_uid != 0 or metadata.st_mode & 0o022 or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(_INVALID)
    controller = namespace / _CONTROLLER
    principal = controller / _ROLE
    environment = {
        _ENV_HOME: str(principal / _HOME),
        _ENV_TEMP: str(principal / _TEMP),
        _ENV_CONFIG: str(principal / _CONFIG),
        _ENV_PATH: str(namespace / _TOOLCHAIN / _BIN) + _SYSTEM_PATH,
        _ENV_LANG: _LANGUAGE,
        _ENV_LOCALE: _LANGUAGE,
    }
    frame = json.dumps(environment).encode(_UTF8) + _NEWLINE
    observations: list[ProcessFacts] = []
    seen: set[tuple[int, int | None, str | None]] = set()
    with tempfile.NamedTemporaryFile(prefix=_TRACE_PREFIX, dir=controller / _PRIVATE) as trace:
        command = [
            str(_STRACE),
            *_TRACE_FLAGS,
            trace.name,
            _SUDO,
            _NONINTERACTIVE,
            _USER_OPTION,
            _ROLE,
            _SEPARATOR,
            _PYTHON,
            str(controller / _LAUNCHER),
            str(namespace / _TOOLCHAIN / _CODEX),
            *SANDBOX_ARGUMENTS,
        ]
        # Privileged strace supervises only its own child; sudo preserves the ordinary isolated UID boundary.
        process = subprocess.Popen(
            command,
            cwd=namespace / _EVIDENCE,
            env=_ROOT_ENVIRONMENT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Remain in the root supervisor's owned group so the caller can close the entire trace.
            start_new_session=False,
        )
        if process.stdin is None:
            raise ValueError(_INVALID)
        process.stdin.write(frame)
        process.stdin.close()
        process.stdin = None
        started = time.monotonic()
        timed_out = False
        try:
            while process.poll() is None:
                if time.monotonic() - started > _TIMEOUT or Path(trace.name).stat().st_size > _MAX_TRACE:
                    timed_out = True
                    os.kill(process.pid, signal.SIGKILL)
                    break
                for pid in _descendants(process.pid):
                    if len(observations) >= _MAX_OBSERVATIONS:
                        break
                    try:
                        facts = process_facts(pid, namespace / _TOOLCHAIN)
                        key = (pid, facts.user_namespace, facts.executable.sha256 if facts.executable else None)
                        if key not in seen:
                            seen.add(key)
                            observations.append(facts)
                    except (OSError, ValueError):
                        continue
                time.sleep(_POLL_INTERVAL)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                os.kill(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
        outcomes = _trace_outcomes(_bounded_read(Path(trace.name), _MAX_TRACE))
    return TraceFacts(
        process.returncode, timed_out, _hash(stdout), _hash(stderr), _hash(_STRACE.read_bytes()), observations, outcomes
    )


_BIN = "bin"
_NONINTERACTIVE = "-n"
_USER_OPTION = "-u"
_SEPARATOR = "--"


def main() -> int:
    """Print only owned typed metadata; exceptions retain no messages or tracebacks."""
    try:
        if sys.argv[1:] == [SNAPSHOT_OPTION]:
            value: ProcessFacts | TraceFacts = process_facts(os.getpid())
        elif sys.argv[1:] == [TRACE_OPTION] and os.geteuid() == 0:
            value = trace_probe()
        else:
            raise ValueError(_INVALID)
        print(json.dumps(asdict(value)))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {_EXCEPTION_KEY: type(error).__name__, _ERRNO_KEY: error.errno if isinstance(error, OSError) else None}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
