"""Verification gate effects: prove an applied DeepSeek set works by running it in isolation.

Executes only; whether the applied set stays is the core operation's decision. The gate
runs every profile under a throwaway harness home and a throwaway user home, so the
operator's hooks (TeleClaude's receiver among them) never fire for a gate turn and
nothing a profile keeps beside the harness home reaches the operator's data. Turn
outcomes are read from the gate's own hooks, composer readiness from the agent
runtime's classifier, and everything the gate starts is torn down on every path.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName, LaunchProfile
from teleclaude.core.agent_readiness import PromptDeliveryState, classify_prompt_delivery
from teleclaude.core.reconciliation.deepseek_fit import DeepSeekStackError, ProfileStack, Stack
from teleclaude.core.reconciliation.deepseek_stack import GateCheck, GateVerdict
from teleclaude.core.tmux_bridge import PaneCursor, PaneObservation
from teleclaude.install.deepseek_profiles import dsh_executable, harness_home
from teleclaude.install.deepseek_registry import read_manifest
from teleclaude.install.dsh_hooks_install import DSH_TUI_DATA_DIRNAME, configure_dsh_tui_onboarding

logger = get_logger(__name__)

_GATE_DIRECTORY = "gate"
_HARNESS_HOME_DIRECTORY = "home"
_USER_HOME_DIRECTORY = "user"
_WORKING_DIRECTORY = "work"
_SIGNALS_DIRECTORY = "signals"
_PROFILES_DIRECTORY = "profiles"
_CREDENTIALS_FILE = ".credentials.yaml"
_HOOKS_FILE = "hooks.json"
_PRESETS_DIRECTORY = ".agent-presets"
# The runtime keeps these data stores in the harness home (third-party/deepseek-dsh/runtime-surface, Harness
# home); the gate's own home starts without them so no gate turn lands in the operator's sessions or history.
_NOT_COPIED = frozenset(
    {"sessions", "storages", ".history", "logs", _HOOKS_FILE, _PROFILES_DIRECTORY, _CREDENTIALS_FILE}
)
_MANIFEST_FILE = "package.json"
_PROFILE_FIELD = "dsh"
_PROFILE_SECTION = "profile"
_PROFILES_PROTOCOL_FIELD: Final = "profiles"
_BUNDLES_FIELD = "bundles"

_PROMPT_CONTEXT_FILE = "prompt-context.json"
_STOP_FILE = "stop.jsonl"
_STOP_FAILURE_FILE = "stop-failure.jsonl"
_LAUNCH_STDERR_FILE = "launch-stderr.log"
_APP_STDOUT_TEMPLATE = "{profile}-stdout.log"
_APP_STDERR_TEMPLATE = "{profile}-stderr.log"
# The injected context arrives as a new inbox message that fires the prompt hook again, so the replay empties
# the file as it prints it: the context is returned once, as a real hook returns it.
_HOOK_REPLAY_COMMAND = "cat {path} && : > {path}"
_HOOK_APPEND_COMMAND = "cat >> {path}"
_HOOK_TYPE_COMMAND = "command"
_HOOK_MATCH_ALL = "*"
_HOOKS_KEY = "hooks"
_HOOK_MATCHER_KEY = "matcher"
_HOOK_TYPE_KEY = "type"
_HOOK_COMMAND_KEY = "command"
_HOOK_UNSANDBOXED_KEY = "unsandboxed"
_PRESET_HOOKS_GLOB_TEMPLATE = "*/{name}"
_WRITE_BINARY = "wb"
_ERRORS_REPLACE = "replace"
_JSON_INDENT = 2

_ENV_HOME = "HOME"
_ENV_DSH_HOME = "DSH_HOME"
# TeleClaude's git wrapper resolves its declaration cache from the user home; under the gate's own home it cannot,
# so the gate's processes step it aside through the wrapper's trusted-tool door and do not claim to run inside the
# operator's terminal server.
_ENV_TRUSTED_TOOL = "TELECLAUDE_TRUSTED_TOOL"
_ENV_TRUSTED_TOOL_ON = "1"
_ENV_TERMINAL_SERVER = ("TMUX", "TMUX_PANE")
_DUMP_CONFIG_FLAGS = ("--dump-config",)
_PROFILE_FLAG = "--profile"
_WEB_FLAGS = ("--no-open", "--port", "0", "--host", "127.0.0.1")
_WEB_READY_PREFIX = "dsh web: "
_HEADLESS_JSON_FLAG = "--json"
_HEADLESS_FINAL_EVENT = "final"
_EVENT_TYPE_FIELD = "type"
_HEADLESS_TASK = "Reply with the single word: ready"
_TURN_PROMPT = "Reply with the single word: ready"
_HOOK_CONTEXT_PROMPT = (
    "A hook supplies a gate code word with this turn. Once you have it, reply with exactly that code word."
)
_HOOK_CONTEXT_TEXT_TEMPLATE = "Hook context for this turn: the gate code word is {token}."
_HOOK_EVENT_NAME_FIELD = "hookEventName"
_HOOK_SPECIFIC_OUTPUT_FIELD = "hookSpecificOutput"
_ADDITIONAL_CONTEXT_FIELD = "additionalContext"

_TMUX = "tmux"
_TMUX_SOCKET_FLAG = "-L"
_TMUX_NO_CONFIG = ("-f", "/dev/null")
_TMUX_SOCKET_TEMPLATE = "deepseek-gate-{token}"
_TMUX_SESSION = "gate"
_TMUX_SIZE = ("-x", "200", "-y", "50")
_TMUX_NEW_SESSION = "new-session"
_TMUX_KILL_SERVER = "kill-server"
_TMUX_SOCKET_PATH_FORMAT = "#{socket_path}"
_TMUX_SEND_KEYS = "send-keys"
_TMUX_CAPTURE_PANE = "capture-pane"
_TMUX_DISPLAY_MESSAGE = "display-message"
_TMUX_COMMAND_SEPARATOR = ";"
_TMUX_TARGET_FLAG = "-t"
_TMUX_PRINT_FLAG = "-p"
_TMUX_ESCAPES_FLAG = "-e"
_TMUX_LITERAL_FLAG = "-l"
_TMUX_ENTER_KEY = "Enter"
_TMUX_DETACHED_FLAG = "-d"
_TMUX_WORKDIR_FLAG = "-c"
_TMUX_SESSION_FLAG = "-s"
_OBSERVATION_MARKER = "__TELECLAUDE_GATE_PANE_BOUNDARY_7d21f0aa__"
_OBSERVATION_FORMAT = _OBSERVATION_MARKER + "#{cursor_flag} #{cursor_y} #{cursor_x}"
_CURSOR_VISIBLE_FLAG = "1"
_CURSOR_FIELD_COUNT = 3
_OUTPUT_ENCODING = "utf-8"
_STDERR_REDIRECT_TEMPLATE = "{command} 2> {path}"

_CONFIG_DUMP_TIMEOUT_SECONDS = 60
_WEB_READY_TIMEOUT_SECONDS = 90
_HEADLESS_TIMEOUT_SECONDS = 240
_OTHER_APP_SETTLE_SECONDS = 15
_COMPOSER_TIMEOUT_SECONDS = 120
_TURN_TIMEOUT_SECONDS = 240
_CONTEXT_TIMEOUT_SECONDS = 60
_TMUX_COMMAND_TIMEOUT_SECONDS = 20
_POLL_INTERVAL_SECONDS = 0.5
_STOP_GRACE_SECONDS = 5
_DETAIL_TAIL_CHARS = 500

_TMUX_UNAVAILABLE = "tmux is not installed or not on PATH"
_LAUNCH_PROFILE_MISSING_TEMPLATE = "The launch profile {profile} does not exist in the harness home"
_LAUNCH_ARGUMENTS_TEMPLATE = "The DeepSeek launch arguments {arguments!r} name no profile"
_CONFIG_FAILED_TEMPLATE = "{profile}: --dump-config exited {code}; stderr: {stderr}"
_CONFIG_TIMEOUT_TEMPLATE = "{profile}: --dump-config did not finish within {seconds} seconds"
_START_STDERR_TEMPLATE = "{profile}: startup wrote diagnostics: {stderr}"
_FILE_READ_FAILURE_TEMPLATE = "Cannot read gate file {path}: {error}"
_WEB_NOT_READY_TEMPLATE = "{profile}: no {prefix!r} line within {seconds} seconds"
_HEADLESS_FAILED_TEMPLATE = "{profile}: headless one-shot exited {code}; stderr: {stderr}"
_HEADLESS_TIMEOUT_TEMPLATE = "{profile}: headless one-shot did not finish within {seconds} seconds"
_HEADLESS_NO_FINAL_TEMPLATE = "{profile}: headless one-shot reached no {event!r} event; output tail: {output}"
_OTHER_EXITED_TEMPLATE = "{profile}: the app exited with {code} before {seconds} seconds"
_COMPOSER_NOT_READY_TEMPLATE = "{profile}: no ready composer within {seconds} seconds; screen tail: {screen}"
_TURN_FAILED_TEMPLATE = "{label}: the turn reported an error: {error}"
_TURN_TIMEOUT_TEMPLATE = "{label}: no completed turn within {seconds} seconds; screen tail: {screen}"
_CONTEXT_MISSING_TEMPLATE = (
    "{label}: the turn completed but the hook's additional context never reached the model within {seconds} seconds; "
    "screen tail: {screen}"
)
_TURN_SESSION_GONE_TEMPLATE = "{label}: the profile exited before the turn completed"
_SCREEN_TAIL_ROWS = 12
_TURN_LABEL = "prompt turn"
_HOOK_TURN_LABEL = "hook-context turn"
_EMPTY_FILE_TEXT = ""
_ROW_SEPARATOR = "\n"
_NO_SCREEN = "(no screen)"
_LOG_CHECK = "DeepSeek gate check"
_LOG_TEARDOWN = "DeepSeek gate teardown step failed"


class AppKind(StrEnum):
    """What a profile's app is, as its declared bundles say."""

    WEB = "web"
    HEADLESS = "headless"
    TUI = "tui"
    OTHER = "other"


