"""Shared result model and command-line entry point for runtime acceptance."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import json
import math
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import FrameType
from typing import cast

from tools.ci.terminal import PersistentTerminal, TerminalFailure

_UTF8 = "utf-8"
_REPORT_SCHEMA_VERSION = 1
_DEFAULT_ROOT = "."
_REPORT_TEMP_SUFFIX = ".tmp"
_LINE_BREAK = "\n"
_ENVIRONMENT_CACHE_DIRECTORY = "teleclaude-runtime-acceptance"
_ENVIRONMENT_LOCK_SUFFIX = ".lock"
_ENVIRONMENT_MANIFESTS = ("pyproject.toml", "uv.lock", ".python-version")
_ENVIRONMENT_REQUIRED_MANIFESTS = ("pyproject.toml", "uv.lock")
_ENVIRONMENT_GROUPS = "runtime-only"
_UV_EXECUTABLE = "uv"
_UV_SYNC_COMMAND = "sync"
_UV_PROJECT_OPTION = "--project"
_UV_LOCKED_OPTION = "--locked"
_UV_NO_INSTALL_PROJECT_OPTION = "--no-install-project"
_UV_NO_DEFAULT_GROUPS_OPTION = "--no-default-groups"
_ENVIRONMENT_VARIABLE = "UV_PROJECT_ENVIRONMENT"
_UV_NO_SYNC_VARIABLE = "UV_NO_SYNC"
_UV_CACHE_VARIABLE = "UV_CACHE_DIR"
_COLD_HOME_VARIABLE = "HOME"
_TELECLAUDE_HOME_VARIABLE = "TELECLAUDE_HOME"
_PYTHON_PATH_VARIABLE = "PYTHONPATH"
_NO_BYTECODE_VARIABLE = "PYTHONDONTWRITEBYTECODE"
_NO_USER_SITE_VARIABLE = "PYTHONNOUSERSITE"
_XDG_STATE_VARIABLE = "XDG_STATE_HOME"
_XDG_CACHE_VARIABLE = "XDG_CACHE_HOME"
_XDG_CONFIG_VARIABLE = "XDG_CONFIG_HOME"
_XDG_DATA_VARIABLE = "XDG_DATA_HOME"
_TMP_VARIABLE = "TMPDIR"
_GIT_CONFIG_GLOBAL_VARIABLE = "GIT_CONFIG_GLOBAL"
_GIT_CONFIG_SYSTEM_VARIABLE = "GIT_CONFIG_SYSTEM"
_GIT_CONFIG_SYSTEM_DISABLED_VARIABLE = "GIT_CONFIG_NOSYSTEM"
_LOCALE_VARIABLE = "LANG"
_PATH_VARIABLE = "PATH"
_NO_COLOR_VARIABLE = "NO_COLOR"
_CONFIG_FILENAME = "config.yml"
_OWNER_ESTABLISHMENT_MODULE = "teleclaude.entrypoints.macos_setup"
_CLI_EXECUTABLE = Path("bin") / "telec"
_CLI_HELP_ARGUMENTS = ("--help",)
_CLI_REPO_HELP_ARGUMENTS = ("repo", "--help")
_CLI_VERSION_ARGUMENTS = ("version",)
_PACKAGE_IMPORT_ISOLATED_OPTION = "-P"
_PACKAGE_IMPORT_SCRIPT = Path("tools") / "ci" / "import_package_modules.py"
_MODULE_HELP_ARGUMENTS = ("-P", "-m", _OWNER_ESTABLISHMENT_MODULE, "--help")
_UV_SYNC_TIMEOUT_SECONDS = 900
_COMMAND_TIMEOUT_SECONDS = 30
_PACKAGE_IMPORT_TIMEOUT_SECONDS = 45
_PROCESS_TERMINATION_GRACE_SECONDS = 1
_SYNTHETIC_COMPUTER_NAME = "runtime-acceptance"
_SYNTHETIC_COMPUTER_USER = "runtime-acceptance"
_SYNTHETIC_COMPUTER_HOST = "runtime-acceptance.invalid"
_SYNTHETIC_AGENT = "claude"
_SYNTHETIC_RELEASE_CHANNEL = "alpha"
_PYTHON_EXECUTABLE = "python"
_UTF8_REPLACEMENT = "replace"
_ENVIRONMENT_INVALID = "The dependency-only environment generation is incomplete: {path}"
_ENVIRONMENT_SYNC_FAILED = "Could not prepare the locked dependency-only environment: {detail}"
_ENVIRONMENT_INPUT_MISSING = "The dependency environment input is missing: {path}"
_PROCESS_LAUNCH_FAILED = "The required process could not be started."
_SCENARIO_COLD = "UC-RA1"
_SCENARIO_RUNTIME_READY = "UC-RA2"
_SCENARIO_OWNER_IDENTITY = "UC-RA3"
_SCENARIO_CONFIG_PATCH = "UC-RA4"
_SCENARIO_RESTART_PERSISTENCE = "UC-RA7"
_SCENARIO_CLEANUP = "UC-RA9"
_SCENARIO_CANDIDATE_IDENTITY = "UC-RA10"
_COLD_PROFILE_SCENARIOS = (_SCENARIO_COLD,)
_FULL_PROFILE_SCENARIOS = (
    _SCENARIO_COLD,
    _SCENARIO_RUNTIME_READY,
    _SCENARIO_OWNER_IDENTITY,
    _SCENARIO_CONFIG_PATCH,
    _SCENARIO_RESTART_PERSISTENCE,
    _SCENARIO_CLEANUP,
    _SCENARIO_CANDIDATE_IDENTITY,
)
_PROFILE_COLD = "cold"
_PROFILE_FULL = "full"
_UNKNOWN_REVISION = "unknown"
_EMPTY = ""
_DIAGNOSTIC_LIMIT = 4096
_INSTALLER_LOG_PATH = Path("install.log")
_INSTALLER_LOG_LABEL = "Installer log (end): "
_INSTALLER_LOG_UNAVAILABLE = "Installer log unavailable ({error_class})."
_INSTALLER_LOG_TRUNCATION_MARKER = "[earlier installer log content omitted]\n"
_DIAGNOSTIC_SEPARATOR = "\n"
_BINARY_READ_MODE = "rb"
_PROFILE_OPTION = "--profile"
_REPORT_OPTION = "--report"
_ROOT_OPTION = "--root"
_SOURCE_REVISION_OPTION = "--source-revision"
_SOURCE_TREE_OPTION = "--source-tree"
_CLI_DESCRIPTION = "Run the bounded real-process CLI acceptance profile."
_REPORT_WRITE_ERROR = "Could not write runtime acceptance report: {error}"
_SCENARIO_NOT_RUN = "No scenario action was registered."
_INTERRUPTED = "The profile was interrupted."
_SYNTHETIC_HOME_DIRECTORY = "home"
_SYNTHETIC_STATE_DIRECTORY = "state"
_SYNTHETIC_CACHE_DIRECTORY = "cache"
_SYNTHETIC_CONFIG_DIRECTORY = "config"
_SYNTHETIC_DATA_DIRECTORY = "data"
_SYNTHETIC_TEMP_DIRECTORY = "tmp"
_ENVIRONMENT_MANIFEST_FILENAME = "environment.json"
_OUTPUT_LIMIT = 65536
_PROCESS_SUCCESS = 0
_PROCESS_FAILURE = 1
_PROCESS_LAUNCH_EXIT_CODE = 127
_REPORT_NAME_TEMPLATE = "runtime-acceptance-{identifier}.json"
_VENV_CONFIG_FILENAME = "pyvenv.cfg"
_PATH_SEPARATOR = os.pathsep
_SCENARIO_PUBLIC_RESULT = "The public command did not return a non-empty successful result."
_SOURCE_TREE_PLACEHOLDER = "<source-tree>"
_DEPENDENCY_ENVIRONMENT_PLACEHOLDER = "<dependency-environment>"
_SYNTHETIC_RUNTIME_PLACEHOLDER = "<synthetic-runtime>"
_RUNTIME_HOME_PLACEHOLDER = "<runtime-home>"
_ADMIN_ROLE = "admin"
_WHOAMI_EMAIL_FIELD = "Email"
_WHOAMI_ROLE_FIELD = "Role"
_WHOAMI_LABEL_SEPARATOR = ": "
_ROLE_SECTION = "roles"
_ROLE_PLATFORM_FIELD = "platform"
_COMPUTER_IS_LOCAL_FIELD = "is_local"
_COMPUTER_NAME_FIELD = "name"
_COMPUTER_STATUS_FIELD = "status"
_READY_LOCAL_COMPUTER_SNAPSHOT = Path("snapshots") / "ready-local-computer.json"
_EXPECTED_COMMAND_ERROR = "A required public command failed or exceeded its bound."
_EXPECTED_VALID_PATCH_ERROR = "A valid public configuration patch did not persist its typed value."
_EXPECTED_REVISION_CHANGE_ERROR = "A committed configuration patch did not advance its revision."
_EXPECTED_PERSON_IDENTITY_ERROR = "The owner person record lacks platform administrator standing."
_EXPECTED_OWNER_WHOAMI_ERROR = "The fresh CLI process did not report the seeded administrator identity."
_EXPECTED_COMPUTER_LIST_ERROR = "The daemon did not return a ready local computer."
_EXPECTED_READINESS_ERROR = "The supported lifecycle did not report a ready daemon in time."
_FULL_INSTALL_ERROR = "The supported installer failed in the disposable runtime."
_FULL_SERVICE_STOP_ERROR = "The supported lifecycle could not stop the disposable runtime."
_FULL_TEMP_CLEANUP_ERROR = "The disposable runtime temporary resources could not be removed."
_FULL_TERMINAL_SETUP_ERROR = "The owned PTY could not enter the checked source directory."
_CLEANUP_FAILURE_SEPARATOR = ", "
_SYNTHETIC_PATH_ENVIRONMENT_VARIABLES = (
    _COLD_HOME_VARIABLE,
    _TELECLAUDE_HOME_VARIABLE,
    _XDG_STATE_VARIABLE,
    _XDG_CACHE_VARIABLE,
    _XDG_CONFIG_VARIABLE,
    _XDG_DATA_VARIABLE,
    _TMP_VARIABLE,
)
_DEFAULT_LANGUAGE = "C.UTF-8"
_UV_NO_SYNC_VALUE = "1"
_PROCESS_FAILURE_DETAIL = "The command failed with exit status {exit_status}."
_PROCESS_TIMEOUT_DETAIL = "The command exceeded its deadline."
_PROCESS_OUTPUT_LIMIT_DETAIL = "The command exceeded the output limit."
_BASH_EXECUTABLE = "/bin/bash"
_BASH_NO_PROFILE_OPTION = "--noprofile"
_BASH_NO_RC_OPTION = "--norc"
_BASH_INTERACTIVE_OPTION = "-i"
_PROMPT_VARIABLE = "PS1"
_CONTINUATION_PROMPT_VARIABLE = "PS2"
_FULL_COMMAND_TIMEOUT_SECONDS = 60
_INSTALL_COMMAND_TIMEOUT_SECONDS = 3600
_INSTALLER_OUTPUT_LIMIT_BYTES = 262144
_INSTALLER_LOG_TAIL_LIMIT = _DIAGNOSTIC_LIMIT // 4
_INSTALLER_STDOUT_TAIL_LIMIT = _DIAGNOSTIC_LIMIT // 4
_INSTALLER_STDERR_TAIL_LIMIT = _DIAGNOSTIC_LIMIT // 4
_INSTALLER_STDOUT_TAIL_LABEL = "Installer stdout (end): "
_INSTALLER_STDERR_TAIL_LABEL = "Installer stderr (end): "
_START_COMMAND_TIMEOUT_SECONDS = 300
_RESTART_COMMAND_TIMEOUT_SECONDS = 300
_STOP_COMMAND_TIMEOUT_SECONDS = 120
_READINESS_WINDOW_SECONDS = 90
_READINESS_POLL_INTERVAL_SECONDS = 1
_HEALTH_OBSERVATION_TIMEOUT_SECONDS = 5
_HEALTH_SOCKET_PATH = "/tmp/teleclaude-api.sock"
_HEALTH_HTTP_REQUEST = b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
_HEALTH_RESPONSE_LIMIT_BYTES = 16384
_HEALTH_PREPARATION_FIELD = "preparation"
_HEALTH_PID_FIELD = "pid"
_HEALTH_TOKEN_FIELD = "token"
_HEALTH_INSTANCE_INVALID = "The public health response lacks a valid daemon instance."
_HEALTH_INSTANCE_UNCHANGED = "The configuration change did not produce a ready replacement daemon in time."
_OWNER_SEED_NAME = "runtime-acceptance-owner"
_OWNER_SEED_EMAIL = "runtime-acceptance-owner@probe.invalid"
_OWNER_SEED_SLUG = "runtime-acceptance-owner"
_REVISION_OPTION = "--revision"
_YAML_OPTION = "--yaml"
_FORMAT_OPTION = "--format"
_JSON_FORMAT = "json"
_SHELL_CHANGE_DIRECTORY = "cd"
_TIMEZONE_UTC = "UTC"
_TIMEZONE_EUROPE_AMSTERDAM = "Europe/Amsterdam"
_FALSE_EXECUTABLE = "/usr/bin/false"
_SLEEP_EXECUTABLE = "/bin/sleep"
_TIMEOUT_PROBE_DURATION = "2"
_TIMEOUT_PROBE_SECONDS = 0.1
_FULL_HOME_REQUIRED = "The full profile requires the disposable VM's normal home directory."
_FULL_CONFIG_RESTORE_ERROR = "The public config surface could not restore disabled external adapters."
_FULL_TERMINAL_CLEANUP_ERROR = "An owned terminal session did not close cleanly."
_FULL_FAILURE_PROBE_FAILED = "A required failing or timed-out child process was not reported as failed."
_FULL_CANDIDATE_IDENTITY_INVALID = "The full profile lacks an exact source and tree identity."
_FULL_REPORT_INVALID = "The full runtime acceptance report is incomplete or does not match its candidate."
_MACHINE_REVISION_FIELD = "revision"
_MACHINE_TIMEZONE_FIELD = "timezone"
_MACHINE_ADAPTER_SECTIONS = ("telegram", "discord", "whatsapp", "email", "tts", "stt")
_MACHINE_ADAPTER_ENABLED_FIELD = "enabled"
_FULL_CLEANUP_FAILURE = "The disposable runtime did not settle its owned resources: {failures}"
_SERVICE_STATUS_COMMAND = ("make", "status")
_SERVICE_START_COMMAND = ("make", "start")
_SERVICE_STOP_COMMAND = ("make", "stop")
_SERVICE_RESTART_COMMAND = ("make", "restart")
_INSTALLER_COMMAND = ("bin/install.sh", "--yes")
_COMPUTERS_LIST_COMMAND = ("bin/telec", "computers", "list")
_CONFIG_COMPUTER_GET_COMMAND = ("bin/telec", "config", "computer", "get", "--format", "json")
_CONFIG_COMPUTER_PATCH_PREFIX = ("bin/telec", "config", "computer", "patch")
_CONFIG_PERSON_GET_PREFIX = ("bin/telec", "config", "person", "get")
_AUTH_LOGIN_PREFIX = ("bin/telec", "auth", "login")
_AUTH_WHOAMI_COMMAND = ("bin/telec", "auth", "whoami")
_AUTH_LOGOUT_COMMAND = ("bin/telec", "auth", "logout")
_ENV_OWNER_NAME_VARIABLE = "TELECLAUDE_OWNER_NAME"
_ENV_OWNER_EMAIL_VARIABLE = "TELECLAUDE_OWNER_EMAIL"
_CI_VARIABLE = "CI"
_USER_VARIABLE = "USER"
_LOGNAME_VARIABLE = "LOGNAME"
_SHELL_VARIABLE = "SHELL"
_XDG_RUNTIME_VARIABLE = "XDG_RUNTIME_DIR"
_DBUS_SESSION_VARIABLE = "DBUS_SESSION_BUS_ADDRESS"
_JSON_OBJECT_START = "{"
_JSON_ARRAY_START = "["
_FULL_NO_OUTPUT_ERROR = "A required public command returned no result."
_FULL_STATE_CHANGED = "A refused operation changed the persisted machine configuration."
_FULL_BAD_REVISION = "A public configuration read did not return its opaque revision."
_FULL_CONFIG_SHAPE_INVALID = "A public configuration read returned an invalid structure."
_JSON_SEPARATORS = (",", ":")
_MANIFEST_KEY_FIELD = "key"
_MANIFEST_GROUPS_FIELD = "groups"
_CONFIG_COMPUTER_FIELD = "computer"
_CONFIG_AGENTS_FIELD = "agents"
_CONFIG_DEFAULT_FIELD = "default"
_CONFIG_DEPLOYMENT_FIELD = "deployment"
_CONFIG_CHANNEL_FIELD = "channel"
_COMPUTER_USER_FIELD = "user"
_COMPUTER_ROLE_FIELD = "role"
_COMPUTER_TIMEZONE_FIELD = "timezone"
_COMPUTER_WORKING_DIRECTORY_FIELD = "default_working_dir"
_COMPUTER_MASTER_FIELD = "is_master"
_COMPUTER_HOST_FIELD = "host"
_RUNNER_IDENTITY_FIELDS = frozenset({_COMPUTER_NAME_FIELD, _COMPUTER_USER_FIELD, _COMPUTER_HOST_FIELD})
_REDACTED_RUNNER_IDENTITY = "<runner-identity>"
_COMPUTER_INGRESS_FIELD = "is_ingress_node"
_AGENT_ENABLED_FIELD = "enabled"
_COMPUTER_ROLE_DEFAULT = "general"
_TRUE_TEXT = "1"
_UV_SYNC_ARGUMENTS = (
    _UV_EXECUTABLE,
    _UV_SYNC_COMMAND,
    _UV_PROJECT_OPTION,
)
_PYTHON_ENVIRONMENT_EXECUTABLE = Path("bin") / _PYTHON_EXECUTABLE


class Profile(StrEnum):
    """Supported acceptance profile selection."""

    COLD = _PROFILE_COLD
    FULL = _PROFILE_FULL


class ScenarioStatus(StrEnum):
    """Terminal outcome for one required scenario."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome and bounded evidence for one required scenario."""

    scenario_id: str
    status: ScenarioStatus
    duration_seconds: float
    commands: tuple[CommandEvidence, ...] = ()
    diagnostics: str = _EMPTY


