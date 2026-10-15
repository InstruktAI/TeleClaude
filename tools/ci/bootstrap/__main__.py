"""Run the fresh-machine bootstrap proof in a disposable Tart macOS VM."""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import yaml

from tools.ci import release_host_guard
from tools.ci.release_host_guard import InstallerResult
from tools.ci.terminal import CommandResult, PersistentTerminal

from .probes import GUEST_TELEC_RELATIVE_PATH, ProbeFailure, run_role_and_identity_probes

_UTF8 = "utf-8"
_APPEND_MODE = "a"
_WRITE_MODE = "w"
_TART_BINARY = "tart"
_GIT_BINARY = "git"
_MAKE_BINARY = "make"
_ENV_BINARY = "/usr/bin/env"
_TRUE_BINARY = "/usr/bin/true"
_PRINTENV_BINARY = "/usr/bin/printenv"
_BASH_BINARY = "/bin/bash"
_TART_EXEC_COMMAND = "exec"
_TART_RUN_COMMAND = "run"
_TART_CLONE_COMMAND = "clone"
_TART_STOP_COMMAND = "stop"
_TART_DELETE_COMMAND = "delete"
_TART_SET_COMMAND = "set"
_TART_VERSION_OPTION = "--version"
_TART_NO_GRAPHICS_OPTION = "--no-graphics"
_TART_DIRECTORY_OPTION = "--dir"
_TART_INPUT_OPTION = "-i"
_TART_TERMINAL_OPTION = "-t"
_BASH_NO_PROFILE_OPTION = "--noprofile"
_BASH_NO_RC_OPTION = "--norc"
_INTERACTIVE_OPTION = "-i"
_GIT_REV_PARSE_COMMAND = "rev-parse"
_GIT_VERIFY_OPTION = "--verify"
_GIT_ROOT_OPTION = "--show-toplevel"
_GIT_BUNDLE_COMMAND = "bundle"
_GIT_BUNDLE_CREATE_COMMAND = "create"
_GIT_CLONE_COMMAND = "clone"
_GIT_NO_CHECKOUT_OPTION = "--no-checkout"
_GIT_CHANGE_DIRECTORY_OPTION = "-C"
_GIT_CHECKOUT_COMMAND = "checkout"
_GIT_DETACH_OPTION = "--detach"
_GIT_HEAD_COMMIT_REF = "HEAD^{commit}"
_GIT_HEAD_REF = "HEAD"
_GIT_MAIN_REF = "main"
_MAKE_CHANGE_DIRECTORY_OPTION = "-C"
_INSTALL_TARGET = "install"
_START_TARGET = "start"
_STATUS_TARGET = "status"
_TEST_BINARY = "/bin/test"
_MKDIR_BINARY = "/bin/mkdir"
_SHASUM_BINARY = "/usr/bin/shasum"
_TEST_FILE_OPTION = "-f"
_MKDIR_PARENTS_OPTION = "-p"
_SHA256_OPTION = "-a"
_SHA256_VALUE = "256"
_HOME_ENVIRONMENT_VARIABLE = "HOME"
_ENVIRONMENT_ASSIGNMENT_FORMAT = "{key}={value}"
_FILENAME_DASH = "-"
_OUTPUT_SUFFIX = ".txt"
_VM_PREFIX_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
_ERROR_REPLACE_MODE = "replace"
_RUN_DIRECTORY_FORMAT = "{prefix}{suffix}"
_CLEANUP_DETAIL_FORMAT = "{stop_output} {cleanup_detail}"
_GUEST_READINESS_DETAIL_FORMAT = "{detail} {output}"
_OUTPUT_FILENAME_FORMAT = "{name}{suffix}"
_EXIT_COMMAND = "exit"
_SEED_DIRECTORY = "seed"
_GUEST_HOME_PREFIX = "/Users/"
_CHECKOUT_FOLDER = "Workspace/InstruktAI/TeleClaude"
_GLOBAL_CONFIG_RELATIVE_PATH = Path(".teleclaude") / "teleclaude.yml"
_PROJECT_ENV_FILENAME = ".env"
_SETTLED_FILE_COUNT = 2
_SETTLED_FILE_SNAPSHOT_FAILED = "Could not fingerprint the global registry and project environment file."
_SETTLED_FILES_CHANGED = "The repeat install changed the people registry or project environment file."
_PROJECT_LOG_ARGUMENT = "teleclaude"
_LOG_LOOKBACK_ARGUMENT = "--since"
_COLLECTED_LOG_FILENAME = "collected-teleclaude-logs.txt"
_AUTH_GROUP = "auth"
_AUTH_LOGIN_COMMAND = "login"
_VERSION_COMMAND = "version"
_DOCS_GROUP = "docs"
_DOCS_GET_COMMAND = "get"
_CONFIG_GROUP = "config"
_CONFIG_VALIDATE_COMMAND = "validate"
_STATUS_OUTPUT_DIRECTORY = "prepare host output directory"
_STATUS_TART_VERSION = "Tart version requirement"
_STATUS_REPOSITORY_ROOT = "resolve current checkout"
_STATUS_BUNDLE = "create repository Git bundle"
_STATUS_VM_CLONE = "clone disposable macOS VM"
_STATUS_VM_START = "start disposable macOS VM"
_STATUS_GUEST_READY = "wait for Tart guest agent"
_STATUS_GUEST_HOME = "resolve VM user home"
_STATUS_SHARED_BUNDLE = "read repository bundle through the guest share"
_STATUS_CHECKOUT_PARENT = "create canonical guest checkout parent"
_STATUS_BUNDLE_CLONE = "clone repository bundle into the guest"
_STATUS_BUNDLE_CHECKOUT = "select bundled checkout commit"
_STATUS_SETTLED_FILES_SNAPSHOT = "fingerprint the people registry and project environment"
_STEP_RESULT_DETAIL = "command exited with code {exit_code}"
_LOGS_RELATIVE_PATH = Path(".local") / "bin" / "instrukt-ai-logs"
_GUEST_SHARED_FILES_ROOT = Path("/Volumes/My Shared Files")
_BUNDLE_FILENAME = "repository.bundle"
_RUN_DIRECTORY_PREFIX = "run-"
_DEFAULT_OUTPUT_DIRECTORY = "teleclaude-bootstrap"
_MINIMUM_TART_VERSION = (2, 38, 0)
_MINIMUM_TART_VERSION_LABEL = "2.38"
_VERSION_PATTERN = re.compile(r"\b(\d+)\.(\d+)(?:\.(\d+))?\b")
_ANSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_UNSAFE_FILENAME = re.compile(r"[^a-z0-9_.-]+")
_EMPTY_VALUE = ""
_NEWLINE = "\n"
_STEP_LOG_FILENAME = "steps.log"
_VM_RUN_LOG_FILENAME = "tart-run.log"
_OUTPUT_DIRECTORY_ARG = "--output-dir"
_BASE_IMAGE_ARG = "--base-image"
_VM_NAME_ARGUMENT = "--vm-name"
_VM_CPU_ARGUMENT = "--vm-cpu"
_VM_MEMORY_ARGUMENT = "--vm-memory-mib"
_RUN_ID_ENV = "GITHUB_RUN_ID"
_RUN_ATTEMPT_ENV = "GITHUB_RUN_ATTEMPT"
_SUBPROCESS_FAILED = "The release host guard refused the proof lifecycle operation."
_TART_CPU_OPTION = "--cpu"
_TART_MEMORY_OPTION = "--memory"
_STATUS_ADMISSION = "release host admission and proof ownership"
_OUTPUT_DIRECTORY_ARGUMENT = _OUTPUT_DIRECTORY_ARG
_BASE_IMAGE_ARGUMENT = _BASE_IMAGE_ARG
_OWNER_SEED_FILENAME = "owner.yaml"
_OWNER_NAME_KEY = "name"
_OWNER_EMAIL_KEY = "email"
_OWNER_NAME_ENV = "TELECLAUDE_OWNER_NAME"
_OWNER_EMAIL_ENV = "TELECLAUDE_OWNER_EMAIL"
_GUEST_READINESS_TIMEOUT_SECONDS = 900
_GUEST_READINESS_RETRY_TIMEOUT_SECONDS = 8
_GUEST_READINESS_POLL_SECONDS = 3
_HOST_COMMAND_TIMEOUT_SECONDS = 900
_VM_CLONE_TIMEOUT_SECONDS = 1200
_INSTALL_TIMEOUT_SECONDS = 3600
_DAEMON_COMMAND_TIMEOUT_SECONDS = 180
_TERMINAL_COMMAND_TIMEOUT_SECONDS = 120
_LOG_COLLECTION_TIMEOUT_SECONDS = 180
_CLEANUP_TIMEOUT_SECONDS = 120
_LOG_LOOKBACK = "6h"
_TIMEOUT_EXIT_CODE = 124
_TART_NOT_FOUND = "Tart is unavailable on this host."
_TART_VERSION_UNREADABLE = "Could not read the Tart CLI version."
_TART_VERSION_TOO_OLD = "Tart {version} is below the required minimum {minimum}."
_OUTPUT_DIRECTORY_FAILED = "Could not prepare the harness output directory: {error}"
_REPOSITORY_ROOT_FAILED = "Could not resolve this checkout's Git root."
_BUNDLE_CREATE_FAILED = "Could not create the repository bundle: {error}"
_VM_NAME_PREFIX_INVALID = "VM name prefix may contain only letters, digits, hyphens, and underscores."
_VM_RUN_FAILED = "Tart exited before the guest VM became ready."
_GUEST_NOT_READY = "Tart guest agent did not become ready before the startup deadline."
_GUEST_HOME_FAILED = "Could not resolve the guest home directory."
_OWNER_SEED_INVALID = "Owner seed must contain non-empty name and email fields."
_OUTPUT_CAPTURE_FAILED = "Could not save command output: {error}"
_STEP_PASSED = "[PASS] {name}"
_STEP_FAILED = "[FAIL] {name}: {detail}"
_STEP_INFORMATION = "[INFO] {name}: {detail}"
_STATUS_INSTALL = "unattended install with owner seed"
_STATUS_START = "make start"
_STATUS_HEALTH = "make status health"
_HEALTHY_STATUS_TOKEN = "HEALTHY"
_STATUS_LOGIN = "seeded administrator terminal login"
_STATUS_VERSION = "telec version"
_STATUS_DOCS = "published documentation read"
_STATUS_CONFIG = "seeded administrator config validation"
_STATUS_PROBES = "role and identity probes"
_STATUS_SETTLED_FILES = "first repeat install preserves the roster and environment"
_STATUS_RESTART = "VM restart"
_STATUS_RESTART_INSTALL = "post-restart unattended install"
_STATUS_POST_RESTART_FILES = "post-restart install preserves the roster and environment"
_STATUS_LOGS = "install and daemon log collection"
_STATUS_CLEANUP = "VM stop and delete"
_DOCS_PROBE_ID = "general/principle/grounding"
_DOCS_RETURNED_ID_LINE = "id: {snippet_id}"
_REPORT_DIRECTORY_LINE = "Harness evidence written to {path}"
_REPOSITORY_ROOT_STEP = _STATUS_REPOSITORY_ROOT
_BUNDLE_STEP = _STATUS_BUNDLE
_STATUS_REPEAT_INSTALL = "repeat unattended install with a populated roster"
_EXIT_DETAIL_FORMAT = "exit={actual}, expected={expected}"
_EXPECTED_TEXT_DETAIL_FORMAT = "{detail}, expected output did not include {expected!r}"
_TART_VERSION_LABEL = _STATUS_TART_VERSION
_VM_CLONE_STEP = _STATUS_VM_CLONE
_VM_START_STEP = _STATUS_VM_START
_GUEST_READY_STEP = _STATUS_GUEST_READY
_GUEST_HOME_STEP = _STATUS_GUEST_HOME
_SHARED_BUNDLE_STEP = _STATUS_SHARED_BUNDLE
_CHECKOUT_PARENT_STEP = _STATUS_CHECKOUT_PARENT
_BUNDLE_CLONE_STEP = _STATUS_BUNDLE_CLONE
_BUNDLE_CHECKOUT_STEP = _STATUS_BUNDLE_CHECKOUT
_SETTLED_FILES_SNAPSHOT_STEP = _STATUS_SETTLED_FILES_SNAPSHOT


