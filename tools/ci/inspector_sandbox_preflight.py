"""Exercise native Codex sandbox initialization before any credential restoration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter

from tools.ci.gha import append_output, required_env
from tools.release.attempt import ProviderAttempt, ProviderFailure, ProviderName, ProviderOutcome
from tools.release.codex_auth import CODEX_AUTH_FILENAME
from tools.release.inspector_bootstrap import (
    BOOTSTRAP_RECEIPT_FILENAME,
    InspectorBootstrap,
    load_bootstrap,
    verify_provider_paths,
)
from tools.release.inspector_sandbox import SANDBOX_ARGUMENTS, SNAPSHOT_OPTION, TRACE_OPTION, ProcessFacts, TraceFacts
from tools.release.isolated_inspection import (
    InspectorBoundaryError,
    InspectorRole,
    InspectorSetupError,
    inspector_python,
    inspector_sandbox_helper,
    principal_layout_paths,
    run_isolated_process,
    settle_inspector_principal,
    validate_principal_file_absent,
)

_DESCRIPTION = "Check native sandbox initialization without authentication or inference."
_OUTPUT_OPTION = "--output-directory"
_RUNNER_TEMP = "RUNNER_TEMP"
_HOME = "HOME"
_PATH = "PATH"
_TMPDIR = "TMPDIR"
_CONFIG = "CODEX_HOME"
_LANG = "LANG"
_LC_ALL = "LC_ALL"
_LANGUAGE = "C.UTF-8"
_UTF8 = "utf-8"
_SHA256 = "sha256:"
_TRUE = "true"
_FALSE = "false"
_READY_OUTPUT = "codex_sandbox_ready"
_CLOSED_OUTPUT = "codex_boundary_closed"
_DIAGNOSTIC = "codex-sandbox-preflight.json"
_ATTEMPT = "codex-attempt.json"
_SUDO = "/usr/bin/sudo"
_ROOT_FLAGS = ("-n", "--")
_SOURCE = Path(__file__).resolve().parents[1] / "release" / "inspector_sandbox.py"
_ROOT_ENVIRONMENT = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/"}
_EMPTY = b""
_TIMEOUT = 60
_MAX_METADATA = 1024 * 1024
_METADATA_FAILED = "Sandbox metadata is unavailable or invalid."
_UID_GAP = "provider_uid_metadata_unavailable"
_POLICY_GAP = "effective_native_policy_not_observed"
_HELPER_GAP = "selected_helper_identity_or_version_not_observed"
_OWNER_GAP = "namespace_owner_uid_not_collected"
_PLATFORM_GAP = "platform_metadata_incomplete"
_PROBE_FAILURE = "native_sandbox_initialization"
_LSM_PATH = Path("/sys/kernel/security/lsm")
_LSMS = frozenset(
    {"capability", "landlock", "lockdown", "yama", "apparmor", "bpf", "selinux", "smack", "tomoyo", "integrity"}
)
_SYSCTLS = {
    "apparmor_restrict_unprivileged_userns": Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns"),
    "unprivileged_userns_clone": Path("/proc/sys/kernel/unprivileged_userns_clone"),
    "max_user_namespaces": Path("/proc/sys/user/max_user_namespaces"),
}
_SAFE_VERSION = re.compile(r"[A-Za-z0-9_.+\-]{1,128}")
_COMMA = ","
_IMAGE_OS = "ImageOS"
_IMAGE_VERSION = "ImageVersion"
_RUNNER_IMAGES = frozenset({"ubuntu20", "ubuntu22", "ubuntu24"})
_RUNNER_VERSION = re.compile(r"[0-9]{8}\.[0-9]{1,4}\.[0-9]{1,4}")
_REQUEST_NAMESPACE = "namespace"
_REQUEST_UID = "owner_uid"
_REQUEST_DEVICE = "device"
_REQUEST_INODE = "inode"
_REQUEST_CLAIM = "claim"
_DIAGNOSTICS_DIRECTORY = "diagnostics"
_DIAGNOSTIC_REFERENCE = "diagnostics/codex-sandbox-preflight.json"
_KILL = "/bin/kill"
_KILL_SIGNAL = "-KILL"
_OPTION_END = "--"
_GROUP_PREFIX = "-"


class ProbeResult(BaseModel):
    """A local native command status is separate from provider assessment execution."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    native_status: int
    timed_out: bool
    stdout_sha256: str
    stderr_sha256: str