@dataclass(frozen=True)
class CommandEvidence:
    """Bounded process evidence for one public command invoked by a scenario."""

    argv: tuple[str, ...]
    exit_status: int | None
    duration_seconds: float
    stdout: str = _EMPTY
    stderr: str = _EMPTY
    diagnostics: str = _EMPTY


@dataclass(frozen=True)
class DaemonInstance:
    """Public process identity observed before and after a configuration restart."""

    pid: int
    token: str


@dataclass(frozen=True)
class WhoAmIFields:
    """Identity fields rendered by the public terminal whoami command."""

    email: str
    role: str


@dataclass(frozen=True)
class CleanupResult:
    """Cleanup outcome retained independently from the scenario outcome."""

    status: ScenarioStatus
    detail: str = _EMPTY
    commands: tuple[CommandEvidence, ...] = ()


@dataclass(frozen=True)
class AcceptanceReport:
    """Structured evidence identifying the source, profile, journeys and cleanup."""

    schema_version: int
    source_revision: str
    source_tree: str
    profile: Profile
    scenario_inventory: tuple[str, ...]
    scenarios: tuple[ScenarioResult, ...]
    cleanup: CleanupResult
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return (
            self.cleanup.status is ScenarioStatus.PASSED
            and len(self.scenarios) == len(self.scenario_inventory)
            and all(result.status is ScenarioStatus.PASSED for result in self.scenarios)
        )