class HarnessFailure(RuntimeError):
    """A required bootstrap proof step failed or exceeded its time bound."""


@dataclass(frozen=True)
class OwnerSeed:
    """Validated owner seed used only by the disposable VM."""

    name: str
    email: str


def _version_tuple(output: str) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.search(output)
    if match is None:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def _load_owner_seed() -> OwnerSeed:
    seed_path = Path(__file__).resolve().parent / _SEED_DIRECTORY / _OWNER_SEED_FILENAME
    raw: object = yaml.safe_load(seed_path.read_text(encoding=_UTF8))
    if not isinstance(raw, dict):
        raise HarnessFailure(_OWNER_SEED_INVALID)
    name = raw.get(_OWNER_NAME_KEY)
    email = raw.get(_OWNER_EMAIL_KEY)
    if not isinstance(name, str) or not name.strip() or not isinstance(email, str) or not email.strip():
        raise HarnessFailure(_OWNER_SEED_INVALID)
    return OwnerSeed(name=name.strip(), email=email.strip())


class GuestTerminal(PersistentTerminal):
    """Keep one Tart guest login bound to one real guest terminal session."""

    def __init__(self, tart_path: str, vm_name: str, timeout_seconds: int) -> None:
        super().__init__(
            [
                tart_path,
                _TART_EXEC_COMMAND,
                _TART_INPUT_OPTION,
                _TART_TERMINAL_OPTION,
                vm_name,
                _BASH_BINARY,
                _BASH_NO_PROFILE_OPTION,
                _BASH_NO_RC_OPTION,
                _INTERACTIVE_OPTION,
            ],
            environment=os.environ,
            timeout_seconds=timeout_seconds,
        )


