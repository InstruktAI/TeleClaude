#!/usr/bin/env python3
"""Inert stand-in for the Claude Code executable at the external agent-CLI process boundary.

The runtime-acceptance profile installs this program as ``claude`` in the disposable home's user-bin directory. It is
what the platform's own session start launches in the pane it creates: it draws a framed composer, reports its
SessionStart and UserPromptSubmit hooks by running the receiver commands the supported installation registered in the
disposable Claude settings, accepts the platform's input through that composer, and asks the platform who it is with a
fresh ``telec sessions show self --full`` process from inside the pane.

It imports only the standard library. It creates no session record, caller identity, authentication state or
application event, and imports no application module: everything it reports is the output of the public executables it
runs. Metadata queries (``--version``, ``update``) print or do nothing and exit; they emit no hooks and start no loop.

Control files live in the directory named by the sidecar configuration the controller wrote beside the profile's home.
The controller writes the case-start timestamp and the barrier release there; this program writes the composer marker,
its input log and its frames there. All timestamps are ``time.monotonic()`` readings, which share one clock across
the processes of a machine.
"""

from __future__ import annotations

import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import FrameType
from typing import Final

CONFIG_RELATIVE_PATH: Final = Path(".local") / "share" / "claude-fixture" / "config.json"
SETTINGS_RELATIVE_PATH: Final = Path(".claude") / "settings.json"
PROJECTS_RELATIVE_PATH: Final = Path(".claude") / "projects"
CONFIG_CONTROL_DIRECTORY: Final = "control_directory"
CONFIG_VERSION: Final = "version"
VERSION_FLAG: Final = "--version"
UPDATE_COMMAND: Final = "update"
USER_FACING_NAME: Final = "claude"
TELEC_COMMAND: Final = "telec"
SELF_PROBE_ARGUMENTS: Final = ("sessions", "show", "self", "--full")

CASE_START_FILE: Final = "case_start"
RELEASE_FILE: Final = "release"
COMPOSER_FILE: Final = "composer_at"
BARRIER_FILE: Final = "barrier.json"
LAUNCH_FILE: Final = "launch.json"
INPUT_LOG_FILE: Final = "inputs.jsonl"
FRAMES_DIRECTORY: Final = "frames"
FRAME_TEMP_PREFIX: Final = "."
FRAME_SUFFIX: Final = ".json"
FRAME_COMPLETE_SUFFIX: Final = ".complete"
FRAME_SESSION_START: Final = "session_start"
FRAME_PROMPT_SUBMIT: Final = "prompt_submit"
FRAME_SELF_PROBE: Final = "self_probe"
PLAN_FILE: Final = "plan.json"
PLAN_COMMANDS_FIELD: Final = "commands"
PLAN_NAME_FIELD: Final = "name"
PLAN_ARGV_FIELD: Final = "argv"
PLAN_FRAME_PREFIX: Final = "cmd_"
PLAN_TIMEOUT_SECONDS: Final = 60

HOOK_SESSION_START: Final = "SessionStart"
HOOK_PROMPT_SUBMIT: Final = "UserPromptSubmit"
HOOKS_FIELD: Final = "hooks"
COMMAND_FIELD: Final = "command"
SHELL_PATH: Final = "/bin/sh"
SHELL_COMMAND_OPTION: Final = "-c"
PERMISSION_MODE: Final = "bypassPermissions"
SESSION_START_SOURCE: Final = "startup"

BARRIER_AFTER_CASE_START_SECONDS: Final = 45.0
BARRIER_AFTER_COMPOSER_SECONDS: Final = 15.0
HOOK_TIMEOUT_SECONDS: Final = 60
PROBE_TIMEOUT_SECONDS: Final = 60
CAPTURE_LIMIT: Final = 4096
POLL_SECONDS: Final = 0.05
READ_SIZE: Final = 65536
DEFAULT_COLUMNS: Final = 120
ENCODING: Final = "utf-8"

