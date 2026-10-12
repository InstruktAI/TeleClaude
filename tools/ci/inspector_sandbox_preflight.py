"""Install vendor-supported Ubuntu prerequisites and check native startup without credentials."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tools.ci.gha import append_output, required_env
from tools.ci.inspector_native_access import NativeAccessOperation, native_probe_program
from tools.release.attempt import ProviderAttempt, ProviderFailure, ProviderName, ProviderOutcome
from tools.release.codex_auth import CODEX_AUTH_FILENAME
from tools.release.evidence_contract import EVIDENCE_INDEX_FILENAME
from tools.release.inspector_bootstrap import (
    BOOTSTRAP_RECEIPT_FILENAME,
    InspectorBootstrap,
    load_bootstrap,
    verify_provider_paths,
)
from tools.release.isolated_inspection import (
    InspectorRole,
    principal_layout_paths,
    run_isolated_process,
    validate_principal_file_absent,
)

_DESCRIPTION = "Check the pinned native Codex sandbox before authentication."
_OUTPUT_OPTION = "--output-directory"
_ATTEMPT_OPTION = "--attempt-output"
_RUNNER_TEMP = "RUNNER_TEMP"
_UTF8 = "utf-8"
_DIAGNOSTIC = "codex-sandbox-readiness.json"
_ATTEMPT = "codex-attempt.json"
_READY_OUTPUT = "codex_sandbox_ready"
_TRUE = "true"
_FALSE = "false"
_HOME = "HOME"
_PATH = "PATH"
_TMPDIR = "TMPDIR"
_LANG = "LANG"
_LC_ALL = "LC_ALL"
_CONFIG = "CODEX_HOME"
_LANGUAGE = "C.UTF-8"
_SUDO = "/usr/bin/sudo"
_SUDO_FLAGS = ("-n", "--")
_APT = "/usr/bin/apt-get"
_INSTALL = "/usr/bin/install"
_PARSER = "/usr/sbin/apparmor_parser"
_BWRAP = Path("/usr/bin/bwrap")
_PROFILE_SOURCE = Path("/usr/share/apparmor/extra-profiles/bwrap-userns-restrict")
_PROFILE_TARGET = Path("/etc/apparmor.d/bwrap-userns-restrict")


class SandboxOperation(StrEnum):
    """Fixed public setup operations, without native arguments or output bodies."""

    REFRESH_PACKAGES = "refresh_packages"
    INSTALL_PACKAGES = "install_packages"
    INSTALL_PROFILE = "install_scoped_profile"
    LOAD_PROFILE = "load_scoped_profile"
    VERIFY_HELPER = "verify_helper_features"
    STARTUP = "native_sandbox_initialization"
    READ_EVIDENCE = "read_evidence"
    DENY_CONTROLLER = "deny_controller_read"
    DENY_AUTH = "deny_auth_path_read"
    DENY_WRITE = "deny_source_write"


class SandboxSetupError(RuntimeError):
    """A prerequisite failed with only its fixed operation and native status."""

    def __init__(self, operation: SandboxOperation, native_status: int | None) -> None:
        super().__init__(_SETUP_FAILED)
        self.operation = operation
        self.native_status = native_status


_SETUP_ARGUMENTS = {
    SandboxOperation.REFRESH_PACKAGES: (_APT, "update", "-qq"),
    SandboxOperation.INSTALL_PACKAGES: (
        _APT,
        "install",
        "-y",
        "-qq",
        "bubblewrap",
        "apparmor-profiles",
        "apparmor-utils",
    ),
    SandboxOperation.INSTALL_PROFILE: (_INSTALL, "-m", "0644", str(_PROFILE_SOURCE), str(_PROFILE_TARGET)),
    SandboxOperation.LOAD_PROFILE: (_PARSER, "-r", str(_PROFILE_TARGET)),
}
_HELP_ARGUMENT = "--help"
_REQUIRED_HELP = (b"--as-pid-1", b"--perms")
_SANDBOX_ARGUMENTS = (
    "sandbox",
    "--profile",
    "release-inspector",
    "--permission-profile",
    "release-inspector",
    "--include-managed-config",
    "--",
    "/bin/true",
)
_SETUP_TIMEOUT = 300
_PROBE_TIMEOUT = 60
_SETUP_FAILED = "The supported native sandbox prerequisites are unavailable."
_OPERATION = "native_sandbox_initialization"


def prepare_ubuntu_sandbox() -> None:
    """Use the distro helper and scoped profile without changing global security controls."""
    for operation, arguments in _SETUP_ARGUMENTS.items():
        try:
            result = subprocess.run(
                (_SUDO, *_SUDO_FLAGS, *arguments), capture_output=True, check=False, timeout=_SETUP_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            raise SandboxSetupError(operation, None) from None
        if result.returncode:
            raise SandboxSetupError(operation, result.returncode)
    result = subprocess.run((str(_BWRAP), _HELP_ARGUMENT), capture_output=True, check=False, timeout=_PROBE_TIMEOUT)
    if result.returncode or any(option not in result.stdout for option in _REQUIRED_HELP):
        raise SandboxSetupError(SandboxOperation.VERIFY_HELPER, result.returncode)


_PRIVATE_MARKER = "readiness-private-marker"
_WRITE_MARKER = ".release-readiness-write-marker"
_MARKER_CONTENT = b"synthetic release readiness marker\n"
_PROBE_PYTHON = "/usr/bin/python3"
_PROBE_CODE_OPTION = "-c"


_PROBE_READ = NativeAccessOperation.READ
_PROBE_WRITE = NativeAccessOperation.WRITE
_READ_REFUSAL_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.ENOENT})
_WRITE_REFUSAL_ERRNOS = _READ_REFUSAL_ERRNOS | {errno.EROFS}
_PROBES_KEY = "confinement"
_EXCLUSIVE_BINARY_MODE = "xb"


class NativeAccessObservation(BaseModel):
    """Completed fixed access operation: only errno or content hash, never payload bytes."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation: NativeAccessOperation
    errno: int | None
    sha256: str | None