class BootstrapHarness:
    """Drive the install sequence and preserve a bounded evidence bundle."""

    def __init__(self, base_image: str, vm_name: str, vm_cpu: int, vm_memory_mib: int, output_root: Path) -> None:
        if _VM_PREFIX_PATTERN.fullmatch(vm_name) is None:
            raise HarnessFailure(_VM_NAME_PREFIX_INVALID)
        self._base_image = base_image
        self._vm_name = vm_name
        self._vm_cpu = vm_cpu
        self._vm_memory_mib = vm_memory_mib
        self._output_root = output_root.expanduser().resolve()
        run_directory_name = _RUN_DIRECTORY_FORMAT.format(prefix=_RUN_DIRECTORY_PREFIX, suffix=uuid.uuid4().hex)
        self._run_directory = self._output_root / run_directory_name
        self._step_log = self._run_directory / _STEP_LOG_FILENAME
        self._vm_run_log = self._run_directory / _VM_RUN_LOG_FILENAME
        self._project_root = Path.cwd().resolve()
        self._bundle_path = self._run_directory / _BUNDLE_FILENAME
        self._head_commit = _EMPTY_VALUE
        self._guest_home = _EMPTY_VALUE
        self._guest_project_root = _EMPTY_VALUE
        self._guest_bundle_path = _EMPTY_VALUE
        self._tart_path: str | None = None
        self._vm_process: subprocess.Popen[bytes] | None = None
        self._vm_created = False
        self._proof_started = False
        self._step_number = 0

    def run(self) -> None:
        self._step(_STATUS_OUTPUT_DIRECTORY, self._prepare_output)
        self._guard(lambda: release_host_guard.admit(self._vm_cpu, self._vm_memory_mib))
        self._verify_tart()
        self._resolve_repository()
        self._create_bundle()
        self._begin_proof()
        self._clone_vm()
        self._mark_proof_created()
        self._start_vm()
        self._wait_for_guest()
        self._prepare_guest_checkout()
        owner_seed = _load_owner_seed()
        self._install(owner_seed)
        self._start_and_check_health()
        self._admin_readiness_probes(owner_seed)
        self._role_and_identity_probes(owner_seed)
        self._repeat_install(owner_seed)
        self._restart_vm()
        self._install_after_restart(owner_seed)
        self._collect_logs()

    @property
    def run_directory(self) -> Path:
        """Return this run's host evidence directory."""
        return self._run_directory

    @property
    def guest_home(self) -> str:
        """Return the guest user's home directory, resolved once the guest is ready."""
        return self._guest_home

    @property
    def guest_project_root(self) -> str:
        """Return the guest's canonical checkout path."""
        return self._guest_project_root

    def cleanup(self, installer_succeeded: bool) -> bool:
        cleanup_succeeded = True
        guard_succeeded = True
        result = InstallerResult.SUCCESS if installer_succeeded else InstallerResult.FAILURE
        if self._proof_started:
            try:
                self._guard(lambda: release_host_guard.record_installer_outcome(self._vm_name, result))
            except HarnessFailure:
                guard_succeeded = False
        if self._tart_path is not None and self._vm_created:
            stop = self._capture([self._tart_path, _TART_STOP_COMMAND, self._vm_name], _CLEANUP_TIMEOUT_SECONDS)
            self._stop_tart_process()
            delete = self._capture([self._tart_path, _TART_DELETE_COMMAND, self._vm_name], _CLEANUP_TIMEOUT_SECONDS)
            detail = delete.output.strip()
            cleanup_succeeded = delete.returncode == 0
            if not cleanup_succeeded and stop.returncode != 0:
                detail = _CLEANUP_DETAIL_FORMAT.format(
                    stop_output=stop.output.strip(),
                    cleanup_detail=_STEP_INFORMATION.format(name=_STATUS_CLEANUP, detail=detail),
                )
            self._record_verdict(_STATUS_CLEANUP, cleanup_succeeded, detail)
            self._vm_created = not cleanup_succeeded
        if self._proof_started:
            try:
                if cleanup_succeeded:
                    self._guard(lambda: release_host_guard.settle_proof(self._vm_name, result))
                else:
                    self._guard(lambda: release_host_guard.record_cleanup_failure(self._vm_name))
            except HarnessFailure:
                guard_succeeded = False
        return cleanup_succeeded and guard_succeeded

    def run_vm_command(
        self,
        name: str,
        command: Sequence[str],
        timeout_seconds: int = _HOST_COMMAND_TIMEOUT_SECONDS,
        *,
        environment: Mapping[str, str] | None = None,
        save_output: bool = True,
        expected_text: str | None = None,
    ) -> str:
        assert self._tart_path is not None
        argv = [self._tart_path, _TART_EXEC_COMMAND, self._vm_name, *command]
        if environment:
            env_args = [
                _ENVIRONMENT_ASSIGNMENT_FORMAT.format(key=key, value=value) for key, value in environment.items()
            ]
            argv = [self._tart_path, _TART_EXEC_COMMAND, self._vm_name, _ENV_BINARY, *env_args, *command]
        return self._run_step(
            name,
            argv,
            timeout_seconds,
            save_output=save_output,
            expected_text=expected_text,
        )

    def record_terminal_result(
        self,
        name: str,
        result: CommandResult,
        *,
        expected_returncode: int = 0,
        expected_text: str | None = None,
    ) -> None:
        output = _ANSI_SEQUENCE.sub(_EMPTY_VALUE, result.output)
        contains_text = expected_text is None or expected_text.lower() in output.lower()
        passed = result.returncode == expected_returncode and contains_text
        detail = _EMPTY_VALUE
        if not passed:
            detail = _EXIT_DETAIL_FORMAT.format(actual=result.returncode, expected=expected_returncode)
            if expected_text is not None and not contains_text:
                detail = _EXPECTED_TEXT_DETAIL_FORMAT.format(detail=detail, expected=expected_text)
        self._save_output(name, result.output)
        self._record_verdict(name, passed, detail)
        if not passed:
            raise HarnessFailure(detail)

    def record_probe(self, name: str, passed: bool, detail: str = _EMPTY_VALUE) -> None:
        self._record_verdict(name, passed, detail)
        if not passed:
            raise HarnessFailure(detail)

    def record_information(self, name: str, detail: str) -> None:
        """Report a capability line that is evidence only and never changes the verdict."""
        line = _STEP_INFORMATION.format(name=name, detail=detail)
        print(line, flush=True)
        with self._step_log.open(_APPEND_MODE, encoding=_UTF8) as report:
            report.write(line + _NEWLINE)

    def _prepare_output(self) -> None:
        self._run_directory.mkdir(parents=True, exist_ok=False)
        self._step_log.write_text(_EMPTY_VALUE, encoding=_UTF8)

    def _step(self, name: str, action: Callable[[], None]) -> None:
        try:
            action()
        except OSError as exc:
            detail = _OUTPUT_DIRECTORY_FAILED.format(error=exc)
            print(_STEP_FAILED.format(name=name, detail=detail), flush=True)
            raise HarnessFailure(detail) from exc
        self._record_verdict(name, True)

    def _verify_tart(self) -> None:
        tart_path = shutil.which(_TART_BINARY)
        if tart_path is None:
            self._record_verdict(_TART_BINARY, False, _TART_NOT_FOUND)
            raise HarnessFailure(_TART_NOT_FOUND)
        self._tart_path = tart_path
        version = self._capture([tart_path, _TART_VERSION_OPTION], _HOST_COMMAND_TIMEOUT_SECONDS)
        parsed = _version_tuple(version.output)
        if parsed is None:
            self._record_verdict(_TART_VERSION_LABEL, False, _TART_VERSION_UNREADABLE)
            raise HarnessFailure(_TART_VERSION_UNREADABLE)
        if parsed < _MINIMUM_TART_VERSION:
            detail = _TART_VERSION_TOO_OLD.format(version=version.output.strip(), minimum=_MINIMUM_TART_VERSION_LABEL)
            self._record_verdict(_TART_VERSION_LABEL, False, detail)
            raise HarnessFailure(detail)
        self._record_verdict(_TART_VERSION_LABEL, True, version.output.strip())

    def _resolve_repository(self) -> None:
        root = self._capture(
            [_GIT_BINARY, _GIT_REV_PARSE_COMMAND, _GIT_ROOT_OPTION],
            _HOST_COMMAND_TIMEOUT_SECONDS,
            cwd=self._project_root,
        )
        head = self._capture(
            [_GIT_BINARY, _GIT_REV_PARSE_COMMAND, _GIT_VERIFY_OPTION, _GIT_HEAD_COMMIT_REF],
            _HOST_COMMAND_TIMEOUT_SECONDS,
            cwd=self._project_root,
        )
        if root.returncode != 0 or head.returncode != 0:
            self._record_verdict(_REPOSITORY_ROOT_STEP, False, _REPOSITORY_ROOT_FAILED)
            raise HarnessFailure(_REPOSITORY_ROOT_FAILED)
        self._project_root = Path(root.output.strip()).resolve()
        self._head_commit = head.output.strip()
        self._record_verdict(_REPOSITORY_ROOT_STEP, True, self._head_commit)

    def _create_bundle(self) -> None:
        # Git bundle is a Git-specific transfer format with no Python-native equivalent.
        result = self._capture(
            [
                _GIT_BINARY,
                _GIT_BUNDLE_COMMAND,
                _GIT_BUNDLE_CREATE_COMMAND,
                str(self._bundle_path),
                _GIT_HEAD_REF,
                _GIT_MAIN_REF,
            ],
            _HOST_COMMAND_TIMEOUT_SECONDS,
            cwd=self._project_root,
        )
        if result.returncode != 0:
            detail = _BUNDLE_CREATE_FAILED.format(error=result.output.strip())
            self._record_verdict(_BUNDLE_STEP, False, detail)
            raise HarnessFailure(detail)
        self._record_verdict(_BUNDLE_STEP, True)

    def _clone_vm(self) -> None:
        assert self._tart_path is not None
        self._vm_created = True
        self._run_step(
            _VM_CLONE_STEP,
            [self._tart_path, _TART_CLONE_COMMAND, self._base_image, self._vm_name],
            _VM_CLONE_TIMEOUT_SECONDS,
        )
        self._run_step(
            _TART_SET_COMMAND,
            [
                self._tart_path,
                _TART_SET_COMMAND,
                self._vm_name,
                _TART_CPU_OPTION,
                str(self._vm_cpu),
                _TART_MEMORY_OPTION,
                str(self._vm_memory_mib),
            ],
            _HOST_COMMAND_TIMEOUT_SECONDS,
        )

    def _begin_proof(self) -> None:
        run_id = os.environ.get(_RUN_ID_ENV, _EMPTY_VALUE)
        run_attempt = os.environ.get(_RUN_ATTEMPT_ENV, _EMPTY_VALUE)
        if not run_id or not run_attempt:
            raise HarnessFailure(_SUBPROCESS_FAILED)
        self._guard(
            lambda: release_host_guard.begin_proof(
                run_id,
                run_attempt,
                self._vm_name,
                self._base_image,
                self._vm_cpu,
                self._vm_memory_mib,
            )
        )
        self._proof_started = True

    def _mark_proof_created(self) -> None:
        self._guard(lambda: release_host_guard.mark_created(self._vm_name))

    def _guard(self, action: Callable[[], None]) -> None:
        try:
            with redirect_stdout(io.StringIO()):
                action()
        except (OSError, RuntimeError, ValueError) as exc:
            detail = str(exc) or _SUBPROCESS_FAILED
            self._record_verdict(_STATUS_ADMISSION, False, detail)
            raise HarnessFailure(detail) from exc
        self._record_verdict(_STATUS_ADMISSION, True)

    def _start_vm(self) -> None:
        assert self._tart_path is not None
        # Tart is the VM lifecycle API; keep its long-lived run process separate from bounded commands.
        with self._vm_run_log.open(_WRITE_MODE, encoding=_UTF8) as log_file:
            self._vm_process = subprocess.Popen(
                [
                    self._tart_path,
                    _TART_RUN_COMMAND,
                    _TART_NO_GRAPHICS_OPTION,
                    _TART_DIRECTORY_OPTION,
                    str(self._run_directory),
                    self._vm_name,
                ],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        if self._vm_process.poll() is not None:
            detail = _VM_RUN_FAILED
            self._record_verdict(_VM_START_STEP, False, detail)
            raise HarnessFailure(detail)
        self._record_verdict(_VM_START_STEP, True)

    def _wait_for_guest(self) -> None:
        assert self._tart_path is not None
        deadline = time.monotonic() + _GUEST_READINESS_TIMEOUT_SECONDS
        last_output = _EMPTY_VALUE
        while time.monotonic() < deadline:
            if self._vm_process is not None and self._vm_process.poll() is not None:
                break
            result = self._capture(
                [self._tart_path, _TART_EXEC_COMMAND, self._vm_name, _TRUE_BINARY],
                _GUEST_READINESS_RETRY_TIMEOUT_SECONDS,
            )
            if result.returncode == 0:
                self._record_verdict(_GUEST_READY_STEP, True)
                return
            last_output = result.output
            time.sleep(_GUEST_READINESS_POLL_SECONDS)
        detail = _GUEST_NOT_READY
        if last_output.strip():
            detail = _GUEST_READINESS_DETAIL_FORMAT.format(detail=detail, output=last_output.strip())
        self._record_verdict(_GUEST_READY_STEP, False, detail)
        raise HarnessFailure(detail)

    def _prepare_guest_checkout(self) -> None:
        self._guest_bundle_path = str(_GUEST_SHARED_FILES_ROOT / _BUNDLE_FILENAME)
        home = self.run_vm_command(
            _GUEST_HOME_STEP,
            [_PRINTENV_BINARY, _HOME_ENVIRONMENT_VARIABLE],
            save_output=False,
        ).strip()
        if not home.startswith(_GUEST_HOME_PREFIX):
            self._record_verdict(_GUEST_HOME_STEP, False, _GUEST_HOME_FAILED)
            raise HarnessFailure(_GUEST_HOME_FAILED)
        self._guest_home = home
        self._guest_project_root = str(Path(home) / _CHECKOUT_FOLDER)
        self.run_vm_command(_SHARED_BUNDLE_STEP, [_TEST_BINARY, _TEST_FILE_OPTION, self._guest_bundle_path])
        self.run_vm_command(
            _CHECKOUT_PARENT_STEP,
            [_MKDIR_BINARY, _MKDIR_PARENTS_OPTION, str(Path(self._guest_project_root).parent)],
        )
        self.run_vm_command(
            _BUNDLE_CLONE_STEP,
            [
                _GIT_BINARY,
                _GIT_CLONE_COMMAND,
                _GIT_NO_CHECKOUT_OPTION,
                self._guest_bundle_path,
                self._guest_project_root,
            ],
            _HOST_COMMAND_TIMEOUT_SECONDS,
        )
        self.run_vm_command(
            _BUNDLE_CHECKOUT_STEP,
            [
                _GIT_BINARY,
                _GIT_CHANGE_DIRECTORY_OPTION,
                self._guest_project_root,
                _GIT_CHECKOUT_COMMAND,
                _GIT_DETACH_OPTION,
                self._head_commit,
            ],
            _HOST_COMMAND_TIMEOUT_SECONDS,
        )

    def _install(self, owner_seed: OwnerSeed, step_name: str = _STATUS_INSTALL) -> None:
        assert self._guest_project_root
        self.run_vm_command(
            step_name,
            [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, self._guest_project_root, _INSTALL_TARGET],
            _INSTALL_TIMEOUT_SECONDS,
            environment={
                _OWNER_NAME_ENV: owner_seed.name,
                _OWNER_EMAIL_ENV: owner_seed.email,
            },
        )

    def _start_and_check_health(self) -> None:
        assert self._guest_project_root
        self.run_vm_command(
            _STATUS_START,
            [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, self._guest_project_root, _START_TARGET],
            _DAEMON_COMMAND_TIMEOUT_SECONDS,
        )
        self.run_vm_command(
            _STATUS_HEALTH,
            [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, self._guest_project_root, _STATUS_TARGET],
            _DAEMON_COMMAND_TIMEOUT_SECONDS,
            expected_text=_HEALTHY_STATUS_TOKEN,
        )

    def _admin_readiness_probes(self, owner_seed: OwnerSeed) -> None:
        assert self._guest_project_root
        telec = str(Path(self._guest_home) / GUEST_TELEC_RELATIVE_PATH)
        with self.terminal() as terminal:
            login = terminal.run([telec, _AUTH_GROUP, _AUTH_LOGIN_COMMAND, owner_seed.email])
            self.record_terminal_result(_STATUS_LOGIN, login)
            version = terminal.run([telec, _VERSION_COMMAND])
            self.record_terminal_result(_STATUS_VERSION, version)
            docs = terminal.run([telec, _DOCS_GROUP, _DOCS_GET_COMMAND, _DOCS_PROBE_ID])
            self.record_terminal_result(
                _STATUS_DOCS,
                docs,
                expected_text=_DOCS_RETURNED_ID_LINE.format(snippet_id=_DOCS_PROBE_ID),
            )
            validation = terminal.run([telec, _CONFIG_GROUP, _CONFIG_VALIDATE_COMMAND])
            self.record_terminal_result(_STATUS_CONFIG, validation)

    def _role_and_identity_probes(self, owner_seed: OwnerSeed) -> None:
        try:
            run_role_and_identity_probes(self, owner_seed.email)
        except ProbeFailure as exc:
            self._record_verdict(_STATUS_PROBES, False, str(exc))
            raise HarnessFailure(str(exc)) from exc

    def terminal(self, timeout_seconds: int = _TERMINAL_COMMAND_TIMEOUT_SECONDS) -> GuestTerminal:
        assert self._tart_path is not None
        return GuestTerminal(self._tart_path, self._vm_name, timeout_seconds)

    def snapshot_settled_files(self) -> tuple[str, ...]:
        assert self._guest_project_root
        global_config = str(Path(self._guest_home) / _GLOBAL_CONFIG_RELATIVE_PATH)
        environment_file = str(Path(self._guest_project_root) / _PROJECT_ENV_FILENAME)
        output = self.run_vm_command(
            _SETTLED_FILES_SNAPSHOT_STEP,
            [_SHASUM_BINARY, _SHA256_OPTION, _SHA256_VALUE, global_config, environment_file],
            save_output=False,
        )
        digests = tuple(line.split()[0] for line in output.splitlines() if line.split())
        if len(digests) != _SETTLED_FILE_COUNT:
            raise HarnessFailure(_SETTLED_FILE_SNAPSHOT_FAILED)
        return digests

    def _repeat_install(self, owner_seed: OwnerSeed) -> None:
        before = self.snapshot_settled_files()
        self._install(owner_seed, _STATUS_REPEAT_INSTALL)
        after = self.snapshot_settled_files()
        self._record_verdict(_STATUS_SETTLED_FILES, before == after)
        if before != after:
            raise HarnessFailure(_SETTLED_FILES_CHANGED)

    def _restart_vm(self) -> None:
        assert self._tart_path is not None
        result = self._capture([self._tart_path, _TART_STOP_COMMAND, self._vm_name], _CLEANUP_TIMEOUT_SECONDS)
        if result.returncode != 0:
            self._record_verdict(_STATUS_RESTART, False, result.output.strip())
            raise HarnessFailure(_STATUS_RESTART)
        self._stop_tart_process()
        self._start_vm()
        self._wait_for_guest()
        self._record_verdict(_STATUS_RESTART, True)

    def _install_after_restart(self, owner_seed: OwnerSeed) -> None:
        before = self.snapshot_settled_files()
        self._install(owner_seed, _STATUS_RESTART_INSTALL)
        after = self.snapshot_settled_files()
        self._record_verdict(_STATUS_POST_RESTART_FILES, before == after)
        if before != after:
            raise HarnessFailure(_SETTLED_FILES_CHANGED)

    def _collect_logs(self) -> None:
        assert self._guest_home
        log_cli = str(Path(self._guest_home) / _LOGS_RELATIVE_PATH)
        output = self.run_vm_command(
            _STATUS_LOGS,
            [log_cli, _PROJECT_LOG_ARGUMENT, _LOG_LOOKBACK_ARGUMENT, _LOG_LOOKBACK],
            _LOG_COLLECTION_TIMEOUT_SECONDS,
            save_output=False,
        )
        self._save_output(_COLLECTED_LOG_FILENAME, output)

    def _capture(
        self,
        argv: Sequence[str],
        timeout_seconds: int,
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        # Tart, Git, make and VM guest commands are external tool contracts without Python-native APIs.
        try:
            result = subprocess.run(
                list(argv),
                cwd=cwd,
                env=None if environment is None else {**os.environ, **environment},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=_UTF8,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = (
                exc.stdout.decode(_UTF8, errors=_ERROR_REPLACE_MODE)
                if isinstance(exc.stdout, bytes)
                else exc.stdout or _EMPTY_VALUE
            )
            return CommandResult(returncode=_TIMEOUT_EXIT_CODE, output=output)
        except OSError as exc:
            return CommandResult(returncode=_TIMEOUT_EXIT_CODE, output=str(exc))
        return CommandResult(returncode=result.returncode, output=result.stdout)

    def _run_step(
        self,
        name: str,
        argv: Sequence[str],
        timeout_seconds: int,
        *,
        environment: Mapping[str, str] | None = None,
        save_output: bool = True,
        expected_text: str | None = None,
    ) -> str:
        result = self._capture(argv, timeout_seconds, cwd=self._project_root, environment=environment)
        if save_output:
            self._save_output(name, result.output)
        if result.returncode != 0 or (expected_text is not None and expected_text not in result.output):
            detail = _STEP_RESULT_DETAIL.format(exit_code=result.returncode)
            if expected_text is not None and expected_text not in result.output:
                detail = _EXPECTED_TEXT_DETAIL_FORMAT.format(detail=detail, expected=expected_text)
            self._record_verdict(name, False, detail)
            raise HarnessFailure(detail)
        self._record_verdict(name, True)
        return result.output

    def _record_verdict(self, name: str, passed: bool, detail: str = _EMPTY_VALUE) -> None:
        self._step_number += 1
        line = _STEP_PASSED.format(name=name) if passed else _STEP_FAILED.format(name=name, detail=detail)
        print(line, flush=True)
        with self._step_log.open(_APPEND_MODE, encoding=_UTF8) as report:
            report.write(line + _NEWLINE)

    def _save_output(self, name: str, output: str) -> None:
        safe_name = _UNSAFE_FILENAME.sub(_FILENAME_DASH, name.lower()).strip(_FILENAME_DASH)
        try:
            output_filename = _OUTPUT_FILENAME_FORMAT.format(name=safe_name, suffix=_OUTPUT_SUFFIX)
            (self._run_directory / output_filename).write_text(output, encoding=_UTF8)
        except OSError as exc:
            raise HarnessFailure(_OUTPUT_CAPTURE_FAILED.format(error=exc)) from exc

    def _stop_tart_process(self) -> None:
        process = self._vm_process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=_CLEANUP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        self._vm_process = None


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_BASE_IMAGE_ARGUMENT, required=True)
    parser.add_argument(_VM_NAME_ARGUMENT, required=True)
    parser.add_argument(_VM_CPU_ARGUMENT, type=int, required=True)
    parser.add_argument(_VM_MEMORY_ARGUMENT, type=int, required=True)
    default_output = Path(tempfile.gettempdir()) / _DEFAULT_OUTPUT_DIRECTORY
    parser.add_argument(_OUTPUT_DIRECTORY_ARGUMENT, type=Path, default=default_output)
    return parser


def main() -> int:
    args = _build_argument_parser().parse_args()
    harness = BootstrapHarness(args.base_image, args.vm_name, args.vm_cpu, args.vm_memory_mib, args.output_dir)
    exit_code = 1
    installer_succeeded = False
    try:
        harness.run()
        installer_succeeded = True
        exit_code = 0
    except HarnessFailure:
        exit_code = 1
    finally:
        try:
            if not harness.cleanup(installer_succeeded=installer_succeeded):
                exit_code = 1
        except HarnessFailure:
            exit_code = 1
    print(_REPORT_DIRECTORY_LINE.format(path=harness.run_directory))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