# The app bundle each vendor app package contributes to a profile's bundle list.
_BUNDLE_APP_KINDS: Mapping[str, AppKind] = {
    "@deepseek-ai/dsh-web-app": AppKind.WEB,
    "@deepseek-ai/dsh-headless": AppKind.HEADLESS,
    "@deepseek-harness-tui/dsh-tui": AppKind.TUI,
}


class HookEvent(StrEnum):
    """The hook events the gate registers."""

    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    STOP_FAILURE = "StopFailure"


class _CheckFailed(Exception):
    """One gate check failed; carries the check and what was observed."""

    def __init__(self, check: GateCheck, detail: str) -> None:
        super().__init__(detail)
        self.check = check
        self.detail = detail


@dataclass(frozen=True)
class _Completed:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class _GatePaths:
    root: Path
    harness_home: Path
    user_home: Path
    working_directory: Path
    signals: Path


class DeepSeekGate:
    """Runs the verification gate for one convergence run under the run's scratch area."""

    def __init__(self, scratch_directory: Path) -> None:
        self._paths = _gate_paths(scratch_directory / _GATE_DIRECTORY)
        self._environment: dict[str, str] = {}
        self._processes: list[subprocess.Popen[bytes]] = []
        self._tmux_socket = _TMUX_SOCKET_TEMPLATE.format(token=uuid.uuid4().hex)

    def run_gate(self, stack: Stack) -> GateVerdict:
        """Run every check in order; stop at the first failure. Teardown runs whatever the verdict."""
        try:
            self._prepare()
            self._run_checks(stack)
        except _CheckFailed as failure:
            logger.warning(_LOG_CHECK, check=failure.check, passed=False, detail=failure.detail)
            return GateVerdict(False, failure.check, failure.detail)
        finally:
            self._teardown()
        return GateVerdict(True, None, None)

    def _run_checks(self, stack: Stack) -> None:
        launch_profile = _launch_profile_name()
        names = tuple(profile.name for profile in stack.profiles)
        for name in names:
            self._check_composed_config(name)
        if launch_profile not in names:
            raise _CheckFailed(
                GateCheck.COMPOSER_READY, _LAUNCH_PROFILE_MISSING_TEMPLATE.format(profile=launch_profile)
            )
        for profile in stack.profiles:
            if profile.name != launch_profile:
                self._check_profile_start(profile)
        self._check_launch_profile(launch_profile)

    def _prepare(self) -> None:
        paths = self._paths
        for directory in (paths.harness_home, paths.user_home, paths.working_directory, paths.signals):
            directory.mkdir(parents=True)
        _build_harness_home(harness_home(), paths.harness_home)
        _write_gate_hooks(paths.harness_home / _HOOKS_FILE, paths.signals)
        for name in (_PROMPT_CONTEXT_FILE, _STOP_FILE, _STOP_FAILURE_FILE):
            (paths.signals / name).write_text(_EMPTY_FILE_TEXT)
        # The first-run guide is recorded in the operator's TUI data before it is copied, so the gate's launch is
        # checked against the operator's own record.
        configure_dsh_tui_onboarding()
        operator_tui_data = Path.home() / DSH_TUI_DATA_DIRNAME
        shutil.copytree(
            operator_tui_data, paths.user_home / DSH_TUI_DATA_DIRNAME, symlinks=True, ignore=_ignore_sockets
        )
        self._environment = _gate_environment(paths)

    def _check_composed_config(self, profile: str) -> None:
        completed = self._run_bounded(
            (str(dsh_executable()), _PROFILE_FLAG, profile, *_DUMP_CONFIG_FLAGS), _CONFIG_DUMP_TIMEOUT_SECONDS
        )
        if completed is None:
            raise _CheckFailed(
                GateCheck.COMPOSED_CONFIG,
                _CONFIG_TIMEOUT_TEMPLATE.format(profile=profile, seconds=_CONFIG_DUMP_TIMEOUT_SECONDS),
            )
        if completed.returncode != 0 or completed.stderr.strip():
            raise _CheckFailed(
                GateCheck.COMPOSED_CONFIG,
                _CONFIG_FAILED_TEMPLATE.format(
                    profile=profile, code=completed.returncode, stderr=_tail(completed.stderr)
                ),
            )

    def _check_profile_start(self, profile: ProfileStack) -> None:
        checks: Mapping[AppKind, Callable[[str], None]] = {
            AppKind.WEB: self._start_web,
            AppKind.HEADLESS: self._start_headless,
            AppKind.TUI: self._start_other_tui,
            AppKind.OTHER: self._start_other,
        }
        checks[_app_kind(profile.name)](profile.name)

    def _start_web(self, profile: str) -> None:
        stdout_path, stderr_path = self._app_logs(profile)
        process = self._spawn((str(dsh_executable()), _PROFILE_FLAG, profile, *_WEB_FLAGS), stdout_path, stderr_path)
        ready = _wait_until(
            lambda: _WEB_READY_PREFIX in _read_text(stdout_path, GateCheck.PROFILE_START) or process.poll() is not None,
            _WEB_READY_TIMEOUT_SECONDS,
        )
        if not ready or _WEB_READY_PREFIX not in _read_text(stdout_path, GateCheck.PROFILE_START):
            raise _CheckFailed(
                GateCheck.PROFILE_START,
                _WEB_NOT_READY_TEMPLATE.format(
                    profile=profile, prefix=_WEB_READY_PREFIX, seconds=_WEB_READY_TIMEOUT_SECONDS
                ),
            )
        self._require_quiet_stderr(profile, stderr_path)

    def _start_headless(self, profile: str) -> None:
        completed = self._run_bounded(
            (str(dsh_executable()), _PROFILE_FLAG, profile, _HEADLESS_JSON_FLAG, _HEADLESS_TASK),
            _HEADLESS_TIMEOUT_SECONDS,
        )
        if completed is None:
            raise _CheckFailed(
                GateCheck.PROFILE_START,
                _HEADLESS_TIMEOUT_TEMPLATE.format(profile=profile, seconds=_HEADLESS_TIMEOUT_SECONDS),
            )
        if completed.returncode != 0 or completed.stderr.strip():
            raise _CheckFailed(
                GateCheck.PROFILE_START,
                _HEADLESS_FAILED_TEMPLATE.format(
                    profile=profile, code=completed.returncode, stderr=_tail(completed.stderr)
                ),
            )
        if not _has_event(completed.stdout, _HEADLESS_FINAL_EVENT):
            raise _CheckFailed(
                GateCheck.PROFILE_START,
                _HEADLESS_NO_FINAL_TEMPLATE.format(
                    profile=profile, event=_HEADLESS_FINAL_EVENT, output=_tail(completed.stdout)
                ),
            )

    def _start_other_tui(self, profile: str) -> None:
        self._boot_tui(profile)
        self._require_quiet_stderr(profile, self._paths.signals / _LAUNCH_STDERR_FILE)
        self._kill_tmux()

    def _start_other(self, profile: str) -> None:
        stdout_path, stderr_path = self._app_logs(profile)
        process = self._spawn((str(dsh_executable()), _PROFILE_FLAG, profile), stdout_path, stderr_path)
        exited = _wait_until(lambda: process.poll() is not None, _OTHER_APP_SETTLE_SECONDS)
        if exited:
            raise _CheckFailed(
                GateCheck.PROFILE_START,
                _OTHER_EXITED_TEMPLATE.format(
                    profile=profile, code=process.returncode, seconds=_OTHER_APP_SETTLE_SECONDS
                ),
            )
        self._require_quiet_stderr(profile, stderr_path)

    def _check_launch_profile(self, profile: str) -> None:
        stderr_path = self._paths.signals / _LAUNCH_STDERR_FILE
        self._boot_tui(profile)
        self._require_quiet_stderr(profile, stderr_path)
        self._complete_turn(_TURN_PROMPT, _TURN_LABEL, GateCheck.TURN, expected_stops=1)
        token = uuid.uuid4().hex
        (self._paths.signals / _PROMPT_CONTEXT_FILE).write_text(_hook_context_decision(token))
        self._wait_for_composer(profile)
        self._complete_turn(
            _HOOK_CONTEXT_PROMPT, _HOOK_TURN_LABEL, GateCheck.HOOK_CONTEXT_TURN, expected_stops=2, context_token=token
        )
        self._require_quiet_stderr(profile, stderr_path)

    def _boot_tui(self, profile: str) -> None:
        """Start the profile in the gate's own terminal server and wait for its ready composer."""
        stderr_path = self._paths.signals / _LAUNCH_STDERR_FILE
        stderr_path.write_text(_EMPTY_FILE_TEXT)
        command = _STDERR_REDIRECT_TEMPLATE.format(
            command=shlex.join((str(dsh_executable()), *_launch_arguments())), path=shlex.quote(str(stderr_path))
        )
        self._tmux(
            _TMUX_NEW_SESSION,
            _TMUX_DETACHED_FLAG,
            _TMUX_SESSION_FLAG,
            _TMUX_SESSION,
            *_TMUX_SIZE,
            _TMUX_WORKDIR_FLAG,
            str(self._paths.working_directory),
            command,
            socket_flags=_TMUX_NO_CONFIG,
        )
        self._wait_for_composer(profile)

    def _wait_for_composer(self, profile: str) -> None:
        if not _wait_until(self._composer_is_ready, _COMPOSER_TIMEOUT_SECONDS):
            raise _CheckFailed(
                GateCheck.COMPOSER_READY,
                _COMPOSER_NOT_READY_TEMPLATE.format(
                    profile=profile, seconds=_COMPOSER_TIMEOUT_SECONDS, screen=self._screen_tail()
                ),
            )

    def _composer_is_ready(self) -> bool:
        observation = self._observe()
        if observation is None:
            return False
        delivery = classify_prompt_delivery(observation, AgentName.DEEPSEEK.value)
        return delivery.state is PromptDeliveryState.EMPTY

    def _complete_turn(
        self, prompt: str, label: str, check: GateCheck, *, expected_stops: int, context_token: str | None = None
    ) -> None:
        """Submit a prompt and require a recorded stop without a turn error.

        With ``context_token`` the turn must also have received the hook's additional context: the context
        carries a token that is generated per run and given to the runtime only through the hook's decision, and the
        turn passes only once that token is visible on the screen. The check shows the runtime received the
        context; it does not locate the token in the model's answer.
        """
        stop_path = self._paths.signals / _STOP_FILE
        failure_path = self._paths.signals / _STOP_FAILURE_FILE
        self._tmux(_TMUX_SEND_KEYS, _TMUX_TARGET_FLAG, _TMUX_SESSION, _TMUX_LITERAL_FLAG, prompt)
        self._tmux(_TMUX_SEND_KEYS, _TMUX_TARGET_FLAG, _TMUX_SESSION, _TMUX_ENTER_KEY)
        finished = _wait_until(
            lambda: (
                _record_count(stop_path, check) >= expected_stops
                or _record_count(failure_path, check) > 0
                or not self._session_exists()
            ),
            _TURN_TIMEOUT_SECONDS,
        )
        if _record_count(failure_path, check) > 0:
            raise _CheckFailed(
                check, _TURN_FAILED_TEMPLATE.format(label=label, error=_tail(_read_text(failure_path, check)))
            )
        if _record_count(stop_path, check) < expected_stops:
            if finished:
                raise _CheckFailed(check, _TURN_SESSION_GONE_TEMPLATE.format(label=label))
            raise _CheckFailed(
                check,
                _TURN_TIMEOUT_TEMPLATE.format(label=label, seconds=_TURN_TIMEOUT_SECONDS, screen=self._screen_tail()),
            )
        if context_token is not None and not _wait_until(
            lambda: self._screen_shows(context_token), _CONTEXT_TIMEOUT_SECONDS
        ):
            raise _CheckFailed(
                check,
                _CONTEXT_MISSING_TEMPLATE.format(
                    label=label, seconds=_CONTEXT_TIMEOUT_SECONDS, screen=self._screen_tail()
                ),
            )

    def _screen_shows(self, token: str) -> bool:
        """Whether the gate's own token is anywhere on the visible screen (an identity check, not a reading of prose)."""
        observation = self._observe()
        return observation is not None and token in observation.text

    def _require_quiet_stderr(self, profile: str, stderr_path: Path) -> None:
        stderr = _read_text(stderr_path, GateCheck.PROFILE_START).strip()
        if stderr:
            raise _CheckFailed(
                GateCheck.PROFILE_START, _START_STDERR_TEMPLATE.format(profile=profile, stderr=_tail(stderr))
            )

    def _app_logs(self, profile: str) -> tuple[Path, Path]:
        return (
            self._paths.signals / _APP_STDOUT_TEMPLATE.format(profile=profile),
            self._paths.signals / _APP_STDERR_TEMPLATE.format(profile=profile),
        )

    def _run_bounded(self, arguments: Sequence[str], timeout_seconds: int) -> _Completed | None:
        """Run to completion without terminal input; ``None`` when the bound passes (the process group is killed)."""
        # The runtime and its apps are external programs; no Python API exists to boot a profile.
        process = subprocess.Popen(
            tuple(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._paths.working_directory,
            env=self._environment,
            start_new_session=True,
        )
        self._processes.append(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            process.communicate()
            return None
        return _Completed(
            process.returncode,
            stdout.decode(_OUTPUT_ENCODING, _ERRORS_REPLACE),
            stderr.decode(_OUTPUT_ENCODING, _ERRORS_REPLACE),
        )

    def _spawn(self, arguments: Sequence[str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen[bytes]:
        """Start a long-running app with its output in files; teardown ends its process group."""
        # The runtime and its apps are external programs; no Python API exists to boot a profile.
        with stdout_path.open(_WRITE_BINARY) as stdout, stderr_path.open(_WRITE_BINARY) as stderr:
            process = subprocess.Popen(
                tuple(arguments),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                cwd=self._paths.working_directory,
                env=self._environment,
                start_new_session=True,
            )
        self._processes.append(process)
        return process

    def _tmux(self, *arguments: str, socket_flags: tuple[str, ...] = ()) -> subprocess.CompletedProcess[bytes]:
        executable = shutil.which(_TMUX)
        if executable is None:
            raise DeepSeekStackError(_TMUX_UNAVAILABLE)
        # tmux owns terminal emulation for the TUI; the gate drives its own private server through its CLI.
        try:
            return subprocess.run(
                (executable, _TMUX_SOCKET_FLAG, self._tmux_socket, *socket_flags, *arguments),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=_TMUX_COMMAND_TIMEOUT_SECONDS,
                env=self._environment or None,
            )
        except subprocess.TimeoutExpired as error:
            raise DeepSeekStackError(str(error)) from error

    def _session_exists(self) -> bool:
        return self._observe() is not None

    def _observe(self) -> PaneObservation | None:
        """The visible pane text and cursor in one tmux call; ``None`` when no pane is there to read."""
        result = self._tmux(
            _TMUX_CAPTURE_PANE,
            _TMUX_TARGET_FLAG,
            _TMUX_SESSION,
            _TMUX_PRINT_FLAG,
            _TMUX_ESCAPES_FLAG,
            _TMUX_COMMAND_SEPARATOR,
            _TMUX_DISPLAY_MESSAGE,
            _TMUX_TARGET_FLAG,
            _TMUX_SESSION,
            _TMUX_PRINT_FLAG,
            _OBSERVATION_FORMAT,
        )
        if result.returncode != 0:
            return None
        return _parse_observation(result.stdout.decode(_OUTPUT_ENCODING, _ERRORS_REPLACE))

    def _screen_tail(self) -> str:
        observation = self._observe()
        if observation is None:
            return _NO_SCREEN
        rows = [row.rstrip() for row in observation.text.split(_ROW_SEPARATOR)]
        return _ROW_SEPARATOR.join([row for row in rows if row][-_SCREEN_TAIL_ROWS:])

    def _kill_tmux(self) -> None:
        """Stop the gate's terminal server and remove its socket, which an interrupted server can leave behind."""
        try:
            located = self._tmux(
                _TMUX_DISPLAY_MESSAGE, _TMUX_TARGET_FLAG, _TMUX_SESSION, _TMUX_PRINT_FLAG, _TMUX_SOCKET_PATH_FORMAT
            )
            self._tmux(_TMUX_KILL_SERVER)
        except DeepSeekStackError as error:
            logger.warning(_LOG_TEARDOWN, step=_TMUX_KILL_SERVER, error=str(error))
            return
        socket_path = located.stdout.decode(_OUTPUT_ENCODING, _ERRORS_REPLACE).strip()
        if located.returncode == 0 and socket_path:
            Path(socket_path).unlink(missing_ok=True)

    def _teardown(self) -> None:
        """Stop the terminal server and every process the gate started; remove everything it created."""
        self._kill_tmux()
        for process in self._processes:
            _kill_group(process)
        shutil.rmtree(self._paths.root, ignore_errors=True)


def _ignore_sockets(directory: str, names: list[str]) -> list[str]:
    """Live socket endpoints cannot be copied and mean nothing to a copy; leave them out."""
    return [name for name in names if stat.S_ISSOCK(os.lstat(os.path.join(directory, name)).st_mode)]


def _gate_paths(root: Path) -> _GatePaths:
    return _GatePaths(
        root,
        root / _HARNESS_HOME_DIRECTORY,
        root / _USER_HOME_DIRECTORY,
        root / _WORKING_DIRECTORY,
        root / _SIGNALS_DIRECTORY,
    )


def _gate_environment(paths: _GatePaths) -> dict[str, str]:
    """The ambient environment with the gate's own homes, the launch environment and the wrapper step-aside applied."""
    environment = dict(os.environ)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    environment.update(AGENT_REGISTRY[AgentName.DEEPSEEK].launch_environment)
    environment[_ENV_HOME] = str(paths.user_home)
    environment[_ENV_DSH_HOME] = str(paths.harness_home)
    environment[_ENV_TRUSTED_TOOL] = _ENV_TRUSTED_TOOL_ON
    for name in _ENV_TERMINAL_SERVER:
        environment.pop(name, None)
    return environment


def _launch_arguments() -> tuple[str, ...]:
    """The launch arguments of the DeepSeek agent definition."""
    profiles = AGENT_REGISTRY[AgentName.DEEPSEEK].protocol[_PROFILES_PROTOCOL_FIELD]
    return tuple(shlex.split(profiles[LaunchProfile.DEFAULT]))


def _launch_profile_name() -> str:
    """The profile the launch arguments boot."""
    arguments = _launch_arguments()
    name = _profile_in(arguments)
    if name is None:
        raise DeepSeekStackError(_LAUNCH_ARGUMENTS_TEMPLATE.format(arguments=arguments))
    return name


def _profile_in(arguments: Sequence[str]) -> str | None:
    for index, argument in enumerate(arguments[:-1]):
        if argument == _PROFILE_FLAG:
            return arguments[index + 1]
    return None


def _build_harness_home(operator_home: Path, gate_home: Path) -> None:
    """Share the operator's profiles and credentials; copy the remaining configuration; start the data stores empty."""
    (gate_home / _PROFILES_DIRECTORY).symlink_to(operator_home / _PROFILES_DIRECTORY)
    credentials = operator_home / _CREDENTIALS_FILE
    if credentials.exists():
        (gate_home / _CREDENTIALS_FILE).symlink_to(credentials)
    for entry in sorted(operator_home.iterdir()):
        if entry.name in _NOT_COPIED:
            continue
        target = gate_home / entry.name
        if entry.name == _PRESETS_DIRECTORY:
            # Resolved so a linked presets directory is copied, never edited through the link below.
            shutil.copytree(entry.resolve(), target, symlinks=True, ignore=_ignore_sockets)
        elif entry.is_symlink():
            target.symlink_to(os.readlink(entry))
        elif entry.is_dir():
            shutil.copytree(entry, target, symlinks=True, ignore=_ignore_sockets)
        else:
            shutil.copy2(entry, target)
    for preset_hooks in (gate_home / _PRESETS_DIRECTORY).glob(_PRESET_HOOKS_GLOB_TEMPLATE.format(name=_HOOKS_FILE)):
        preset_hooks.unlink()


# guard: loose-dict-func - hooks.json is a dynamic external wire shape
def _write_gate_hooks(path: Path, signals: Path) -> None:
    """The gate's own global hook layer: replay a decision at prompt submit, record stops and stop failures."""
    commands = {
        HookEvent.USER_PROMPT_SUBMIT: _HOOK_REPLAY_COMMAND.format(
            path=shlex.quote(str(signals / _PROMPT_CONTEXT_FILE))
        ),
        HookEvent.STOP: _HOOK_APPEND_COMMAND.format(path=shlex.quote(str(signals / _STOP_FILE))),
        HookEvent.STOP_FAILURE: _HOOK_APPEND_COMMAND.format(path=shlex.quote(str(signals / _STOP_FAILURE_FILE))),
    }
    hooks = {
        event.value: [
            {
                _HOOK_MATCHER_KEY: _HOOK_MATCH_ALL,
                _HOOKS_KEY: [
                    {_HOOK_TYPE_KEY: _HOOK_TYPE_COMMAND, _HOOK_COMMAND_KEY: command, _HOOK_UNSANDBOXED_KEY: True}
                ],
            }
        ]
        for event, command in commands.items()
    }
    path.write_text(json.dumps({_HOOKS_KEY: hooks}, indent=_JSON_INDENT))


# guard: loose-dict-func - the hook decision is a dynamic external wire shape
def _hook_context_decision(token: str) -> str:
    return json.dumps(
        {
            _HOOK_SPECIFIC_OUTPUT_FIELD: {
                _HOOK_EVENT_NAME_FIELD: HookEvent.USER_PROMPT_SUBMIT.value,
                _ADDITIONAL_CONTEXT_FIELD: _HOOK_CONTEXT_TEXT_TEMPLATE.format(token=token),
            }
        }
    )


def _app_kind(profile: str) -> AppKind:
    """The app kind a profile declares through its bundle list; the first recognized app bundle decides."""
    manifest_path = harness_home() / _PROFILES_DIRECTORY / profile / _MANIFEST_FILE
    manifest = read_manifest(manifest_path)
    section = manifest.get(_PROFILE_FIELD)
    profile_section = section.get(_PROFILE_SECTION) if isinstance(section, dict) else None
    bundles = profile_section.get(_BUNDLES_FIELD) if isinstance(profile_section, dict) else None
    if isinstance(bundles, list):
        for bundle in bundles:
            if isinstance(bundle, str) and bundle in _BUNDLE_APP_KINDS:
                return _BUNDLE_APP_KINDS[bundle]
    return AppKind.OTHER


def _parse_observation(decoded: str) -> PaneObservation | None:
    if _OBSERVATION_MARKER not in decoded:
        return None
    text, cursor_text = decoded.rsplit(_OBSERVATION_MARKER, 1)
    fields = cursor_text.split()
    if len(fields) != _CURSOR_FIELD_COUNT or fields[0] != _CURSOR_VISIBLE_FLAG:
        return PaneObservation(text=text, cursor=None)
    row_text, column_text = fields[1:]
    if not row_text.isdigit() or not column_text.isdigit():
        return PaneObservation(text=text, cursor=None)
    return PaneObservation(text=text, cursor=PaneCursor(row=int(row_text), column=int(column_text)))


def _has_event(stdout: str, event: str) -> bool:
    """Whether the newline-delimited run events include one of the named type."""
    for line in stdout.splitlines():
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict) and document.get(_EVENT_TYPE_FIELD) == event:
            return True
    return False


def _record_count(path: Path, check: GateCheck) -> int:
    return len([line for line in _read_text(path, check).splitlines() if line.strip()])


def _read_text(path: Path, check: GateCheck) -> str:
    try:
        return path.read_text(encoding=_OUTPUT_ENCODING, errors=_ERRORS_REPLACE)
    except OSError as error:
        raise _CheckFailed(check, _FILE_READ_FAILURE_TEMPLATE.format(path=path, error=error)) from error


def _tail(text: str) -> str:
    return text.strip()[-_DETAIL_TAIL_CHARS:]


def _wait_until(condition: Callable[[], bool], timeout_seconds: float) -> bool:
    """Poll the condition until it holds or the bound passes."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if condition():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_INTERVAL_SECONDS)


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """End a gate process and everything it started."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        return