class ConfinementObservation(BaseModel):
    """One fixed credential-free boundary check; output bodies remain unretained."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation: SandboxOperation
    native_status: int
    passed: bool
    stdout_sha256: str
    stderr_sha256: str


def check_confinement(bootstrap: InspectorBootstrap, environment: dict[str, str]) -> list[ConfinementObservation]:
    """Check only fixed evidence/private paths under the already selected native policy."""
    evidence_file = bootstrap.evidence / EVIDENCE_INDEX_FILENAME
    controller_marker = bootstrap.controller / _PRIVATE_MARKER
    auth_marker = bootstrap.config(InspectorRole.CODEX) / _PRIVATE_MARKER
    write_marker = bootstrap.evidence / _WRITE_MARKER
    observations: list[ConfinementObservation] = []
    if write_marker.exists() or write_marker.is_symlink():
        raise ValueError(_SETUP_FAILED)
    markers: list[Path] = []
    try:
        for path in (controller_marker, auth_marker):
            with path.open(_EXCLUSIVE_BINARY_MODE) as output:
                output.write(_MARKER_CONTENT)
            path.chmod(0o600)
            markers.append(path)
        commands = (
            (
                SandboxOperation.READ_EVIDENCE,
                _PROBE_READ,
                evidence_file,
                hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
            ),
            (SandboxOperation.DENY_CONTROLLER, _PROBE_READ, controller_marker, None),
            (SandboxOperation.DENY_AUTH, _PROBE_READ, auth_marker, None),
            (SandboxOperation.DENY_WRITE, _PROBE_WRITE, write_marker, None),
        )
        for operation, access, path, expected in commands:
            result = run_isolated_process(
                InspectorRole.CODEX,
                bootstrap.executable(InspectorRole.CODEX),
                (
                    *_SANDBOX_ARGUMENTS[:-1],
                    _PROBE_PYTHON,
                    _PROBE_CODE_OPTION,
                    native_probe_program(),
                    access,
                    str(path),
                ),
                bootstrap.evidence,
                environment,
                controller_directory=bootstrap.controller,
                timeout_seconds=_PROBE_TIMEOUT,
            )
            passed = False
            if not result.timed_out and result.return_code == 0:
                try:
                    observation = NativeAccessObservation.model_validate_json(result.stdout)
                except ValueError:
                    observation = None
                if observation is not None and observation.operation == access:
                    if expected is not None:
                        passed = observation.errno is None and observation.sha256 == expected
                    else:
                        refusals = _WRITE_REFUSAL_ERRNOS if access == _PROBE_WRITE else _READ_REFUSAL_ERRNOS
                        passed = observation.errno in refusals and observation.sha256 is None
            if operation is SandboxOperation.DENY_WRITE:
                passed = passed and not write_marker.exists() and not write_marker.is_symlink()
            observations.append(
                ConfinementObservation(
                    operation=operation,
                    native_status=result.return_code,
                    passed=passed,
                    stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
                    stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),
                )
            )
            if not passed:
                break
    finally:
        for path in markers:
            path.unlink()
        if write_marker.exists() or write_marker.is_symlink():
            write_marker.unlink()
    return observations


def main(argv: list[str] | None = None) -> int:
    """Run exactly one no-op native check and retain only bounded ordinary failure metadata."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(_OUTPUT_OPTION, type=Path, required=True)
    parser.add_argument(_ATTEMPT_OPTION, type=Path, required=True)
    args = parser.parse_args(argv)
    args.output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    status: int | None = None
    stdout_hash: str | None = None
    stderr_hash: str | None = None
    exception: str | None = None
    native_errno: int | None = None
    operation = SandboxOperation.STARTUP
    confinement: list[ConfinementObservation] = []
    try:
        prepare_ubuntu_sandbox()
        bootstrap = load_bootstrap(Path(required_env(_RUNNER_TEMP)).resolve() / BOOTSTRAP_RECEIPT_FILENAME)
        verify_provider_paths(bootstrap, InspectorRole.CODEX)
        validate_principal_file_absent(
            InspectorRole.CODEX, bootstrap.controller, bootstrap.config(InspectorRole.CODEX) / CODEX_AUTH_FILENAME
        )
        home, temporary, _ = principal_layout_paths(InspectorRole.CODEX, bootstrap.controller)
        environment = {
            _HOME: str(home),
            _PATH: bootstrap.runtime_path,
            _TMPDIR: str(temporary),
            _LANG: _LANGUAGE,
            _LC_ALL: _LANGUAGE,
            _CONFIG: str(bootstrap.config(InspectorRole.CODEX)),
        }
        result = run_isolated_process(
            InspectorRole.CODEX,
            bootstrap.executable(InspectorRole.CODEX),
            _SANDBOX_ARGUMENTS,
            bootstrap.evidence,
            environment,
            controller_directory=bootstrap.controller,
            timeout_seconds=_PROBE_TIMEOUT,
        )
        status = result.return_code
        stdout_hash = hashlib.sha256(result.stdout).hexdigest()
        stderr_hash = hashlib.sha256(result.stderr).hexdigest()
        if status == 0:
            confinement = check_confinement(bootstrap, environment)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        exception = type(error).__name__
        native_errno = error.errno if isinstance(error, OSError) else None
        if isinstance(error, SandboxSetupError):
            operation = error.operation
            status = error.native_status
    diagnostic = args.output_directory / _DIAGNOSTIC
    diagnostic.write_text(
        json.dumps(
            {
                _OPERATION_KEY: operation,
                _NATIVE_STATUS_KEY: status,
                _STDOUT_HASH_KEY: stdout_hash,
                _STDERR_HASH_KEY: stderr_hash,
                _EXCEPTION_KEY: exception,
                _ERRNO_KEY: native_errno,
                _PROBES_KEY: [item.model_dump(mode=_JSON_MODE) for item in confinement],
            }
        ),
        encoding=_UTF8,
    )
    diagnostic.chmod(0o600)
    ready = status == 0 and exception is None and len(confinement) == 4 and all(item.passed for item in confinement)
    if not ready:
        args.attempt_output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(diagnostic, args.attempt_output.parent / _DIAGNOSTIC)
        (args.attempt_output.parent / _DIAGNOSTIC).chmod(0o600)
        attempt = ProviderAttempt(
            provider=ProviderName.CODEX,
            outcome=ProviderOutcome.FAILED,
            failure=ProviderFailure.EXECUTION,
            report_sha256=None,
            auth_settled=False,
            exit_code=None,
            diagnostic_path=_DIAGNOSTIC,
        )
        args.attempt_output.write_text(attempt.model_dump_json(), encoding=_UTF8)
        args.attempt_output.chmod(0o600)
    append_output(_READY_OUTPUT, _TRUE if ready else _FALSE)
    return 0 if ready else 1


_JSON_MODE = "json"
_OPERATION_KEY = "operation"
_NATIVE_STATUS_KEY = "native_status"
_STDOUT_HASH_KEY = "stdout_sha256"
_STDERR_HASH_KEY = "stderr_sha256"
_EXCEPTION_KEY = "exception_type"
_ERRNO_KEY = "errno"

if __name__ == "__main__":
    raise SystemExit(main())
