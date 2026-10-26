"""Run the fresh-machine installer proof on a GitHub-hosted macOS runner."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.reconciliation.install_act import InstallStatus
from tools.ci.terminal import CommandResult, PersistentTerminal, TerminalFailure

from .probes import TELEC_RELATIVE_PATH, ProbeFailure, run_role_and_identity_probes

_UTF8 = "utf-8"
_APPEND_MODE = "a"
_GIT_BINARY = "git"
_MAKE_BINARY = "make"
_BASH_BINARY = "/bin/bash"
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
_START_TARGET = "start"
_STOP_TARGET = "stop"
_STATUS_TARGET = "status"
_OUTPUT_SUFFIX = ".txt"
_RUN_DIRECTORY_FORMAT = "{prefix}{suffix}"
_OUTPUT_FILENAME_FORMAT = "{name}{suffix}"
_FILENAME_DASH = "-"
_HOME_ENVIRONMENT_VARIABLE = "HOME"
_USER_ENVIRONMENT_VARIABLE = "USER"
_LOGNAME_ENVIRONMENT_VARIABLE = "LOGNAME"
_SHELL_ENVIRONMENT_VARIABLE = "SHELL"
_TMPDIR_ENVIRONMENT_VARIABLE = "TMPDIR"
_LANG_ENVIRONMENT_VARIABLE = "LANG"
_PATH_ENVIRONMENT_VARIABLE = "PATH"
_RUNNER_ENVIRONMENT_VARIABLE = "RUNNER_ENVIRONMENT"
_GITHUB_ACTIONS_VARIABLE = "GITHUB_ACTIONS"
_GITHUB_HOSTED = "github-hosted"
_TRUE = "true"
_DARWIN_PLATFORM = "darwin"
_PLATFORM_HOME_DIRECTORY = Path(".teleclaude")
_GLOBAL_CONFIG_FILENAME = "teleclaude.yml"
_OWNER_SEED_FILENAME = "owner.yaml"
_OWNER_NAME_KEY = "name"
_OWNER_EMAIL_KEY = "email"
_OWNER_NAME_ENV = "TELECLAUDE_OWNER_NAME"
_OWNER_EMAIL_ENV = "TELECLAUDE_OWNER_EMAIL"
_SEED_DIRECTORY = "seed"
_CHECKOUT_FOLDER = Path("Workspace") / "InstruktAI" / "TeleClaude"
_GLOBAL_CONFIG_RELATIVE_PATH = _PLATFORM_HOME_DIRECTORY / _GLOBAL_CONFIG_FILENAME
_MACHINE_ENV_RELATIVE_PATH = _PLATFORM_HOME_DIRECTORY / ".env"
_FILE_FINGERPRINT_FAILED = "Could not fingerprint {path}: {error}"
_DIRECTORY_CREATE_FAILED = "Could not create {path}: {error}"
_SETTLED_FILES_CHANGED = "The repeat install changed the people registry or machine environment file."
_PROJECT_LOG_ARGUMENT = "teleclaude"
_LOG_LOOKBACK_ARGUMENT = "--since"
_COLLECTED_LOG_FILENAME = "collected-teleclaude-logs.txt"
_LOGS_RELATIVE_PATH = Path(".local") / "bin" / "instrukt-ai-logs"
_BUNDLE_FILENAME = "repository.bundle"
_RUN_DIRECTORY_PREFIX = "run-"
_DEFAULT_OUTPUT_DIRECTORY = "teleclaude-bootstrap"
_ERROR_REPLACE_MODE = "replace"
_BINARY_READ_MODE = "rb"
_TIMEOUT_EXIT_CODE = 124
_OWNER_SEED_INVALID = "Owner seed must contain non-empty name and email fields."
_RUNNER_USER_MISSING = "The hosted runner did not declare its login user."
_HOSTED_RUNNER_REFUSED = (
    "The installer proof requires a fresh GitHub-hosted macOS runner with no installed TeleClaude state."
)
_OUTPUT_DIRECTORY_FAILED = "Could not prepare the harness output directory: {error}"
_REPOSITORY_ROOT_FAILED = "Could not resolve this checkout's Git root."
_BUNDLE_CREATE_FAILED = "Could not create the repository bundle: {error}"
_OUTPUT_CAPTURE_FAILED = "Could not save command output: {error}"
_STEP_RESULT_DETAIL = "command exited with code {exit_code}"
_EXPECTED_TEXT_DETAIL_FORMAT = "{detail}, expected output did not include {expected!r}"
_EXIT_DETAIL_FORMAT = "exit={actual}, expected={expected}"
_TERMINAL_FAILURE_DETAIL = "terminal failure: {reason}"
_STEP_PASSED = "[PASS] {name}"
_STEP_FAILED = "[FAIL] {name}: {detail}"
_STEP_INFORMATION = "[INFO] {name}: {detail}"
_REPORT_DIRECTORY_LINE = "Harness evidence written to {path}"
_STATUS_PRECONDITION = "fresh GitHub-hosted macOS runner precondition"
_STATUS_OUTPUT_DIRECTORY = "prepare runner output directory"
_STATUS_REPOSITORY_ROOT = "resolve current checkout"
_STATUS_BUNDLE = "create repository Git bundle"
_STATUS_CHECKOUT_PARENT = "create canonical runner checkout parent"
_STATUS_BUNDLE_CLONE = "clone repository bundle into canonical checkout"
_STATUS_BUNDLE_CHECKOUT = "select bundled candidate commit"
_STATUS_INSTALL = "unattended install with owner seed"
_INSTALL_ACT_STEP = "{name}: install act"
_ACTIVE_RELEASE_STEP = "{name}: resolve the installed release"
_CONVERGE_STEP = "{name}: converge from the installed release"
_STATUS_START = "make start"
_STATUS_HEALTH = "make status health"
_STATUS_LOGIN = "seeded administrator terminal login"
_STATUS_VERSION = "telec version"
_STATUS_DOCS = "published documentation read"
_STATUS_CONFIG = "seeded administrator config validation"
_STATUS_PROBES = "role and identity probes"
_STATUS_SETTLED_FILES_SNAPSHOT = "fingerprint the people registry and machine environment"
_STATUS_SETTLED_FILES = "first repeat install preserves the roster and machine environment"
_STATUS_REPEAT_INSTALL = "repeat unattended install with a populated roster"
_STATUS_RESTART = "installed services stop and start"
_STATUS_SERVICE_STOP = "make stop"
_STATUS_RESTART_INSTALL = "post-restart unattended install"
_STATUS_POST_RESTART_FILES = "post-restart install preserves the roster and machine environment"
_STATUS_LOGS = "install and daemon log collection"
_HEALTHY_STATUS_TOKEN = "HEALTHY"
_DOCS_PROBE_ID = "general/principle/grounding"
_DOCS_RETURNED_ID_LINE = "id: {snippet_id}"
_PYTHON_PATH_ENVIRONMENT_VARIABLE = "PYTHONPATH"
_PYTHON_ISOLATED_OPTION = "-P"
_PYTHON_MODULE_OPTION = "-m"
_PYTHON_COMMAND_OPTION = "-c"
_INSTALL_ACT_MODULE = "teleclaude.core.reconciliation.installation_move"
_INSTALL_ACT_BOOTSTRAP_VERB = "bootstrap"
_INSTALL_ACT_SOURCE_OPTION = "--source"
_INSTALL_ACT_REVISION_OPTION = "--revision"
_INSTALL_RESULT_LINE = "{status}: {revision}"
_ACTIVE_RELEASE_QUERY = (
    "from teleclaude.core.reconciliation.installation import InstallationLayout; "
    "print(InstallationLayout().active_release())"
)
_CONVERGENCE_INSTALLER = Path("bin") / "install.sh"
_UV_EXECUTABLE = "uv"
_UV_MISSING = "The hosted proof runner has no uv, which the installation act needs to build the release."
_ACTIVE_RELEASE_INVALID = "The installation reported no usable active release folder: {reported!r}"
_ACTIVE_RELEASE_UNRESOLVED = "The installed release is read before the install act resolved it."
_RUN_ENV_BASE = {
    _PATH_ENVIRONMENT_VARIABLE: "/usr/bin:/bin:/usr/sbin:/sbin",
    _LANG_ENVIRONMENT_VARIABLE: "en_US.UTF-8",
}
_PATH_HELPER_EXECUTABLE = "/usr/libexec/path_helper"
_PATH_HELPER_OPTION = "-s"
_PATH_HELPER_EXPORT = "export"
_PATH_HELPER_SEPARATOR = ";"
_PATH_ASSIGNMENT_PREFIX = f"{_PATH_ENVIRONMENT_VARIABLE}="
_PATH_HELPER_FAILED = "Could not construct the runner login PATH using path_helper."
_PATH_HELPER_OUTPUT_INVALID = "path_helper did not return a valid PATH assignment."
_HASH_CHUNK_SIZE = 1024 * 1024
_ANSI_SEQUENCE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_UNSAFE_FILENAME = re.compile(r"[^a-z0-9_.-]+")
_EMPTY_VALUE = ""
_NEWLINE = "\n"
_STEP_LOG_FILENAME = "steps.log"
_OUTPUT_DIRECTORY_ARGUMENT = "--output-dir"
_HOST_COMMAND_TIMEOUT_SECONDS = 900
_INSTALL_TIMEOUT_SECONDS = 3600
_DAEMON_COMMAND_TIMEOUT_SECONDS = 180
_TERMINAL_COMMAND_TIMEOUT_SECONDS = 120
_LOG_COLLECTION_TIMEOUT_SECONDS = 180
_LOG_LOOKBACK = "6h"
_PROJECTS_DIRECTORY = "bootstrap-probe-projects"
_NO_PROFILE_BASH = (_BASH_BINARY, _BASH_NO_PROFILE_OPTION, _BASH_NO_RC_OPTION, _INTERACTIVE_OPTION)


class TelecToken(StrEnum):
    """Closed set of TeleClaude CLI tokens used by the installer proof."""

    AUTH = "auth"
    LOGIN = "login"
    VERSION = "version"
    DOCS = "docs"
    GET = "get"
    CONFIG = "config"
    VALIDATE = "validate"


class HarnessFailure(RuntimeError):
    """A required bootstrap proof step failed or exceeded its time bound."""


@dataclass(frozen=True)
class OwnerSeed:
    """Validated owner seed used only by the runner installation."""

    name: str
    email: str


def _hosted_runner_refusal() -> str | None:
    """Return the reason this process is unsafe to run, before it performs any setup."""
    home_value = os.environ.get(_HOME_ENVIRONMENT_VARIABLE)
    if (
        os.environ.get(_GITHUB_ACTIONS_VARIABLE) != _TRUE
        or os.environ.get(_RUNNER_ENVIRONMENT_VARIABLE) != _GITHUB_HOSTED
        or sys.platform != _DARWIN_PLATFORM
        or not home_value
    ):
        return _HOSTED_RUNNER_REFUSED
    home = Path(home_value)
    canonical_checkout = home / _CHECKOUT_FOLDER
    platform_home = home / _PLATFORM_HOME_DIRECTORY
    socket_path = Path(API_SOCKET_PATH)
    occupied = (
        (platform_home.exists() or platform_home.is_symlink())
        or (socket_path.exists() or socket_path.is_symlink())
        or (canonical_checkout.exists() or canonical_checkout.is_symlink())
    )
    return _HOSTED_RUNNER_REFUSED if occupied else None


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


def _path_from_helper(output: str) -> str:
    """Read the PATH assignment emitted by macOS path_helper without evaluating shell text."""
    try:
        tokens = list(shlex.shlex(output, posix=True, punctuation_chars=_PATH_HELPER_SEPARATOR))
    except ValueError as exc:
        raise HarnessFailure(_PATH_HELPER_OUTPUT_INVALID) from exc
    expected_suffix = (
        _PATH_HELPER_SEPARATOR,
        _PATH_HELPER_EXPORT,
        _PATH_ENVIRONMENT_VARIABLE,
        _PATH_HELPER_SEPARATOR,
    )
    if len(tokens) != len(expected_suffix) + 1 or not tokens[0].startswith(_PATH_ASSIGNMENT_PREFIX):
        raise HarnessFailure(_PATH_HELPER_OUTPUT_INVALID)
    if tuple(tokens[1:]) != expected_suffix:
        raise HarnessFailure(_PATH_HELPER_OUTPUT_INVALID)
    path = tokens[0][len(_PATH_ASSIGNMENT_PREFIX) :]
    if not path:
        raise HarnessFailure(_PATH_HELPER_OUTPUT_INVALID)
    return path


def _file_sha256(path: Path) -> str:
    """Fingerprint a local file through Python's buffered hashing API."""
    digest = hashlib.sha256()
    with path.open(_BINARY_READ_MODE) as content:
        while chunk := content.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _runner_environment() -> dict[str, str]:
    """Build the small login environment allowed to reach installation commands."""
    home = os.environ[_HOME_ENVIRONMENT_VARIABLE]
    user = os.environ.get(_USER_ENVIRONMENT_VARIABLE) or os.environ.get(_LOGNAME_ENVIRONMENT_VARIABLE)
    if not user:
        raise HarnessFailure(_RUNNER_USER_MISSING)
    environment = {
        _HOME_ENVIRONMENT_VARIABLE: home,
        _USER_ENVIRONMENT_VARIABLE: user,
        _LOGNAME_ENVIRONMENT_VARIABLE: user,
        _SHELL_ENVIRONMENT_VARIABLE: _BASH_BINARY,
        _TMPDIR_ENVIRONMENT_VARIABLE: tempfile.gettempdir(),
        _LANG_ENVIRONMENT_VARIABLE: os.environ.get(
            _LANG_ENVIRONMENT_VARIABLE, _RUN_ENV_BASE[_LANG_ENVIRONMENT_VARIABLE]
        ),
        _PATH_ENVIRONMENT_VARIABLE: _RUN_ENV_BASE[_PATH_ENVIRONMENT_VARIABLE],
    }
    # macOS path_helper is the system source of login PATH ordering; Python has no equivalent API.
    result = subprocess.run(
        [_PATH_HELPER_EXECUTABLE, _PATH_HELPER_OPTION],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=_UTF8,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise HarnessFailure(_PATH_HELPER_FAILED)
    environment[_PATH_ENVIRONMENT_VARIABLE] = _path_from_helper(result.stdout)
    # The installation act builds the release with uv; the hosted job pins it on the controller's PATH, and
    # only its directory crosses into this otherwise closed environment.
    uv = shutil.which(_UV_EXECUTABLE)
    if uv is None:
        raise HarnessFailure(_UV_MISSING)
    environment[_PATH_ENVIRONMENT_VARIABLE] = os.pathsep.join(
        (str(Path(uv).parent), environment[_PATH_ENVIRONMENT_VARIABLE])
    )
    return environment


class BootstrapHarness:
    """Run the fresh-machine install sequence and retain bounded evidence."""

    def __init__(self, output_root: Path, environment: Mapping[str, str]) -> None:
        self._environment = dict(environment)
        self._home = Path(self._environment[_HOME_ENVIRONMENT_VARIABLE]).resolve()
        self._output_root = output_root.expanduser().resolve()
        run_directory_name = _RUN_DIRECTORY_FORMAT.format(prefix=_RUN_DIRECTORY_PREFIX, suffix=uuid.uuid4().hex)
        self._run_directory = self._output_root / run_directory_name
        self._step_log = self._run_directory / _STEP_LOG_FILENAME
        self._project_root = Path.cwd().resolve()
        self._bundle_path = self._run_directory / _BUNDLE_FILENAME
        self._head_commit = _EMPTY_VALUE
        self._project_checkout = self._home / _CHECKOUT_FOLDER
        self._active_release: Path | None = None
        self._step_number = 0

    def run(self) -> None:
        self._step(_STATUS_OUTPUT_DIRECTORY, self._prepare_output)
        self._record_verdict(_STATUS_PRECONDITION, True)
        self._resolve_repository()
        self._create_bundle()
        self._prepare_checkout()
        owner_seed = _load_owner_seed()
        self._install(owner_seed, expected_status=InstallStatus.COMPLETED)
        self._start_and_check_health()
        self._admin_readiness_probes(owner_seed)
        self._role_and_identity_probes(owner_seed)
        self._repeat_install(owner_seed)
        self._restart_services()
        self._install_after_restart(owner_seed)
        self._collect_logs()

    @property
    def run_directory(self) -> Path:
        """Return this run's runner evidence directory."""
        return self._run_directory

    @property
    def home(self) -> str:
        """Return the runner user's home directory."""
        return str(self._home)

    @property
    def project_root(self) -> str:
        """Return the candidate checkout's canonical path, the source the installation was made from."""
        return str(self._project_checkout)

    @property
    def active_release(self) -> Path:
        """Return the installed release folder the install act made active."""
        if self._active_release is None:
            raise HarnessFailure(_ACTIVE_RELEASE_UNRESOLVED)
        return self._active_release

    def cleanup(self, installer_succeeded: bool) -> bool:
        """Confirm the hosted runner owns no separate machine requiring disposal."""
        del installer_succeeded
        return True

    def run_command(
        self,
        name: str,
        command: Sequence[str],
        timeout_seconds: int = _HOST_COMMAND_TIMEOUT_SECONDS,
        *,
        environment: Mapping[str, str] | None = None,
        save_output: bool = True,
        expected_text: str | None = None,
        cwd: Path | None = None,
    ) -> str:
        return self._run_step(
            name,
            command,
            timeout_seconds,
            environment=environment,
            save_output=save_output,
            expected_text=expected_text,
            cwd=self._project_checkout if cwd is None else cwd,
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

    def terminal(
        self, timeout_seconds: int = _TERMINAL_COMMAND_TIMEOUT_SECONDS
    ) -> AbstractContextManager[PersistentTerminal]:
        # CLI probes use the runner home so project context cannot come from the harness checkout.
        os.chdir(self._home)
        return PersistentTerminal(_NO_PROFILE_BASH, environment=self._environment, timeout_seconds=timeout_seconds)

    def snapshot_settled_files(self) -> tuple[str, ...]:
        global_config = self._home / _GLOBAL_CONFIG_RELATIVE_PATH
        environment_file = self._home / _MACHINE_ENV_RELATIVE_PATH
        digests: list[str] = []
        for path in (global_config, environment_file):
            try:
                digests.append(_file_sha256(path))
            except OSError as exc:
                detail = _FILE_FINGERPRINT_FAILED.format(path=path, error=exc)
                self._record_verdict(_STATUS_SETTLED_FILES_SNAPSHOT, False, detail)
                raise HarnessFailure(detail) from exc
        self._record_verdict(_STATUS_SETTLED_FILES_SNAPSHOT, True)
        return tuple(digests)

    def create_directory(self, name: str, path: Path) -> None:
        """Create a local harness directory and retain the operation in the step report."""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            detail = _DIRECTORY_CREATE_FAILED.format(path=path, error=exc)
            self._record_verdict(name, False, detail)
            raise HarnessFailure(detail) from exc
        self._record_verdict(name, True)

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
            self._record_verdict(_STATUS_REPOSITORY_ROOT, False, _REPOSITORY_ROOT_FAILED)
            raise HarnessFailure(_REPOSITORY_ROOT_FAILED)
        self._project_root = Path(root.output.strip()).resolve()
        self._head_commit = head.output.strip()
        self._record_verdict(_STATUS_REPOSITORY_ROOT, True, self._head_commit)

    def _create_bundle(self) -> None:
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
            self._record_verdict(_STATUS_BUNDLE, False, detail)
            raise HarnessFailure(detail)
        self._record_verdict(_STATUS_BUNDLE, True)

    def _prepare_checkout(self) -> None:
        self.create_directory(_STATUS_CHECKOUT_PARENT, self._project_checkout.parent)
        self.run_command(
            _STATUS_BUNDLE_CLONE,
            [
                _GIT_BINARY,
                _GIT_CLONE_COMMAND,
                _GIT_NO_CHECKOUT_OPTION,
                str(self._bundle_path),
                str(self._project_checkout),
            ],
            _HOST_COMMAND_TIMEOUT_SECONDS,
            cwd=self._home,
        )
        self.run_command(
            _STATUS_BUNDLE_CHECKOUT,
            [
                _GIT_BINARY,
                _GIT_CHANGE_DIRECTORY_OPTION,
                str(self._project_checkout),
                _GIT_CHECKOUT_COMMAND,
                _GIT_DETACH_OPTION,
                self._head_commit,
            ],
            _HOST_COMMAND_TIMEOUT_SECONDS,
            cwd=self._home,
        )

    def _install(
        self, owner_seed: OwnerSeed, step_name: str = _STATUS_INSTALL, *, expected_status: InstallStatus
    ) -> None:
        """Install the candidate as the bootstrap does: the install act, then convergence from the installed release."""
        act_environment = {_PYTHON_PATH_ENVIRONMENT_VARIABLE: str(self._project_checkout)}
        self.run_command(
            _INSTALL_ACT_STEP.format(name=step_name),
            [
                sys.executable,
                _PYTHON_ISOLATED_OPTION,
                _PYTHON_MODULE_OPTION,
                _INSTALL_ACT_MODULE,
                _INSTALL_ACT_BOOTSTRAP_VERB,
                _INSTALL_ACT_SOURCE_OPTION,
                str(self._project_checkout),
                _INSTALL_ACT_REVISION_OPTION,
                self._head_commit,
            ],
            _INSTALL_TIMEOUT_SECONDS,
            environment=act_environment,
            expected_text=_INSTALL_RESULT_LINE.format(status=expected_status, revision=self._head_commit),
        )
        first_installation = self._active_release is None
        if self._active_release is None:
            self._active_release = self._resolve_active_release(step_name, act_environment)
        self.run_command(
            _CONVERGE_STEP.format(name=step_name),
            [str(self._active_release / _CONVERGENCE_INSTALLER)],
            _INSTALL_TIMEOUT_SECONDS,
            environment={_OWNER_NAME_ENV: owner_seed.name, _OWNER_EMAIL_ENV: owner_seed.email},
        )
        if first_installation:
            # install.sh exports the publication directory only into its own process, which cannot reach this
            # harness; the later make, terminal and probe commands resolve the published telec through this PATH.
            publication_directory = str(self._home / TELEC_RELATIVE_PATH.parent)
            self._environment[_PATH_ENVIRONMENT_VARIABLE] = os.pathsep.join(
                (publication_directory, self._environment[_PATH_ENVIRONMENT_VARIABLE])
            )

    def _resolve_active_release(self, step_name: str, environment: Mapping[str, str]) -> Path:
        """Ask the installation layout, in the installation's own environment, which release is active."""
        name = _ACTIVE_RELEASE_STEP.format(name=step_name)
        output = self.run_command(
            name,
            [sys.executable, _PYTHON_ISOLATED_OPTION, _PYTHON_COMMAND_OPTION, _ACTIVE_RELEASE_QUERY],
            _HOST_COMMAND_TIMEOUT_SECONDS,
            environment=environment,
        )
        lines = output.strip().splitlines()
        reported = lines[-1].strip() if lines else _EMPTY_VALUE
        release = Path(reported)
        if not release.is_absolute() or not (release / _CONVERGENCE_INSTALLER).is_file():
            detail = _ACTIVE_RELEASE_INVALID.format(reported=reported)
            self._record_verdict(name, False, detail)
            raise HarnessFailure(detail)
        return release

    def _start_and_check_health(self) -> None:
        # The start command clears its caller before dispatch; on a real terminal that caller is the
        # sole registered owner, which the generic background path cannot present.
        with self.terminal(_DAEMON_COMMAND_TIMEOUT_SECONDS) as terminal:
            self._record_terminal_step(
                terminal,
                _STATUS_START,
                [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, str(self._project_checkout), _START_TARGET],
            )
            self._record_terminal_step(
                terminal,
                _STATUS_HEALTH,
                [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, str(self._project_checkout), _STATUS_TARGET],
                expected_text=_HEALTHY_STATUS_TOKEN,
            )

    def _record_terminal_step(
        self,
        terminal: PersistentTerminal,
        name: str,
        command: Sequence[str],
        *,
        expected_text: str | None = None,
    ) -> None:
        # A terminal that fails to return a bounded result keeps the partial output `_capture` gives a timed-out
        # step, and the failure record names the terminal's reason.
        try:
            result = terminal.run(command)
        except TerminalFailure as exc:
            detail = _TERMINAL_FAILURE_DETAIL.format(reason=exc)
            self._save_output(name, exc.output)
            self._record_verdict(name, False, detail)
            raise HarnessFailure(detail) from exc
        self.record_terminal_result(name, result, expected_text=expected_text)

    def _admin_readiness_probes(self, owner_seed: OwnerSeed) -> None:
        telec = str(self._home / TELEC_RELATIVE_PATH)
        with self.terminal() as terminal:
            login = terminal.run([telec, TelecToken.AUTH, TelecToken.LOGIN, owner_seed.email])
            self.record_terminal_result(_STATUS_LOGIN, login)
            version = terminal.run([telec, TelecToken.VERSION])
            self.record_terminal_result(_STATUS_VERSION, version)
            docs = terminal.run([telec, TelecToken.DOCS, TelecToken.GET, _DOCS_PROBE_ID])
            self.record_terminal_result(
                _STATUS_DOCS,
                docs,
                expected_text=_DOCS_RETURNED_ID_LINE.format(snippet_id=_DOCS_PROBE_ID),
            )
            validation = terminal.run([telec, TelecToken.CONFIG, TelecToken.VALIDATE])
            self.record_terminal_result(_STATUS_CONFIG, validation)

    def _role_and_identity_probes(self, owner_seed: OwnerSeed) -> None:
        try:
            run_role_and_identity_probes(self, owner_seed.email)
        except ProbeFailure as exc:
            self._record_verdict(_STATUS_PROBES, False, str(exc))
            raise HarnessFailure(str(exc)) from exc

    def _repeat_install(self, owner_seed: OwnerSeed) -> None:
        before = self.snapshot_settled_files()
        self._install(owner_seed, _STATUS_REPEAT_INSTALL, expected_status=InstallStatus.UNCHANGED)
        after = self.snapshot_settled_files()
        self._record_verdict(_STATUS_SETTLED_FILES, before == after)
        if before != after:
            raise HarnessFailure(_SETTLED_FILES_CHANGED)

    def _restart_services(self) -> None:
        for name, target in ((_STATUS_SERVICE_STOP, _STOP_TARGET), (_STATUS_START, _START_TARGET)):
            self.run_command(
                name,
                [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, str(self._project_checkout), target],
                _DAEMON_COMMAND_TIMEOUT_SECONDS,
            )
        self.run_command(
            _STATUS_HEALTH,
            [_MAKE_BINARY, _MAKE_CHANGE_DIRECTORY_OPTION, str(self._project_checkout), _STATUS_TARGET],
            _DAEMON_COMMAND_TIMEOUT_SECONDS,
            expected_text=_HEALTHY_STATUS_TOKEN,
        )
        self._record_verdict(_STATUS_RESTART, True)

    def _install_after_restart(self, owner_seed: OwnerSeed) -> None:
        before = self.snapshot_settled_files()
        self._install(owner_seed, _STATUS_RESTART_INSTALL, expected_status=InstallStatus.UNCHANGED)
        after = self.snapshot_settled_files()
        self._record_verdict(_STATUS_POST_RESTART_FILES, before == after)
        if before != after:
            raise HarnessFailure(_SETTLED_FILES_CHANGED)

    def _collect_logs(self) -> None:
        log_cli = str(self._home / _LOGS_RELATIVE_PATH)
        output = self.run_command(
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
        try:
            # Git bundle/checkout and the Make, TeleClaude, and log-collector CLI contracts need real processes.
            result = subprocess.run(
                list(argv),
                cwd=cwd,
                env={**self._environment, **(environment or {})},
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
        cwd: Path | None = None,
    ) -> str:
        result = self._capture(argv, timeout_seconds, cwd=cwd, environment=environment)
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


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    default_output = Path(tempfile.gettempdir()) / _DEFAULT_OUTPUT_DIRECTORY
    parser.add_argument(_OUTPUT_DIRECTORY_ARGUMENT, type=Path, default=default_output)
    return parser


def main() -> int:
    args = _build_argument_parser().parse_args()
    refusal = _hosted_runner_refusal()
    if refusal is not None:
        print(_STEP_FAILED.format(name=_STATUS_PRECONDITION, detail=refusal), flush=True)
        return 1
    try:
        environment = _runner_environment()
        harness = BootstrapHarness(args.output_dir, environment)
    except (HarnessFailure, OSError, subprocess.SubprocessError) as exc:
        print(_STEP_FAILED.format(name=_STATUS_PRECONDITION, detail=str(exc)), flush=True)
        return 1
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