ScenarioAction = Callable[[], ScenarioResult | None]
CleanupAction = Callable[[list[CommandEvidence]], None]


def _bound_command_evidence(evidence: Sequence[CommandEvidence]) -> tuple[CommandEvidence, ...]:
    """Copy command evidence with each diagnostic stream bounded for the report."""
    return tuple(
        CommandEvidence(
            argv=command.argv,
            exit_status=command.exit_status,
            duration_seconds=command.duration_seconds,
            stdout=command.stdout[:_DIAGNOSTIC_LIMIT],
            stderr=command.stderr[:_DIAGNOSTIC_LIMIT],
            diagnostics=command.diagnostics[:_DIAGNOSTIC_LIMIT],
        )
        for command in evidence
    )


def execute_profile(
    profile: Profile,
    *,
    source_revision: str,
    source_tree: str,
    scenario_inventory: Sequence[str],
    scenario_actions: Mapping[str, ScenarioAction],
    cleanup_action: CleanupAction,
) -> AcceptanceReport:
    """Run required scenarios in order and retain failures, omissions and cleanup."""
    started = time.monotonic()
    outcomes: list[ScenarioResult] = []
    cleanup = CleanupResult(status=ScenarioStatus.NOT_RUN)
    for scenario_id in scenario_inventory:
        action = scenario_actions.get(scenario_id)
        if action is None:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.NOT_RUN,
                    duration_seconds=0,
                    diagnostics=_SCENARIO_NOT_RUN,
                )
            )
            continue
        scenario_started = time.monotonic()
        try:
            result = action()
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=result.status if result is not None else ScenarioStatus.PASSED,
                    duration_seconds=time.monotonic() - scenario_started,
                    commands=_bound_command_evidence(result.commands) if result is not None else (),
                    diagnostics=result.diagnostics[:_DIAGNOSTIC_LIMIT] if result is not None else _EMPTY,
                )
            )
        except KeyboardInterrupt:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.FAILED,
                    duration_seconds=time.monotonic() - scenario_started,
                    diagnostics=_INTERRUPTED,
                )
            )
        except Exception as exc:
            outcomes.append(
                ScenarioResult(
                    scenario_id=scenario_id,
                    status=ScenarioStatus.FAILED,
                    duration_seconds=time.monotonic() - scenario_started,
                    diagnostics=f"{type(exc).__name__}: {exc}"[:_DIAGNOSTIC_LIMIT],
                )
            )
        if outcomes[-1].status is not ScenarioStatus.PASSED:
            for not_run_id in scenario_inventory[len(outcomes) :]:
                outcomes.append(
                    ScenarioResult(
                        scenario_id=not_run_id,
                        status=ScenarioStatus.NOT_RUN,
                        duration_seconds=0,
                        diagnostics=_SCENARIO_NOT_RUN,
                    )
                )
            break
    cleanup_evidence: list[CommandEvidence] = []
    try:
        cleanup_action(cleanup_evidence)
        cleanup = CleanupResult(status=ScenarioStatus.PASSED)
    except Exception as exc:
        cleanup = CleanupResult(
            status=ScenarioStatus.FAILED,
            detail=f"{type(exc).__name__}: {exc}"[:_DIAGNOSTIC_LIMIT],
            commands=_bound_command_evidence(cleanup_evidence),
        )
    except KeyboardInterrupt:
        cleanup = CleanupResult(
            status=ScenarioStatus.FAILED,
            detail=_INTERRUPTED,
            commands=_bound_command_evidence(cleanup_evidence),
        )
    return AcceptanceReport(
        schema_version=_REPORT_SCHEMA_VERSION,
        source_revision=source_revision,
        source_tree=source_tree,
        profile=profile,
        scenario_inventory=tuple(scenario_inventory),
        scenarios=tuple(outcomes),
        cleanup=cleanup,
        duration_seconds=time.monotonic() - started,
    )


@dataclass(frozen=True)
class ProcessExecution:
    """Bounded output and lifecycle result from one child process group."""

    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    diagnostics: str = _EMPTY


@dataclass
class FullRuntimeResources:
    """Resources and reversible setup state owned by one disposable full profile."""

    source_root: Path
    temporary_root: Path
    environment: dict[str, str]
    source_revision: str
    source_tree: str
    admin_terminal: PersistentTerminal | None = None
    install_attempted: bool = False
    start_attempted: bool = False
    original_adapter_flags: dict[str, bool] | None = None
    adapter_flags_changed: bool = False
    original_timezone: str | None = None
    expected_timezone: str | None = None
    unrelated_computer_role: str | None = None

    def open_admin_terminal(self) -> PersistentTerminal:
        """Create the one administrator PTY retained for fresh CLI processes."""
        if self.admin_terminal is None:
            self.admin_terminal = _open_terminal(self.environment)
            if self.admin_terminal.run([_SHELL_CHANGE_DIRECTORY, str(self.source_root)]).returncode != _PROCESS_SUCCESS:
                self.admin_terminal.close()
                self.admin_terminal = None
                raise RuntimeError(_FULL_TERMINAL_SETUP_ERROR)
        return self.admin_terminal

    def sanitize(self, text: str) -> str:
        """Remove source, home and disposable paths from retained command evidence."""
        text = text.replace(str(self.source_root), _SOURCE_TREE_PLACEHOLDER)
        text = text.replace(str(self.temporary_root), _SYNTHETIC_RUNTIME_PLACEHOLDER)
        home = self.environment.get(_COLD_HOME_VARIABLE)
        if home:
            text = text.replace(home, _RUNTIME_HOME_PLACEHOLDER)
        return text


def _run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int = _OUTPUT_LIMIT,
) -> ProcessExecution:
    """Run one command in an owned process group and retain bounded evidence."""
    started = time.monotonic()
    # A child process is required to exercise the checked public executable and uv as real boundaries.
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return ProcessExecution(
            exit_status=_PROCESS_LAUNCH_EXIT_CODE,
            stdout=_EMPTY,
            stderr=_EMPTY,
            duration_seconds=time.monotonic() - started,
            diagnostics=_PROCESS_LAUNCH_FAILED,
        )
    try:
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds)
            diagnostics = _EMPTY
        except subprocess.TimeoutExpired:
            _stop_process_group(process)
            stdout_bytes, stderr_bytes = process.communicate()
            diagnostics = _PROCESS_TIMEOUT_DETAIL
        except BaseException:
            _stop_process_group(process)
            process.communicate()
            raise
    finally:
        if process.poll() is None:
            _stop_process_group(process)
    output_exceeded = len(stdout_bytes) > output_limit_bytes or len(stderr_bytes) > output_limit_bytes
    if output_exceeded:
        diagnostics = _PROCESS_OUTPUT_LIMIT_DETAIL
    return ProcessExecution(
        exit_status=process.returncode if process.returncode is not None else _PROCESS_FAILURE,
        stdout=stdout_bytes[:output_limit_bytes].decode(_UTF8, errors=_UTF8_REPLACEMENT),
        stderr=stderr_bytes[:output_limit_bytes].decode(_UTF8, errors=_UTF8_REPLACEMENT),
        duration_seconds=time.monotonic() - started,
        diagnostics=diagnostics,
    )


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate every process in the command group, escalating after a short grace."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait()
    except ChildProcessError:
        return


def _environment_cache_key(source_root: Path) -> str:
    """Hash dependency inputs and interpreter identity for an immutable environment."""
    digest = hashlib.sha256()
    for relative_path in _ENVIRONMENT_MANIFESTS:
        manifest_path = source_root / relative_path
        digest.update(relative_path.encode(_UTF8))
        if manifest_path.is_file():
            digest.update(manifest_path.read_bytes())
        elif relative_path in _ENVIRONMENT_REQUIRED_MANIFESTS:
            raise FileNotFoundError(_ENVIRONMENT_INPUT_MISSING.format(path=relative_path))
    identity = (
        _ENVIRONMENT_GROUPS,
        str(Path(sys.executable).resolve()),
        sys.version,
        sys.implementation.cache_tag or _UNKNOWN_REVISION,
        platform.platform(),
    )
    digest.update(json.dumps(identity, separators=_JSON_SEPARATORS).encode(_UTF8))
    return digest.hexdigest()


def _environment_cache_root() -> Path:
    """Return the caller-owned, machine-local cache root for immutable environments."""
    cache_name = f"{_ENVIRONMENT_CACHE_DIRECTORY}-{os.getuid()}"
    return Path(tempfile.gettempdir()) / cache_name