RULE_CHARACTER: Final = chr(0x2500)
PROMPT_MARKER: Final = chr(0x276F)
BANNER_LINES: Final = ("claude (runtime acceptance fixture)",)
ESC: Final = "\x1b"
CLEAR_AND_HOME: Final = f"{ESC}[2J{ESC}[H"
BRACKETED_PASTE_ON: Final = f"{ESC}[?2004h"
BRACKETED_PASTE_OFF: Final = f"{ESC}[?2004l"
PASTE_START: Final = f"{ESC}[200~"
PASTE_END: Final = f"{ESC}[201~"
CARRIAGE_RETURN: Final = "\r"
LINE_FEED: Final = "\n"
CRLF: Final = "\r\n"

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _load_config() -> Mapping[str, str]:
    raw = json.loads((_home() / CONFIG_RELATIVE_PATH).read_text(encoding=ENCODING))
    return {str(key): str(value) for key, value in raw.items()}


def _bounded(text: str) -> str:
    return text[:CAPTURE_LIMIT]


class _Control:
    """The controller-owned directory this program reports into and reads its barrier from."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.frames = directory / FRAMES_DIRECTORY
        self.frames.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: JsonObject) -> None:
        temporary = self.directory / f"{FRAME_TEMP_PREFIX}{name}.tmp"
        with temporary.open("w", encoding=ENCODING) as handle:
            handle.write(json.dumps(payload) + LINE_FEED)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.directory / name)

    def write_frame(self, name: str, payload: JsonObject) -> None:
        """Install a whole frame atomically, then emit its distinct completion marker."""
        temporary = self.frames / f"{FRAME_TEMP_PREFIX}{name}{FRAME_SUFFIX}.tmp"
        with temporary.open("w", encoding=ENCODING) as handle:
            handle.write(json.dumps(payload) + LINE_FEED)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.frames / f"{name}{FRAME_SUFFIX}")
        marker = self.frames / f"{name}{FRAME_COMPLETE_SUFFIX}"
        marker.write_text(LINE_FEED, encoding=ENCODING)

    def append_input(self, entry: JsonObject) -> None:
        with (self.directory / INPUT_LOG_FILE).open("a", encoding=ENCODING) as handle:
            handle.write(json.dumps(entry) + LINE_FEED)
            handle.flush()
            os.fsync(handle.fileno())

    def write_number(self, name: str, value: float) -> None:
        """Install a plain monotonic reading atomically, so a reader never sees it half written."""
        temporary = self.directory / f"{FRAME_TEMP_PREFIX}{name}.tmp"
        temporary.write_text(f"{value!r}{LINE_FEED}", encoding=ENCODING)
        os.replace(temporary, self.directory / name)

    def read_number(self, name: str) -> float | None:
        try:
            return float((self.directory / name).read_text(encoding=ENCODING).strip())
        except (OSError, ValueError):
            return None

    def read_json(self, name: str) -> JsonObject | None:
        try:
            value = json.loads((self.directory / name).read_text(encoding=ENCODING))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def exists(self, name: str) -> bool:
        return (self.directory / name).exists()


def _registered_commands(event: str) -> list[str]:
    """The receiver commands the supported installation registered for a hook event in the Claude settings."""
    try:
        settings = json.loads((_home() / SETTINGS_RELATIVE_PATH).read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return []
    blocks = settings.get(HOOKS_FIELD, {}).get(event, []) if isinstance(settings, dict) else []
    commands: list[str] = []
    for block in blocks if isinstance(blocks, list) else []:
        for hook in block.get(HOOKS_FIELD, []) if isinstance(block, dict) else []:
            if isinstance(hook, dict) and isinstance(hook.get(COMMAND_FIELD), str):
                commands.append(str(hook[COMMAND_FIELD]))
    return commands


def _run(argv: Sequence[str], *, timeout_seconds: float, stdin_text: str = "") -> JsonObject:
    """Run one command in this pane's environment and report its bounded outcome."""
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        outcome: JsonObject = {
            "argv": [_bounded(part) for part in argv],
            "exit_status": completed.returncode,
            "stdout": _bounded(completed.stdout),
            "stderr": _bounded(completed.stderr),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        outcome = {"argv": [_bounded(part) for part in argv], "exit_status": None, "timed_out": True}
    except OSError as error:
        outcome = {"argv": [_bounded(part) for part in argv], "exit_status": None, "error": type(error).__name__}
    outcome["duration_seconds"] = time.monotonic() - started
    return outcome


class _Fixture:
    """One launch of the inert agent: its terminal, its barrier, its hooks and its self probe."""

    def __init__(self, control: _Control) -> None:
        self.control = control
        self.native_session_id = str(uuid.uuid4())
        self.cwd = os.path.realpath(os.getcwd())
        self.transcript_path = self._transcript_path()
        self.draft = ""
        self.composer_at: float | None = None
        self.hook_started = False
        self.first_prompt_handled = False
        self.running = True
        self.row = len(BANNER_LINES) + 2

    def _transcript_path(self) -> Path:
        project_directory = self.cwd.replace(os.sep, "-")
        return _home() / PROJECTS_RELATIVE_PATH / project_directory / f"{self.native_session_id}.jsonl"

    def _payload(self, event: str, **extra: JsonValue) -> JsonObject:
        payload: JsonObject = {
            "session_id": self.native_session_id,
            "transcript_path": str(self.transcript_path),
            "cwd": self.cwd,
            "permission_mode": PERMISSION_MODE,
            "hook_event_name": event,
        }
        payload.update(extra)
        return payload

    def record_launch(self) -> None:
        resolved = shutil.which(USER_FACING_NAME)
        self.control.write_json(
            LAUNCH_FILE,
            {
                "executable": os.path.realpath(__file__),
                "resolved_command": os.path.realpath(resolved) if resolved else None,
                "native_session_id": self.native_session_id,
                "transcript_path": str(self.transcript_path),
                "cwd": self.cwd,
                "pid": os.getpid(),
                "launched_at": time.monotonic(),
            },
        )

    def draw(self) -> None:
        columns = shutil.get_terminal_size((DEFAULT_COLUMNS, 40)).columns
        rule = RULE_CHARACTER * columns
        rows = [*BANNER_LINES, rule, f"{PROMPT_MARKER} {self.draft}", rule]
        screen = CLEAR_AND_HOME + CRLF.join(rows)
        cursor = f"{ESC}[{self.row};{3 + len(self.draft)}H"
        sys.stdout.write(screen + cursor)
        sys.stdout.flush()

    def deadline(self) -> float | None:
        """The barrier's hard deadline: the earlier of case-start+45 s and composer-marker+15 s."""
        if self.composer_at is None:
            return None
        deadline = self.composer_at + BARRIER_AFTER_COMPOSER_SECONDS
        case_start = self.control.read_number(CASE_START_FILE)
        if case_start is not None:
            deadline = min(deadline, case_start + BARRIER_AFTER_CASE_START_SECONDS)
        return deadline

    def _run_hook(self, event: str, frame: str, **extra: JsonValue) -> JsonObject:
        commands = _registered_commands(event)
        payload = json.dumps(self._payload(event, **extra))
        runs = [
            _run([SHELL_PATH, SHELL_COMMAND_OPTION, command], timeout_seconds=HOOK_TIMEOUT_SECONDS, stdin_text=payload)
            for command in commands
        ]
        frame_payload: JsonObject = {
            "event": event,
            "registered": bool(commands),
            "native_session_id": self.native_session_id,
            "input": dict(extra),
            "runs": list(runs),
        }
        self.control.write_frame(frame, frame_payload)
        return frame_payload

    def release_if_due(self) -> None:
        if self.hook_started or self.composer_at is None:
            return
        now = time.monotonic()
        deadline = self.deadline()
        released = self.control.exists(RELEASE_FILE)
        if not released and (deadline is None or now < deadline):
            return
        self.control.write_json(
            BARRIER_FILE,
            {"released_by": "controller" if released else "deadline", "at": now, "deadline": deadline},
        )
        self.hook_started = True
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_hook(HOOK_SESSION_START, FRAME_SESSION_START, source=SESSION_START_SOURCE)
        self.transcript_path.touch()

    def submit(self, text: str) -> None:
        entry: JsonObject = {"at": time.monotonic(), "text": text, "hook_started": self.hook_started}
        self.control.append_input(entry)
        self.draft = ""
        self.draw()
        if not self.hook_started or self.first_prompt_handled:
            return
        self.first_prompt_handled = True
        with self.transcript_path.open("a", encoding=ENCODING) as transcript:
            line: JsonObject = {
                "type": "user",
                "sessionId": self.native_session_id,
                "message": {"role": "user", "content": text},
            }
            transcript.write(json.dumps(line) + LINE_FEED)
        self._run_hook(HOOK_PROMPT_SUBMIT, FRAME_PROMPT_SUBMIT, prompt=text)
        telec = shutil.which(TELEC_COMMAND)
        probe = _run([telec or TELEC_COMMAND, *SELF_PROBE_ARGUMENTS], timeout_seconds=PROBE_TIMEOUT_SECONDS)
        self.control.write_frame(FRAME_SELF_PROBE, {"telec": telec, "run": probe})
        self._run_plan()

    def _run_plan(self) -> None:
        """Run the controller\'s reviewed public commands, each as a fresh process of this pane, and report each.

        The plan names only the public ``telec`` executable with its arguments. It carries no identity, token, header
        or environment: the pane\'s own environment is the caller\'s identity, as for any command a driver runs.
        """
        plan = self.control.read_json(PLAN_FILE)
        commands = plan.get(PLAN_COMMANDS_FIELD) if plan is not None else None
        if not isinstance(commands, list):
            return
        for command in commands:
            if not isinstance(command, dict):
                continue
            name = command.get(PLAN_NAME_FIELD)
            argv = command.get(PLAN_ARGV_FIELD)
            if not isinstance(name, str) or not name.isalnum() or not isinstance(argv, list) or not argv:
                continue
            arguments = [part for part in argv if isinstance(part, str)]
            if len(arguments) != len(argv) or arguments[0] != TELEC_COMMAND:
                continue
            resolved = shutil.which(TELEC_COMMAND)
            run = _run([resolved or TELEC_COMMAND, *arguments[1:]], timeout_seconds=PLAN_TIMEOUT_SECONDS)
            reported: list[JsonValue] = [*arguments]
            self.control.write_frame(
                f"{PLAN_FRAME_PREFIX}{name}", {"name": name, "argv": reported, "telec": resolved, "run": run}
            )

    def feed(self, data: str, state: _InputState) -> None:
        """Consume terminal input: pasted or typed text builds the draft, Enter submits it."""
        index = 0
        while index < len(data):
            if data.startswith(PASTE_START, index):
                state.pasting = True
                index += len(PASTE_START)
            elif data.startswith(PASTE_END, index):
                state.pasting = False
                index += len(PASTE_END)
            elif data[index] in (CARRIAGE_RETURN, LINE_FEED) and not state.pasting:
                if self.draft:
                    self.submit(self.draft)
                index += 1
            elif data[index] == ESC:
                index += 1
            else:
                self.draft += data[index]
                index += 1
        self.draw()


class _InputState:
    """Whether the terminal is inside a bracketed paste."""

    def __init__(self) -> None:
        self.pasting = False


def _interactive(control: _Control) -> int:
    fixture = _Fixture(control)
    fixture.record_launch()
    descriptor = sys.stdin.fileno()
    saved = termios.tcgetattr(descriptor)

    def stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        fixture.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    tty.setraw(descriptor)
    try:
        sys.stdout.write(BRACKETED_PASTE_ON)
        fixture.draw()
        fixture.composer_at = time.monotonic()
        control.write_number(COMPOSER_FILE, fixture.composer_at)
        selector = selectors.DefaultSelector()
        selector.register(descriptor, selectors.EVENT_READ)
        state = _InputState()
        pending = b""
        while fixture.running:
            fixture.release_if_due()
            if not selector.select(POLL_SECONDS):
                continue
            chunk = os.read(descriptor, READ_SIZE)
            if not chunk:
                break
            pending += chunk
            try:
                text = pending.decode(ENCODING)
            except UnicodeDecodeError:
                continue
            pending = b""
            fixture.feed(text, state)
    finally:
        sys.stdout.write(BRACKETED_PASTE_OFF)
        sys.stdout.flush()
        termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)
    return 0


def main(arguments: Sequence[str]) -> int:
    """Answer metadata queries, or run the interactive inert agent."""
    config = _load_config()
    first = arguments[0] if arguments else ""
    if first == VERSION_FLAG:
        print(config[CONFIG_VERSION])
        return 0
    if first == UPDATE_COMMAND:
        return 0
    return _interactive(_Control(Path(config[CONFIG_CONTROL_DIRECTORY])))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