class SandboxDiagnostic(BaseModel):
    """Allowlisted platform facts and owned observations, with explicit unavailable evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    provider: ProviderName = ProviderName.CODEX
    operation: str = _PROBE_FAILURE
    pinned_version: str | None = None
    kernel_release: str | None = None
    architecture: str | None = None
    runner_image: str | None = None
    runner_image_version: str | None = None
    active_lsms: list[str] = []
    namespace_sysctls: dict[str, int] = {}
    provider_context: ProcessFacts | None = None
    control: ProbeResult | None = None
    trace: TraceFacts | None = None
    exception_type: str | None = None
    errno: int | None = None
    native_status: int | None = None
    gaps: list[str] = [_OWNER_GAP, _POLICY_GAP, _HELPER_GAP]


def _hash(content: bytes) -> str:
    """Keep native output bodies outside retained evidence."""
    return _SHA256 + hashlib.sha256(content).hexdigest()


def _safe_version(value: str) -> str | None:
    """Export only known version-shaped host metadata, never arbitrary environment values."""
    return value if _SAFE_VERSION.fullmatch(value) else None


def _platform() -> SandboxDiagnostic:
    """Read public kernel and fixed sysctl facts; inaccessible facts remain missing."""
    sysctls: dict[str, int] = {}
    lsms: list[str] = []
    gaps = [_OWNER_GAP, _POLICY_GAP, _HELPER_GAP]
    for key, path in _SYSCTLS.items():
        try:
            text = path.read_text(encoding=_UTF8).strip()
            if text.isdecimal() and len(text) <= 20:
                sysctls[key] = int(text)
        except OSError:
            gaps.append(_PLATFORM_GAP)
    try:
        lsms = [value for value in _LSM_PATH.read_text(encoding=_UTF8).strip().split(_COMMA) if value in _LSMS]
    except OSError:
        gaps.append(_PLATFORM_GAP)
    return SandboxDiagnostic(
        kernel_release=_safe_version(platform.release()),
        architecture=_safe_version(platform.machine()),
        runner_image=_runner_image(),
        runner_image_version=_runner_version(),
        active_lsms=lsms,
        namespace_sysctls=sysctls,
        gaps=sorted(set(gaps)),
    )


def _runner_image() -> str | None:
    """Recognize only fixed public runner image names, never arbitrary environment text."""
    value = os.environ.get(_IMAGE_OS)
    return value if value in _RUNNER_IMAGES else None


def _runner_version() -> str | None:
    """Recognize the public numeric runner build-version shape."""
    value = os.environ.get(_IMAGE_VERSION)
    return value if value is not None and _RUNNER_VERSION.fullmatch(value) else None


def _trace(bootstrap: InspectorBootstrap) -> TraceFacts:
    """Invoke the fixed root supervisor with owned locator metadata, never secrets or argv selectors."""
    request = {
        _REQUEST_NAMESPACE: str(bootstrap.namespace),
        _REQUEST_UID: bootstrap.owner_uid,
        _REQUEST_DEVICE: bootstrap.device,
        _REQUEST_INODE: bootstrap.inode,
        _REQUEST_CLAIM: bootstrap.claim,
    }
    # Root tracing must observe only its own native sandbox descendants, including executable FDs.
    process = subprocess.Popen(
        [_SUDO, *_ROOT_FLAGS, str(inspector_python()), str(_SOURCE), TRACE_OPTION],
        env=_ROOT_ENVIRONMENT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(json.dumps(request).encode(_UTF8), timeout=_TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        _close_trace_group(process.pid)
        process.communicate(timeout=10)
        raise
    finally:
        _close_trace_group(process.pid)
    if process.returncode != 0 or len(stdout) > _MAX_METADATA:
        raise InspectorSetupError(exception_type=RuntimeError.__name__, native_status=process.returncode)
    return TypeAdapter(TraceFacts).validate_json(stdout, strict=True)


def _close_trace_group(pid: int) -> None:
    """Close only the privileged group allocated by this caller, including tracer descendants."""
    # Privilege is required for root-owned tracing children; the group identity comes from our own Popen.
    result = subprocess.run(
        [_SUDO, *_ROOT_FLAGS, _KILL, _KILL_SIGNAL, _OPTION_END, _GROUP_PREFIX + str(pid)],
        env=_ROOT_ENVIRONMENT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise InspectorBoundaryError(_METADATA_FAILED)


def preflight(receipt: Path, output_directory: Path) -> bool:
    """Refuse native failure before auth use, while preserving fallback after UID settlement."""
    diagnostic = _platform()
    ready = False
    boundary_closed = True
    try:
        bootstrap = load_bootstrap(receipt)
        verify_provider_paths(bootstrap, InspectorRole.CODEX)
        validate_principal_file_absent(
            InspectorRole.CODEX, bootstrap.controller, bootstrap.config(InspectorRole.CODEX) / CODEX_AUTH_FILENAME
        )
        home, temporary, _ = principal_layout_paths(InspectorRole.CODEX, bootstrap.controller)
        environment = {
            _HOME: str(home),
            _PATH: bootstrap.runtime_path,
            _TMPDIR: str(temporary),
            _CONFIG: str(bootstrap.config(InspectorRole.CODEX)),
            _LANG: _LANGUAGE,
            _LC_ALL: _LANGUAGE,
        }
        diagnostic = diagnostic.model_copy(update={_PIN: bootstrap.versions[InspectorRole.CODEX]})
        context = run_isolated_process(
            InspectorRole.CODEX,
            inspector_python(),
            (str(inspector_sandbox_helper(bootstrap.controller)), SNAPSHOT_OPTION),
            bootstrap.evidence,
            environment,
            controller_directory=bootstrap.controller,
            timeout_seconds=_TIMEOUT,
        )
        if context.return_code == 0 and len(context.stdout) <= _MAX_METADATA:
            diagnostic = diagnostic.model_copy(
                update={_CONTEXT: TypeAdapter(ProcessFacts).validate_json(context.stdout, strict=True)}
            )
        else:
            diagnostic = diagnostic.model_copy(update={_GAPS: diagnostic.gaps + [_UID_GAP]})
        control = run_isolated_process(
            InspectorRole.CODEX,
            bootstrap.executable(InspectorRole.CODEX),
            SANDBOX_ARGUMENTS,
            bootstrap.evidence,
            environment,
            controller_directory=bootstrap.controller,
            timeout_seconds=_TIMEOUT,
        )
        diagnostic = diagnostic.model_copy(
            update={
                _CONTROL: ProbeResult(
                    native_status=control.return_code,
                    timed_out=control.timed_out,
                    stdout_sha256=_hash(control.stdout),
                    stderr_sha256=_hash(control.stderr),
                )
            }
        )
        ready = control.return_code == 0 and not control.timed_out
        if not ready:
            verify_provider_paths(bootstrap, InspectorRole.CODEX)
            validate_principal_file_absent(
                InspectorRole.CODEX, bootstrap.controller, bootstrap.config(InspectorRole.CODEX) / CODEX_AUTH_FILENAME
            )
            diagnostic = diagnostic.model_copy(update={_TRACE: _trace(bootstrap)})
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        if isinstance(error, InspectorBoundaryError):
            boundary_closed = False
        diagnostic = diagnostic.model_copy(
            update={
                _EXCEPTION: type(error).__name__,
                _ERRNO: error.errno if isinstance(error, OSError) else None,
                _STATUS: error.native_status if isinstance(error, InspectorSetupError) else None,
            }
        )
    finally:
        try:
            settle_inspector_principal(InspectorRole.CODEX)
        except (OSError, RuntimeError):
            ready = False
            boundary_closed = False
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    diagnostic_path = output_directory / _DIAGNOSTIC
    diagnostic_path.write_text(diagnostic.model_dump_json(indent=2), encoding=_UTF8)
    diagnostic_path.chmod(0o600)
    if not ready:
        attempt = ProviderAttempt(
            provider=ProviderName.CODEX,
            outcome=ProviderOutcome.FAILED,
            failure=ProviderFailure.EXECUTION,
            report_sha256=None,
            auth_settled=False,
            auth_settlement_failed=False,
            exit_code=None,
            diagnostic_path=_DIAGNOSTIC_REFERENCE,
        )
        (output_directory.parent / _CODEX_RESULT).mkdir(mode=0o700, exist_ok=False)
        failure_diagnostics = output_directory.parent / _CODEX_RESULT / _DIAGNOSTICS_DIRECTORY
        failure_diagnostics.mkdir(mode=0o700)
        failure_diagnostic = failure_diagnostics / _DIAGNOSTIC
        failure_diagnostic.write_text(diagnostic.model_dump_json(indent=2), encoding=_UTF8)
        failure_diagnostic.chmod(0o600)
        (output_directory.parent / _CODEX_RESULT / _ATTEMPT).write_text(
            attempt.model_dump_json(indent=2), encoding=_UTF8
        )
    append_output(_READY_OUTPUT, _TRUE if ready else _FALSE)
    append_output(_CLOSED_OUTPUT, _TRUE if boundary_closed else _FALSE)
    return ready


_PIN = "pinned_version"
_CONTEXT = "provider_context"
_GAPS = "gaps"
_CONTROL = "control"
_TRACE = "trace"
_EXCEPTION = "exception_type"
_ERRNO = "errno"
_STATUS = "native_status"
_CODEX_RESULT = "codex-result"


def main(argv: list[str] | None = None) -> int:
    """One Python Actions step exports readiness without accessing workflow credentials."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(_OUTPUT_OPTION, type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = Path(required_env(_RUNNER_TEMP)).resolve() / BOOTSTRAP_RECEIPT_FILENAME
    try:
        return 0 if preflight(receipt, args.output_directory) else 1
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(
            json.dumps({_EXCEPTION: type(error).__name__, _ERRNO: error.errno if isinstance(error, OSError) else None}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