def ensure_dependency_environment(source_root: Path) -> Path:
    """Prepare or reuse a locked environment that contains dependencies but no app install."""
    resolved_root = source_root.expanduser().resolve()
    cache_root = _environment_cache_root()
    cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache_root.chmod(0o700)
    generation = _environment_cache_key(resolved_root)
    environment_path = cache_root / generation
    lock_path = cache_root / f"{generation}{_ENVIRONMENT_LOCK_SUFFIX}"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if environment_path.exists():
            _validate_dependency_environment(environment_path, generation)
            return environment_path
        environment = _dependency_sync_environment(cache_root, environment_path)
        sync_result = _run_bounded_process(
            (
                *_UV_SYNC_ARGUMENTS,
                str(resolved_root),
                _UV_LOCKED_OPTION,
                _UV_NO_INSTALL_PROJECT_OPTION,
                _UV_NO_DEFAULT_GROUPS_OPTION,
            ),
            cwd=resolved_root,
            environment=environment,
            timeout_seconds=_UV_SYNC_TIMEOUT_SECONDS,
        )
        if sync_result.exit_status != 0 or sync_result.diagnostics:
            if environment_path.exists() and not environment_path.is_symlink():
                shutil.rmtree(environment_path)
            detail = _PROCESS_FAILURE_DETAIL.format(exit_status=sync_result.exit_status)
            raise RuntimeError(_ENVIRONMENT_SYNC_FAILED.format(detail=detail))
        manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
        manifest_path.write_text(json.dumps({"key": generation, "groups": _ENVIRONMENT_GROUPS}), encoding=_UTF8)
        _validate_dependency_environment(environment_path, generation)
        return environment_path


def _dependency_sync_environment(cache_root: Path, environment_path: Path) -> dict[str, str]:
    """Build an allowlisted environment for uv without inheriting credentials or project config."""
    runtime_home = cache_root / _SYNTHETIC_HOME_DIRECTORY
    runtime_cache = cache_root / _SYNTHETIC_CACHE_DIRECTORY
    runtime_temp = cache_root / _SYNTHETIC_TEMP_DIRECTORY
    runtime_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_temp.mkdir(mode=0o700, parents=True, exist_ok=True)
    child_environment = {
        _PATH_VARIABLE: os.environ.get(_PATH_VARIABLE, _EMPTY),
        _COLD_HOME_VARIABLE: str(runtime_home),
        _UV_CACHE_VARIABLE: str(runtime_cache),
        _ENVIRONMENT_VARIABLE: str(environment_path),
        _LOCALE_VARIABLE: os.environ.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _TMP_VARIABLE: str(runtime_temp),
    }
    return child_environment


def _validate_dependency_environment(environment_path: Path, generation: str) -> None:
    """Refuse an incomplete or mismatched cached environment without mutating it."""
    manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
    python_path = environment_path / _PYTHON_ENVIRONMENT_EXECUTABLE
    config_path = environment_path / _VENV_CONFIG_FILENAME
    if (
        environment_path.is_symlink()
        or not environment_path.is_dir()
        or not manifest_path.is_file()
        or not python_path.is_file()
        or not config_path.is_file()
    ):
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))
    try:
        manifest: object = json.loads(manifest_path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name)) from exc
    if manifest != {_MANIFEST_KEY_FIELD: generation, _MANIFEST_GROUPS_FIELD: _ENVIRONMENT_GROUPS}:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))


def _make_cold_environment(
    source_root: Path,
    dependency_environment: Path,
    temporary_root: Path,
    *,
    channel: str = _SYNTHETIC_RELEASE_CHANNEL,
    working_directory: Path | None = None,
) -> dict[str, str]:
    """Create disposable paths and a synthetic runtime config for cold CLI startup."""
    home = temporary_root / _SYNTHETIC_HOME_DIRECTORY
    state = temporary_root / _SYNTHETIC_STATE_DIRECTORY
    cache = temporary_root / _SYNTHETIC_CACHE_DIRECTORY
    config = temporary_root / _SYNTHETIC_CONFIG_DIRECTORY
    data = temporary_root / _SYNTHETIC_DATA_DIRECTORY
    temporary = temporary_root / _SYNTHETIC_TEMP_DIRECTORY
    for path in (home, state, cache, config, data, temporary):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    machine_config = {
        _CONFIG_COMPUTER_FIELD: {
            _COMPUTER_NAME_FIELD: _SYNTHETIC_COMPUTER_NAME,
            _COMPUTER_USER_FIELD: _SYNTHETIC_COMPUTER_USER,
            _COMPUTER_ROLE_FIELD: _COMPUTER_ROLE_DEFAULT,
            _COMPUTER_TIMEZONE_FIELD: _TIMEZONE_UTC,
            _COMPUTER_WORKING_DIRECTORY_FIELD: str(source_root if working_directory is None else working_directory),
            _COMPUTER_MASTER_FIELD: False,
            _COMPUTER_HOST_FIELD: _SYNTHETIC_COMPUTER_HOST,
            _COMPUTER_INGRESS_FIELD: False,
        },
        _CONFIG_AGENTS_FIELD: {
            _CONFIG_DEFAULT_FIELD: _SYNTHETIC_AGENT,
            _SYNTHETIC_AGENT: {_AGENT_ENABLED_FIELD: True},
        },
        _CONFIG_DEPLOYMENT_FIELD: {_CONFIG_CHANNEL_FIELD: channel},
    }
    (home / _CONFIG_FILENAME).write_text(json.dumps(machine_config), encoding=_UTF8)
    child_environment = {
        _PATH_VARIABLE: os.environ.get(_PATH_VARIABLE, _EMPTY),
        _LOCALE_VARIABLE: os.environ.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _COLD_HOME_VARIABLE: str(home),
        _TELECLAUDE_HOME_VARIABLE: str(home),
        _ENVIRONMENT_VARIABLE: str(dependency_environment),
        _UV_NO_SYNC_VARIABLE: _UV_NO_SYNC_VALUE,
        _NO_BYTECODE_VARIABLE: _TRUE_TEXT,
        _NO_USER_SITE_VARIABLE: _TRUE_TEXT,
        _XDG_STATE_VARIABLE: str(state),
        _XDG_CACHE_VARIABLE: str(cache),
        _XDG_CONFIG_VARIABLE: str(config),
        _XDG_DATA_VARIABLE: str(data),
        _TMP_VARIABLE: str(temporary),
        _GIT_CONFIG_GLOBAL_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_DISABLED_VARIABLE: _TRUE_TEXT,
        _NO_COLOR_VARIABLE: _TRUE_TEXT,
    }
    return child_environment


def _sanitize_report_text(
    text: str,
    source_root: Path,
    dependency_environment: Path,
    child_environment: Mapping[str, str],
) -> str:
    """Remove machine-local source, environment and disposable paths from retained output."""
    replacements = [
        (str(source_root), _SOURCE_TREE_PLACEHOLDER),
        (str(dependency_environment), _DEPENDENCY_ENVIRONMENT_PLACEHOLDER),
    ]
    replacements.extend(
        (child_environment[name], _SYNTHETIC_RUNTIME_PLACEHOLDER)
        for name in _SYNTHETIC_PATH_ENVIRONMENT_VARIABLES
        if name in child_environment
    )
    for value, replacement in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(value, replacement)
    return text


def _full_runtime_environment() -> dict[str, str]:
    """Build an allowlisted child environment that keeps the disposable VM home intact."""
    host_environment = os.environ  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    home = host_environment.get(_COLD_HOME_VARIABLE)
    if not home:
        raise RuntimeError(_FULL_HOME_REQUIRED)
    child_environment = {
        _PATH_VARIABLE: host_environment.get(_PATH_VARIABLE, _EMPTY),
        _COLD_HOME_VARIABLE: home,
        _LOCALE_VARIABLE: host_environment.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _TMP_VARIABLE: tempfile.gettempdir(),
        _NO_BYTECODE_VARIABLE: _TRUE_TEXT,
        _NO_USER_SITE_VARIABLE: _TRUE_TEXT,
        _UV_NO_SYNC_VARIABLE: _UV_NO_SYNC_VALUE,
        _GIT_CONFIG_GLOBAL_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_VARIABLE: os.devnull,
        _GIT_CONFIG_SYSTEM_DISABLED_VARIABLE: _TRUE_TEXT,
        _ENV_OWNER_NAME_VARIABLE: _OWNER_SEED_NAME,
        _ENV_OWNER_EMAIL_VARIABLE: _OWNER_SEED_EMAIL,
    }
    for name in (_USER_VARIABLE, _LOGNAME_VARIABLE, _SHELL_VARIABLE, _XDG_RUNTIME_VARIABLE, _DBUS_SESSION_VARIABLE):
        value = host_environment.get(name)
        if value:
            child_environment[name] = value
    if (ci_value := host_environment.get(_CI_VARIABLE)) is not None:
        child_environment[_CI_VARIABLE] = ci_value
    return child_environment


def _open_terminal(environment: Mapping[str, str]) -> PersistentTerminal:
    """Open one persistent PTY shell for authenticated, fresh CLI child processes."""
    terminal_environment = dict(environment)
    terminal_environment[_PROMPT_VARIABLE] = _EMPTY
    terminal_environment[_CONTINUATION_PROMPT_VARIABLE] = _EMPTY
    terminal = PersistentTerminal(
        [_BASH_EXECUTABLE, _BASH_NO_PROFILE_OPTION, _BASH_NO_RC_OPTION, _BASH_INTERACTIVE_OPTION],
        environment=terminal_environment,
        timeout_seconds=_FULL_COMMAND_TIMEOUT_SECONDS,
        output_limit_bytes=_OUTPUT_LIMIT,
        disable_echo=True,
    )
    terminal.__enter__()
    return terminal


def _record_terminal_command(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    argv: Sequence[str],
    evidence: list[CommandEvidence],
) -> tuple[int | None, str]:
    """Run one fresh CLI command on an owned PTY and retain bounded sanitized evidence."""
    started = time.monotonic()
    argv_tuple = tuple(argv)
    if argv_tuple and argv_tuple[0] == str(_CLI_EXECUTABLE):
        argv_tuple = (str(resources.source_root / _CLI_EXECUTABLE), *argv_tuple[1:])
    try:
        result = terminal.run(argv_tuple)
    except TerminalFailure as exc:
        evidence.append(
            CommandEvidence(
                argv=tuple(resources.sanitize(value) for value in argv_tuple),
                exit_status=None,
                duration_seconds=time.monotonic() - started,
                stdout=resources.sanitize(exc.output)[:_DIAGNOSTIC_LIMIT],
                diagnostics=_PROCESS_TIMEOUT_DETAIL,
            )
        )
        return None, exc.output
    sanitized_output = resources.sanitize(_terminal_diagnostic_output(result.output))
    evidence.append(
        CommandEvidence(
            argv=tuple(resources.sanitize(value) for value in argv_tuple),
            exit_status=result.returncode,
            duration_seconds=time.monotonic() - started,
            stdout=sanitized_output[:_DIAGNOSTIC_LIMIT],
        )
    )
    return result.returncode, result.output


def _record_external_command(
    resources: FullRuntimeResources,
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    evidence: list[CommandEvidence],
) -> ProcessExecution:
    """Run a lifecycle command in an owned process group and retain bounded evidence."""
    result = _run_bounded_process(
        argv,
        cwd=cwd,
        environment=resources.environment,
        timeout_seconds=timeout_seconds,
    )
    evidence.append(
        CommandEvidence(
            argv=tuple(resources.sanitize(value) for value in argv),
            exit_status=result.exit_status,
            duration_seconds=result.duration_seconds,
            stdout=resources.sanitize(result.stdout)[:_DIAGNOSTIC_LIMIT]
            if result.exit_status != _PROCESS_SUCCESS or result.diagnostics
            else _EMPTY,
            stderr=resources.sanitize(result.stderr)[:_DIAGNOSTIC_LIMIT]
            if result.exit_status != _PROCESS_SUCCESS or result.diagnostics
            else _EMPTY,
            diagnostics=result.diagnostics,
        )
    )
    return result


def _capture_scenario(
    scenario_id: str,
    resources: FullRuntimeResources,
    action: Callable[[list[CommandEvidence]], None],
) -> ScenarioResult:
    """Collect command evidence for one full-profile journey without leaking runtime paths."""
    started = time.monotonic()
    evidence: list[CommandEvidence] = []
    try:
        action(evidence)
        status = ScenarioStatus.PASSED
        diagnostics = _EMPTY
    except Exception as exc:
        status = ScenarioStatus.FAILED
        diagnostics = resources.sanitize(f"{type(exc).__name__}: {exc}")[:_DIAGNOSTIC_LIMIT]
    return ScenarioResult(
        scenario_id=scenario_id,
        status=status,
        duration_seconds=time.monotonic() - started,
        commands=tuple(
            command
            if status is ScenarioStatus.FAILED
            and (index == len(evidence) - 1 or command.exit_status != _PROCESS_SUCCESS or command.diagnostics)
            else replace(command, stdout=_EMPTY)
            for index, command in enumerate(evidence)
        ),
        diagnostics=diagnostics,
    )


FullScenarioAction = Callable[[FullRuntimeResources, list[CommandEvidence]], None]


def _bind_full_scenario(
    scenario_id: str,
    resources: FullRuntimeResources,
    action: FullScenarioAction,
) -> ScenarioAction:
    """Adapt one full-profile action to the report runner's result contract."""

    def run() -> ScenarioResult:
        def invoke(evidence: list[CommandEvidence]) -> None:
            action(resources, evidence)

        return _capture_scenario(scenario_id, resources, invoke)

    return run


def _structured_value(output: str) -> object | None:
    """Decode one JSON value from a CLI terminal capture, skipping shell echo and prompt text."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character not in (_JSON_OBJECT_START, _JSON_ARRAY_START):
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
            return cast(object, value)
        except json.JSONDecodeError:
            continue
    return None


def _mapping_value(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if any(not isinstance(key, str) for key in value):
        return None
    return value


def _terminal_diagnostic_output(output: str) -> str:
    """Keep public result structure without the disposable runner's identity values."""
    payload = _structured_value(output)
    if payload is None:
        return output
    return json.dumps(_redact_runner_identity(payload), ensure_ascii=True)


def _redact_runner_identity(value: object) -> object:
    """Redact identity leaves in public computer and configuration result objects."""
    mapping = _mapping_value(value)
    if mapping is not None:
        return {
            key: _REDACTED_RUNNER_IDENTITY
            if key in _RUNNER_IDENTITY_FIELDS and isinstance(item, str)
            else _redact_runner_identity(item)
            for key, item in mapping.items()
        }
    if isinstance(value, list):
        return [_redact_runner_identity(item) for item in value]
    return value


def _computer_view(output: str) -> tuple[Mapping[str, object], str]:
    """Read the typed public computer view and opaque revision from CLI JSON."""
    payload = _mapping_value(_structured_value(output))
    if payload is None:
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    computer = _mapping_value(payload.get(_CONFIG_COMPUTER_FIELD))
    revision = payload.get(_MACHINE_REVISION_FIELD)
    if computer is None or not isinstance(revision, str) or not revision:
        raise ValueError(_FULL_BAD_REVISION)
    return computer, revision


def _computer_identity(machine: Mapping[str, object]) -> Mapping[str, object]:
    """Read identity fields inside the computer-kind machine document."""
    computer = _mapping_value(machine.get(_CONFIG_COMPUTER_FIELD))
    if computer is None:
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    return computer


def _computer_list_has_ready_local(output: str) -> bool:
    """Verify the public daemon response reports its local computer online."""
    expected = _mapping_value(
        json.loads((Path(__file__).parent / _READY_LOCAL_COMPUTER_SNAPSHOT).read_text(encoding=_UTF8))
    )
    payload = _structured_value(output)
    if not isinstance(payload, list):
        return False
    for item in payload:
        row = _mapping_value(item)
        if row is not None and row.get(_COMPUTER_IS_LOCAL_FIELD) is True:
            actual = {
                _COMPUTER_IS_LOCAL_FIELD: row.get(_COMPUTER_IS_LOCAL_FIELD),
                _COMPUTER_STATUS_FIELD: row.get(_COMPUTER_STATUS_FIELD),
            }
            return actual == expected
    return False


def _owner_record_is_administrator(output: str) -> bool:
    """Verify the owner seed resolves to the declared platform administrator standing."""
    payload = _mapping_value(_structured_value(output))
    if payload is None:
        return False
    roles = payload.get(_ROLE_SECTION)
    return isinstance(roles, list) and any(
        (role := _mapping_value(item)) is not None and role.get(_ROLE_PLATFORM_FIELD) == _ADMIN_ROLE for item in roles
    )


def _parse_whoami_fields(output: str) -> WhoAmIFields | None:
    """Parse the public whoami key/value lines without grading unrelated output text."""
    fields: dict[str, str] = {}
    expected_fields = {_WHOAMI_EMAIL_FIELD, _WHOAMI_ROLE_FIELD}
    for line in output.splitlines():
        field, separator, value = line.partition(_WHOAMI_LABEL_SEPARATOR)
        if separator and field in expected_fields:
            if field in fields:
                return None
            fields[field] = value.strip()
    email = fields.get(_WHOAMI_EMAIL_FIELD)
    role = fields.get(_WHOAMI_ROLE_FIELD)
    if not email or not role:
        return None
    return WhoAmIFields(email=email, role=role)


def _require_process_success(result: ProcessExecution) -> None:
    if result.exit_status != _PROCESS_SUCCESS or result.diagnostics:
        raise RuntimeError(_EXPECTED_COMMAND_ERROR)


def _require_terminal_success(exit_status: int | None, output: str, evidence: Sequence[CommandEvidence]) -> None:
    if exit_status != _PROCESS_SUCCESS or not output.strip() or evidence[-1].diagnostics:
        raise RuntimeError(_FULL_NO_OUTPUT_ERROR)


def _read_computer_config(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    evidence: list[CommandEvidence],
) -> tuple[Mapping[str, object], str, str]:
    exit_status, output = _record_terminal_command(
        resources,
        terminal,
        _CONFIG_COMPUTER_GET_COMMAND,
        evidence,
    )
    _require_terminal_success(exit_status, output, evidence)
    computer, revision = _computer_view(output)
    return computer, revision, output


def _patch_configuration(
    resources: FullRuntimeResources,
    terminal: PersistentTerminal,
    argv_prefix: Sequence[str],
    revision: str,
    patch: Mapping[str, JSONValue],
    evidence: list[CommandEvidence],
) -> None:
    argv = (*argv_prefix, _REVISION_OPTION, revision, _YAML_OPTION, json.dumps(patch))
    exit_status, output = _record_terminal_command(resources, terminal, argv, evidence)
    _require_terminal_success(exit_status, output, evidence)


def _disable_external_adapters(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    computer, revision, _ = _read_computer_config(resources, terminal, evidence)
    changes: JSONObject = {}
    original_flags: dict[str, bool] = {}
    for section_name in _MACHINE_ADAPTER_SECTIONS:
        section = _mapping_value(computer.get(section_name))
        if section is None:
            continue
        enabled = section.get(_MACHINE_ADAPTER_ENABLED_FIELD)
        if enabled is False:
            continue
        if enabled is True:
            original_flags[section_name] = True
        changes[section_name] = {_MACHINE_ADAPTER_ENABLED_FIELD: False}
    if not changes:
        return
    resources.original_adapter_flags = original_flags
    resources.adapter_flags_changed = True
    _patch_configuration(
        resources,
        terminal,
        _CONFIG_COMPUTER_PATCH_PREFIX,
        revision,
        changes,
        evidence,
    )


def _restore_full_profile_changes(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.admin_terminal
    if terminal is None:
        return
    if resources.adapter_flags_changed or resources.original_timezone is not None:
        try:
            _run_readiness_check(resources, evidence)
            computer, revision, _ = _read_computer_config(resources, terminal, evidence)
            restore: JSONObject = {}
            if (
                resources.original_timezone is not None
                and _computer_identity(computer).get(_MACHINE_TIMEZONE_FIELD) != resources.original_timezone
            ):
                restore[_CONFIG_COMPUTER_FIELD] = {_MACHINE_TIMEZONE_FIELD: resources.original_timezone}
            for section_name, enabled in (resources.original_adapter_flags or {}).items():
                section = _mapping_value(computer.get(section_name))
                if section is None:
                    raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
                if section.get(_MACHINE_ADAPTER_ENABLED_FIELD) is not enabled:
                    restore[section_name] = {_MACHINE_ADAPTER_ENABLED_FIELD: enabled}
            if restore:
                previous_instance = _read_daemon_instance(_HEALTH_SOCKET_PATH, _HEALTH_OBSERVATION_TIMEOUT_SECONDS)
                if previous_instance is None:
                    raise RuntimeError(_EXPECTED_READINESS_ERROR)
                _patch_configuration(
                    resources,
                    terminal,
                    _CONFIG_COMPUTER_PATCH_PREFIX,
                    revision,
                    restore,
                    evidence,
                )
                _await_config_restart(resources, evidence, previous_instance)
            resources.adapter_flags_changed = False
            resources.original_timezone = None
        except Exception as exc:
            raise RuntimeError(_FULL_CONFIG_RESTORE_ERROR) from exc


def _close_full_profile_resources(
    resources: FullRuntimeResources,
    cleanup_evidence: list[CommandEvidence],
) -> None:
    """Stop the supported runtime, restore temporary declarations and remove owned resources."""
    failures: list[str] = []
    try:
        _restore_full_profile_changes(resources, cleanup_evidence)
    except Exception:
        failures.append(_FULL_CONFIG_RESTORE_ERROR)
    terminal = resources.admin_terminal
    if terminal is not None:
        try:
            logout_status, logout_output = _record_terminal_command(
                resources,
                terminal,
                _AUTH_LOGOUT_COMMAND,
                cleanup_evidence,
            )
            _require_terminal_success(logout_status, logout_output, cleanup_evidence)
        except Exception:
            failures.append(_FULL_TERMINAL_CLEANUP_ERROR)
    if resources.install_attempted:
        result = _record_external_command(
            resources,
            _SERVICE_STOP_COMMAND,
            cwd=resources.source_root,
            timeout_seconds=_STOP_COMMAND_TIMEOUT_SECONDS,
            evidence=cleanup_evidence,
        )
        if result.exit_status != _PROCESS_SUCCESS or result.diagnostics:
            failures.append(_FULL_SERVICE_STOP_ERROR)
    if terminal is not None:
        try:
            terminal.close()
        except Exception:
            failures.append(_FULL_TERMINAL_CLEANUP_ERROR)
    try:
        shutil.rmtree(resources.temporary_root)
    except OSError:
        failures.append(_FULL_TEMP_CLEANUP_ERROR)
    if failures:
        raise RuntimeError(_FULL_CLEANUP_FAILURE.format(failures=_CLEANUP_FAILURE_SEPARATOR.join(failures)))


def _run_readiness_check(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    deadline = time.monotonic() + _READINESS_WINDOW_SECONDS
    while time.monotonic() < deadline:
        result = _record_external_command(
            resources,
            _SERVICE_STATUS_COMMAND,
            cwd=resources.source_root,
            timeout_seconds=_FULL_COMMAND_TIMEOUT_SECONDS,
            evidence=evidence,
        )
        if result.exit_status == _PROCESS_SUCCESS and not result.diagnostics:
            return
        time.sleep(_READINESS_POLL_INTERVAL_SECONDS)
    raise RuntimeError(_EXPECTED_READINESS_ERROR)


def _read_health_body(socket_path: str, timeout_seconds: float) -> bytes | None:
    """Read bounded HTTP bytes with one deadline across connect, headers and body."""
    expired = threading.Event()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout_seconds)

            def expire() -> None:
                expired.set()
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    # Deadline expiry can race an unconnected or already-closed socket.
                    pass

            timer = threading.Timer(timeout_seconds, expire)
            timer.start()
            try:
                connection.connect(socket_path)
                if expired.is_set():
                    return None
                connection.sendall(_HEALTH_HTTP_REQUEST)
                with http.client.HTTPResponse(connection) as response:
                    response.begin()
                    if response.status != http.HTTPStatus.OK:
                        return None
                    body = response.read(_HEALTH_RESPONSE_LIMIT_BYTES + 1)
            finally:
                timer.cancel()
                timer.join()
    except (ConnectionError, FileNotFoundError, TimeoutError):
        return None
    except http.client.HTTPException:
        if expired.is_set():
            return None
        raise
    return None if expired.is_set() else body


def _read_daemon_instance(socket_path: str, timeout_seconds: float) -> DaemonInstance | None:
    """Observe the public local health identity; a closed socket is a transition state."""
    body = _read_health_body(socket_path, timeout_seconds)
    if body is None:
        return None
    if len(body) > _HEALTH_RESPONSE_LIMIT_BYTES:
        raise ValueError(_HEALTH_INSTANCE_INVALID)
    health = _mapping_value(json.loads(body))
    preparation = _mapping_value(health.get(_HEALTH_PREPARATION_FIELD)) if health is not None else None
    if preparation is None:
        raise ValueError(_HEALTH_INSTANCE_INVALID)
    pid, token = preparation.get(_HEALTH_PID_FIELD), preparation.get(_HEALTH_TOKEN_FIELD)
    if type(pid) is not int or pid <= 0 or not isinstance(token, str) or not token:
        raise ValueError(_HEALTH_INSTANCE_INVALID)
    return DaemonInstance(pid, token)


def _await_config_restart(
    resources: FullRuntimeResources, evidence: list[CommandEvidence], previous: DaemonInstance
) -> None:
    """Wait for a different process instance before applying the ordinary readiness gate."""
    deadline = time.monotonic() + _READINESS_WINDOW_SECONDS
    while (remaining := deadline - time.monotonic()) > 0:
        instance = _read_daemon_instance(_HEALTH_SOCKET_PATH, min(_HEALTH_OBSERVATION_TIMEOUT_SECONDS, remaining))
        if instance is not None and instance != previous:
            _run_readiness_check(resources, evidence)
            return
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(_READINESS_POLL_INTERVAL_SECONDS, remaining))
    raise RuntimeError(_HEALTH_INSTANCE_UNCHANGED)


def _full_install_and_ready(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    resources.install_attempted = True
    installer_environment = dict(resources.environment)
    installer_environment[_ENV_OWNER_NAME_VARIABLE] = _OWNER_SEED_NAME
    installer_environment[_ENV_OWNER_EMAIL_VARIABLE] = _OWNER_SEED_EMAIL
    installer_environment.pop(_CI_VARIABLE, None)
    install_result = _run_bounded_process(
        (str(resources.source_root / _INSTALLER_COMMAND[0]), *_INSTALLER_COMMAND[1:]),
        cwd=resources.source_root,
        environment=installer_environment,
        timeout_seconds=_INSTALL_COMMAND_TIMEOUT_SECONDS,
        output_limit_bytes=_INSTALLER_OUTPUT_LIMIT_BYTES,
    )
    diagnostics = _EMPTY
    if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics:
        max_process_diagnostic_chars = (
            _DIAGNOSTIC_LIMIT - len(_INSTALLER_LOG_LABEL) - len(_INSTALLER_LOG_TRUNCATION_MARKER) - 1
        )
        process_diagnostics = resources.sanitize(install_result.diagnostics)[:max_process_diagnostic_chars]
        diagnostic_prefix = f"{process_diagnostics}{_DIAGNOSTIC_SEPARATOR}" if process_diagnostics else _EMPTY
        installer_log_diagnostic: str
        try:
            log_budget = max(
                1,
                _DIAGNOSTIC_LIMIT
                - len(diagnostic_prefix)
                - len(_INSTALLER_LOG_LABEL)
                - len(_INSTALLER_LOG_TRUNCATION_MARKER),
            )
            with (resources.source_root / _INSTALLER_LOG_PATH).open(_BINARY_READ_MODE) as installer_log:
                installer_log.seek(0, os.SEEK_END)
                log_size = installer_log.tell()
                log_start = max(0, log_size - log_budget)
                installer_log.seek(log_start)
                log_excerpt = installer_log.read(log_budget).decode(_UTF8, errors=_UTF8_REPLACEMENT)
            truncation_marker = _INSTALLER_LOG_TRUNCATION_MARKER if log_start else _EMPTY
            available_log_chars = max(
                1,
                _DIAGNOSTIC_LIMIT - len(diagnostic_prefix) - len(_INSTALLER_LOG_LABEL) - len(truncation_marker),
            )
            sanitized_log_excerpt = resources.sanitize(log_excerpt)
            installer_log_diagnostic = (
                f"{_INSTALLER_LOG_LABEL}{truncation_marker}{sanitized_log_excerpt[-available_log_chars:]}"
            )
        except OSError as error:
            installer_log_diagnostic = _INSTALLER_LOG_UNAVAILABLE.format(error_class=type(error).__name__)[
                : _DIAGNOSTIC_LIMIT - len(diagnostic_prefix)
            ]
        log_tail = installer_log_diagnostic[-_INSTALLER_LOG_TAIL_LIMIT:]
        stdout_tail = resources.sanitize(install_result.stdout[-_INSTALLER_STDOUT_TAIL_LIMIT:])
        stderr_tail = resources.sanitize(install_result.stderr[-_INSTALLER_STDERR_TAIL_LIMIT:])
        diagnostics = (
            f"{diagnostic_prefix}{log_tail}{_DIAGNOSTIC_SEPARATOR}"
            f"{_INSTALLER_STDOUT_TAIL_LABEL}{stdout_tail}{_DIAGNOSTIC_SEPARATOR}"
            f"{_INSTALLER_STDERR_TAIL_LABEL}{stderr_tail}"
        )[-_DIAGNOSTIC_LIMIT:]
    evidence.append(
        CommandEvidence(
            argv=tuple(resources.sanitize(value) for value in _INSTALLER_COMMAND),
            exit_status=install_result.exit_status,
            duration_seconds=install_result.duration_seconds,
            stdout=resources.sanitize(install_result.stdout)[:_DIAGNOSTIC_LIMIT]
            if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics
            else _EMPTY,
            stderr=resources.sanitize(install_result.stderr)[:_DIAGNOSTIC_LIMIT]
            if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics
            else _EMPTY,
            diagnostics=diagnostics,
        )
    )
    if install_result.exit_status != _PROCESS_SUCCESS or install_result.diagnostics:
        raise RuntimeError(_FULL_INSTALL_ERROR)
    terminal = resources.open_admin_terminal()
    login_status, login_output = _record_terminal_command(
        resources,
        terminal,
        (*_AUTH_LOGIN_PREFIX, _OWNER_SEED_EMAIL),
        evidence,
    )
    _require_terminal_success(login_status, login_output, evidence)
    resources.start_attempted = True
    start_result = _record_external_command(
        resources,
        _SERVICE_START_COMMAND,
        cwd=resources.source_root,
        timeout_seconds=_START_COMMAND_TIMEOUT_SECONDS,
        evidence=evidence,
    )
    _require_process_success(start_result)
    _run_readiness_check(resources, evidence)
    _disable_external_adapters(resources, evidence)
    computer_status, computer_output = _record_terminal_command(
        resources,
        terminal,
        _COMPUTERS_LIST_COMMAND,
        evidence,
    )
    _require_terminal_success(computer_status, computer_output, evidence)
    if not _computer_list_has_ready_local(computer_output):
        raise ValueError(_EXPECTED_COMPUTER_LIST_ERROR)


def _full_owner_identity(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    whoami_status, whoami_output = _record_terminal_command(
        resources,
        terminal,
        _AUTH_WHOAMI_COMMAND,
        evidence,
    )
    _require_terminal_success(whoami_status, whoami_output, evidence)
    whoami = _parse_whoami_fields(whoami_output)
    if whoami is None or whoami.email != _OWNER_SEED_EMAIL or whoami.role != _ADMIN_ROLE:
        raise ValueError(_EXPECTED_OWNER_WHOAMI_ERROR)
    person_status, person_output = _record_terminal_command(
        resources,
        terminal,
        (*_CONFIG_PERSON_GET_PREFIX, _OWNER_SEED_SLUG, _FORMAT_OPTION, _JSON_FORMAT),
        evidence,
    )
    _require_terminal_success(person_status, person_output, evidence)
    if not _owner_record_is_administrator(person_output):
        raise ValueError(_EXPECTED_PERSON_IDENTITY_ERROR)


def _full_configuration_change(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    terminal = resources.open_admin_terminal()
    computer, revision, _ = _read_computer_config(resources, terminal, evidence)
    computer = _computer_identity(computer)
    original_timezone = computer.get(_MACHINE_TIMEZONE_FIELD)
    if not isinstance(original_timezone, str):
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    unrelated_role = computer.get(_COMPUTER_ROLE_FIELD)
    if not isinstance(unrelated_role, str):
        raise ValueError(_FULL_CONFIG_SHAPE_INVALID)
    timezone = _TIMEZONE_EUROPE_AMSTERDAM if original_timezone == _TIMEZONE_UTC else _TIMEZONE_UTC
    resources.original_timezone = original_timezone
    resources.expected_timezone = timezone
    resources.unrelated_computer_role = unrelated_role
    previous_instance = _read_daemon_instance(_HEALTH_SOCKET_PATH, _HEALTH_OBSERVATION_TIMEOUT_SECONDS)
    if previous_instance is None:
        raise RuntimeError(_EXPECTED_READINESS_ERROR)
    patch: JSONObject = {
        _CONFIG_COMPUTER_FIELD: {_MACHINE_TIMEZONE_FIELD: timezone},
    }
    _patch_configuration(resources, terminal, _CONFIG_COMPUTER_PATCH_PREFIX, revision, patch, evidence)
    _await_config_restart(resources, evidence, previous_instance)
    verified_terminal = resources.open_admin_terminal()
    verified, new_revision, _ = _read_computer_config(resources, verified_terminal, evidence)
    verified = _computer_identity(verified)
    if verified.get(_MACHINE_TIMEZONE_FIELD) != timezone:
        raise ValueError(_EXPECTED_VALID_PATCH_ERROR)
    if verified.get(_COMPUTER_ROLE_FIELD) != unrelated_role:
        raise ValueError(_FULL_STATE_CHANGED)
    if new_revision == revision:
        raise ValueError(_EXPECTED_REVISION_CHANGE_ERROR)


def _full_restart_persistence(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    resources.start_attempted = True
    restart_result = _record_external_command(
        resources,
        _SERVICE_RESTART_COMMAND,
        cwd=resources.source_root,
        timeout_seconds=_RESTART_COMMAND_TIMEOUT_SECONDS,
        evidence=evidence,
    )
    _require_process_success(restart_result)
    _run_readiness_check(resources, evidence)
    terminal = resources.open_admin_terminal()
    computer, _, _ = _read_computer_config(resources, terminal, evidence)
    computer = _computer_identity(computer)
    if computer.get(_MACHINE_TIMEZONE_FIELD) != resources.expected_timezone:
        raise ValueError(_FULL_STATE_CHANGED)
    if computer.get(_COMPUTER_ROLE_FIELD) != resources.unrelated_computer_role:
        raise ValueError(_FULL_STATE_CHANGED)


def _full_failure_cleanup_probe(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    failure = _run_bounded_process(
        (_FALSE_EXECUTABLE,),
        cwd=resources.source_root,
        environment=resources.environment,
        timeout_seconds=_FULL_COMMAND_TIMEOUT_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=(_FALSE_EXECUTABLE,),
            exit_status=failure.exit_status,
            duration_seconds=failure.duration_seconds,
            diagnostics=failure.diagnostics,
        )
    )
    if failure.exit_status == _PROCESS_SUCCESS:
        raise ValueError(_FULL_FAILURE_PROBE_FAILED)
    timeout = _run_bounded_process(
        (_SLEEP_EXECUTABLE, _TIMEOUT_PROBE_DURATION),
        cwd=resources.source_root,
        environment=resources.environment,
        timeout_seconds=_TIMEOUT_PROBE_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=(_SLEEP_EXECUTABLE, _TIMEOUT_PROBE_DURATION),
            exit_status=timeout.exit_status,
            duration_seconds=timeout.duration_seconds,
            diagnostics=timeout.diagnostics,
        )
    )
    if timeout.diagnostics != _PROCESS_TIMEOUT_DETAIL:
        raise ValueError(_FULL_FAILURE_PROBE_FAILED)


def _full_candidate_identity(resources: FullRuntimeResources, evidence: list[CommandEvidence]) -> None:
    del evidence
    if not resources.source_root.is_dir() or not resources.source_revision or not resources.source_tree:
        raise ValueError(_FULL_CANDIDATE_IDENTITY_INVALID)


def _cold_entrypoint_scenario(
    source_root: Path,
    child_environment: Mapping[str, str],
    dependency_environment: Path,
) -> ScenarioResult:
    """Exercise the reviewed cold public entry points from one prospective source tree."""
    command_rows = (
        ((str(_CLI_EXECUTABLE), *_CLI_HELP_ARGUMENTS), child_environment),
        ((str(_CLI_EXECUTABLE), *_CLI_REPO_HELP_ARGUMENTS), child_environment),
        ((str(_CLI_EXECUTABLE), *_CLI_VERSION_ARGUMENTS), child_environment),
    )
    evidence: list[CommandEvidence] = []
    scenario_started = time.monotonic()
    for argv, command_environment in command_rows:
        result = _run_bounded_process(
            argv,
            cwd=source_root,
            environment=command_environment,
            timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        )
        evidence.append(
            CommandEvidence(
                argv=argv,
                exit_status=result.exit_status,
                duration_seconds=result.duration_seconds,
                stdout=_sanitize_report_text(result.stdout, source_root, dependency_environment, child_environment),
                stderr=_sanitize_report_text(result.stderr, source_root, dependency_environment, child_environment),
                diagnostics=result.diagnostics,
            )
        )
        if result.exit_status != _PROCESS_SUCCESS or not result.stdout.strip() or result.diagnostics:
            return ScenarioResult(
                scenario_id=_SCENARIO_COLD,
                status=ScenarioStatus.FAILED,
                duration_seconds=time.monotonic() - scenario_started,
                commands=tuple(evidence),
                diagnostics=_SCENARIO_PUBLIC_RESULT,
            )
    module_environment = dict(child_environment)
    module_environment[_PYTHON_PATH_VARIABLE] = str(source_root)
    module_environment[_PATH_VARIABLE] = (
        f"{dependency_environment / _PYTHON_ENVIRONMENT_EXECUTABLE.parent}"
        f"{_PATH_SEPARATOR}{module_environment[_PATH_VARIABLE]}"
    )
    module_argv = (
        _PYTHON_EXECUTABLE,
        *_MODULE_HELP_ARGUMENTS,
    )
    module_result = _run_bounded_process(
        module_argv,
        cwd=source_root,
        environment=module_environment,
        timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=module_argv,
            exit_status=module_result.exit_status,
            duration_seconds=module_result.duration_seconds,
            stdout=_sanitize_report_text(
                module_result.stdout,
                source_root,
                dependency_environment,
                module_environment,
            ),
            stderr=_sanitize_report_text(
                module_result.stderr,
                source_root,
                dependency_environment,
                module_environment,
            ),
            diagnostics=module_result.diagnostics,
        )
    )
    if module_result.exit_status != _PROCESS_SUCCESS or not module_result.stdout.strip() or module_result.diagnostics:
        return ScenarioResult(
            scenario_id=_SCENARIO_COLD,
            status=ScenarioStatus.FAILED,
            duration_seconds=time.monotonic() - scenario_started,
            commands=tuple(evidence),
            diagnostics=_SCENARIO_PUBLIC_RESULT,
        )

    import_argv = (
        _PYTHON_EXECUTABLE,
        _PACKAGE_IMPORT_ISOLATED_OPTION,
        str(_PACKAGE_IMPORT_SCRIPT),
    )
    import_result = _run_bounded_process(
        import_argv,
        cwd=source_root,
        environment=module_environment,
        timeout_seconds=_PACKAGE_IMPORT_TIMEOUT_SECONDS,
    )
    evidence.append(
        CommandEvidence(
            argv=import_argv,
            exit_status=import_result.exit_status,
            duration_seconds=import_result.duration_seconds,
            stdout=_sanitize_report_text(
                import_result.stdout,
                source_root,
                dependency_environment,
                module_environment,
            ),
            stderr=_sanitize_report_text(
                import_result.stderr,
                source_root,
                dependency_environment,
                module_environment,
            ),
            diagnostics=import_result.diagnostics,
        )
    )
    passed = (
        import_result.exit_status == _PROCESS_SUCCESS
        and bool(import_result.stdout.strip())
        and not import_result.diagnostics
    )
    return ScenarioResult(
        scenario_id=_SCENARIO_COLD,
        status=ScenarioStatus.PASSED if passed else ScenarioStatus.FAILED,
        duration_seconds=time.monotonic() - scenario_started,
        commands=tuple(evidence),
        diagnostics=_EMPTY if passed else _SCENARIO_PUBLIC_RESULT,
    )


def run_profile(
    profile: Profile,
    *,
    source_root: Path,
    source_revision: str,
    source_tree: str,
) -> AcceptanceReport:
    """Run the selected profile with disposable state and report cleanup separately."""
    resolved_root = source_root.expanduser().resolve()
    temporary_root = Path(tempfile.mkdtemp(prefix=_ENVIRONMENT_CACHE_DIRECTORY))
    try:

        def cold_action() -> ScenarioResult:
            dependency_environment = ensure_dependency_environment(resolved_root)
            child_environment = _make_cold_environment(resolved_root, dependency_environment, temporary_root)
            return _cold_entrypoint_scenario(resolved_root, child_environment, dependency_environment)

        actions: dict[str, ScenarioAction] = {_SCENARIO_COLD: cold_action}
        inventory: Sequence[str] = _COLD_PROFILE_SCENARIOS

        def cleanup_cold(evidence: list[CommandEvidence]) -> None:
            del evidence
            shutil.rmtree(temporary_root)

        cleanup_action: CleanupAction = cleanup_cold
        if profile is Profile.FULL:
            resources = FullRuntimeResources(
                source_root=resolved_root,
                temporary_root=temporary_root,
                environment=_full_runtime_environment(),
                source_revision=source_revision,
                source_tree=source_tree,
            )
            actions.update(
                {
                    _SCENARIO_RUNTIME_READY: _bind_full_scenario(
                        _SCENARIO_RUNTIME_READY, resources, _full_install_and_ready
                    ),
                    _SCENARIO_OWNER_IDENTITY: _bind_full_scenario(
                        _SCENARIO_OWNER_IDENTITY, resources, _full_owner_identity
                    ),
                    _SCENARIO_CONFIG_PATCH: _bind_full_scenario(
                        _SCENARIO_CONFIG_PATCH, resources, _full_configuration_change
                    ),
                    _SCENARIO_RESTART_PERSISTENCE: _bind_full_scenario(
                        _SCENARIO_RESTART_PERSISTENCE, resources, _full_restart_persistence
                    ),
                    _SCENARIO_CLEANUP: _bind_full_scenario(_SCENARIO_CLEANUP, resources, _full_failure_cleanup_probe),
                    _SCENARIO_CANDIDATE_IDENTITY: _bind_full_scenario(
                        _SCENARIO_CANDIDATE_IDENTITY, resources, _full_candidate_identity
                    ),
                }
            )
            inventory = _FULL_PROFILE_SCENARIOS

            def cleanup_full(evidence: list[CommandEvidence]) -> None:
                _close_full_profile_resources(resources, evidence)

            cleanup_action = cleanup_full
        return execute_profile(
            profile,
            source_revision=source_revision,
            source_tree=source_tree,
            scenario_inventory=inventory,
            scenario_actions=actions,
            cleanup_action=cleanup_action,
        )
    except BaseException:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise


def write_report(report: AcceptanceReport, report_path: Path) -> None:
    """Persist a report atomically enough that readers never accept a partial JSON file."""
    temporary_path = report_path.with_suffix(f"{report_path.suffix}{_REPORT_TEMP_SUFFIX}")
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(json.dumps(asdict(report), indent=2) + _LINE_BREAK, encoding=_UTF8)
        temporary_path.replace(report_path)
    except OSError as exc:
        raise RuntimeError(_REPORT_WRITE_ERROR.format(error=exc)) from exc


def validate_full_report_bytes(report_bytes: bytes, *, source_revision: str, source_tree: str) -> None:
    """Require complete, successful structured full-profile evidence for one exact source tree."""
    try:
        report = json.loads(report_bytes)
        expected_fields = {
            "schema_version",
            "source_revision",
            "source_tree",
            "profile",
            "scenario_inventory",
            "scenarios",
            "cleanup",
            "duration_seconds",
        }
        if (
            not isinstance(report, dict)
            or set(report) != expected_fields
            or type(report["schema_version"]) is not int
            or report["schema_version"] != _REPORT_SCHEMA_VERSION
            or report["source_revision"] != source_revision
            or report["source_tree"] != source_tree
            or report["profile"] != _PROFILE_FULL
            or report["scenario_inventory"] != list(_FULL_PROFILE_SCENARIOS)
            or type(report["duration_seconds"]) not in (int, float)
            or not math.isfinite(report["duration_seconds"])
            or report["duration_seconds"] < 0
        ):
            raise ValueError
        scenarios = report["scenarios"]
        if not isinstance(scenarios, list) or len(scenarios) != len(_FULL_PROFILE_SCENARIOS):
            raise ValueError
        for expected_id, scenario in zip(_FULL_PROFILE_SCENARIOS, scenarios, strict=True):
            if (
                not isinstance(scenario, dict)
                or set(scenario) != {"scenario_id", "status", "duration_seconds", "commands", "diagnostics"}
                or scenario["scenario_id"] != expected_id
                or scenario["status"] != ScenarioStatus.PASSED.value
                or type(scenario["duration_seconds"]) not in (int, float)
                or not math.isfinite(scenario["duration_seconds"])
                or scenario["duration_seconds"] < 0
                or not isinstance(scenario["commands"], list)
                or scenario["diagnostics"] != _EMPTY
            ):
                raise ValueError
            for command in scenario["commands"]:
                if (
                    not isinstance(command, dict)
                    or set(command) != {"argv", "exit_status", "duration_seconds", "stdout", "stderr", "diagnostics"}
                    or not isinstance(command["argv"], list)
                    or not all(isinstance(part, str) for part in command["argv"])
                    or (command["exit_status"] is not None and type(command["exit_status"]) is not int)
                    or type(command["duration_seconds"]) not in (int, float)
                    or not math.isfinite(command["duration_seconds"])
                    or command["duration_seconds"] < 0
                    or not all(isinstance(command[field], str) for field in ("stdout", "stderr", "diagnostics"))
                ):
                    raise ValueError
        cleanup = report["cleanup"]
        if (
            not isinstance(cleanup, dict)
            or set(cleanup) not in ({"status", "detail"}, {"status", "detail", "commands"})
            or cleanup["status"] != ScenarioStatus.PASSED.value
            or cleanup["detail"] != _EMPTY
            or ("commands" in cleanup and cleanup["commands"] != [])
        ):
            raise ValueError
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, OverflowError, TypeError, ValueError):
        raise ValueError(_FULL_REPORT_INVALID) from None


def _parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument(_PROFILE_OPTION, choices=[profile.value for profile in Profile], required=True)
    parser.add_argument(_ROOT_OPTION, type=Path, default=Path(_DEFAULT_ROOT))
    parser.add_argument(_SOURCE_REVISION_OPTION, required=True)
    parser.add_argument(_SOURCE_TREE_OPTION, required=True)
    default_report = Path(tempfile.gettempdir()) / _REPORT_NAME_TEMPLATE.format(identifier=uuid.uuid4().hex)
    parser.add_argument(_REPORT_OPTION, type=Path, default=default_report)
    return parser.parse_args(arguments)


def _handle_profile_termination(_signum: int, _frame: FrameType | None) -> None:
    """Turn runner cancellation into the profile's cleanup path before exit."""
    raise KeyboardInterrupt(_INTERRUPTED)


def main(arguments: list[str] | None = None) -> int:
    """Run the requested profile and write a structured result for the checked source."""
    parsed = _parse_arguments(sys.argv[1:] if arguments is None else arguments)
    selected_profile = Profile(parsed.profile)
    previous_termination_handler = signal.signal(signal.SIGTERM, _handle_profile_termination)
    try:
        report = run_profile(
            selected_profile,
            source_root=parsed.root,
            source_revision=parsed.source_revision,
            source_tree=parsed.source_tree,
        )
        write_report(report, parsed.report)
        return 0 if report.passed else 1
    finally:
        signal.signal(signal.SIGTERM, previous_termination_handler)


if __name__ == "__main__":
    raise SystemExit(main())
