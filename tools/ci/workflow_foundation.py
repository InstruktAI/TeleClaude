"""Journey F0 of the workflow acceptance: the native fixture foundation.

The journey's assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/foundation-startup-review-draft.md`, approved at exact SHA-256
8b9e3768530263268e1a9ddb920b1bf09e656046943097158fbb72b4af1c357c, authority
`local/projects/teleclaude/spec/feature/agent_runtime/runtime-acceptance` Workflow journeys). It proves a disposable
Linux native-fixture binding, a public terminal's refusal as a non-session, a platform-created session's startup
admission, its self identity from inside its own pane, and its closure. It proves no workflow claim, helper sweep,
admission, model behaviour or provider behaviour.

The inert executable (`native_claude_fixture.py`) sits at the external agent-CLI process boundary: the platform creates
the session, the pane and the launch, and every observation below is a public read through a fresh CLI process or the
fixture's own report of the public executables it ran. This controller creates no session record, caller identity,
authentication state or application event, and imports no application module.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

type EvidenceValue = str | int | float | bool | None | list[EvidenceValue] | dict[str, EvidenceValue]
type EvidenceObject = dict[str, EvidenceValue]

FIXTURE_SOURCE: Final = Path("tools") / "ci" / "native_claude_fixture.py"
USER_BIN_RELATIVE: Final = Path(".local") / "bin"
FIXTURE_NAME: Final = "claude"
CONFIG_RELATIVE: Final = Path(".local") / "share" / "claude-fixture" / "config.json"
CONTROL_DIRECTORY_NAME: Final = "native-fixture-control"
VENDOR_VERSION: Final = "2.1.289 (Claude Code)"
CONFIG_CONTROL_DIRECTORY: Final = "control_directory"
CONFIG_VERSION: Final = "version"
FIXTURE_MODE: Final = 0o755
SHELL_EXECUTABLE: Final = "/bin/sh"
LOGIN_SHELL_EXECUTABLE: Final = "/bin/bash"
COMMAND_V_SCRIPT: Final = "command -v claude"
LOGIN_CONTEXT_SCRIPT: Final = (
    'printf "PATH=%s\\n" "$PATH"; ls -a "$HOME" | tr "\\n" " "; printf "\\n"; ls -a "$HOME/.local/bin" | tr "\\n" " "'
)
LOGIN_SHELL_OPTION: Final = "-lic"
SHELL_COMMAND_OPTION: Final = "-c"
LOGIN_BASE_PATH: Final = "/usr/local/bin:/usr/bin:/bin"
GIT_EXECUTABLE: Final = "git"
GIT_INIT_ARGUMENTS: Final = ("init", "-q")
GIT_DIRECTORY: Final = ".git"
PROCESS_TIMEOUT_SECONDS: Final = 30
PATH_ROOT: Final = "/"
LOGIN_PROFILE_NAMES: Final = (".bash_profile", ".bash_login", ".profile")
LOGIN_PATH_LINE: Final = 'case ":$PATH:" in *":{directory}:"*) ;; *) export PATH="{directory}:$PATH" ;; esac'
LINE_FEED: Final = "\n"
CLI_TIMEOUT_SECONDS: Final = 60
START_OBSERVATION_CAP_SECONDS: Final = 900
POLL_SECONDS: Final = 1.0
RECORD_POLL_SECONDS: Final = 2.0

CASE_START_FILE: Final = "case_start"
RELEASE_FILE: Final = "release"
COMPOSER_FILE: Final = "composer_at"
BARRIER_FILE: Final = "barrier.json"
LAUNCH_FILE: Final = "launch.json"
INPUT_LOG_FILE: Final = "inputs.jsonl"
FRAMES_DIRECTORY: Final = "frames"
FRAME_SESSION_START: Final = "session_start"
FRAME_PROMPT_SUBMIT: Final = "prompt_submit"
FRAME_SELF_PROBE: Final = "self_probe"
FRAME_SUFFIX: Final = ".json"
FRAME_HOOK_KEYS: Final = frozenset({"event", "registered", "native_session_id", "input", "runs"})
FRAME_SELF_PROBE_KEYS: Final = frozenset({"telec", "run"})
FRAME_COMMAND_PREFIX: Final = "cmd_"
FRAME_COMMAND_KEYS: Final = frozenset({"name", "argv", "telec", "run"})
FRAME_WRITE_PREFIX: Final = "cmd_write"
FRAME_WRITE_OK: Final = "ok"
FRAME_WRITE_CWD: Final = "cwd"
FRAME_WRITE_ROWS: Final = "writes"
FRAME_WRITE_ERROR: Final = "error"
FRAME_WRITE_COMPLETED: Final = "written"
FRAME_WRITE_PATH: Final = "path"
FRAME_WRITE_MODE: Final = "mode"
FRAME_WRITE_BYTES: Final = "bytes"
FRAME_WRITE_SHA: Final = "sha256"
FRAME_WRITE_SUCCESS_KEYS: Final = frozenset({FRAME_WRITE_OK, FRAME_WRITE_CWD, FRAME_WRITE_ROWS})
FRAME_WRITE_FAILURE_KEYS: Final = frozenset({FRAME_WRITE_OK, FRAME_WRITE_ERROR, FRAME_WRITE_COMPLETED})
FRAME_WRITE_ROW_KEYS: Final = frozenset({FRAME_WRITE_PATH, FRAME_WRITE_MODE, FRAME_WRITE_BYTES, FRAME_WRITE_SHA})
FRAME_COMPLETE_SUFFIX: Final = ".complete"

WINDOW_AFTER_CASE_START_SECONDS: Final = 45.0
WINDOW_AFTER_COMPOSER_SECONDS: Final = 15.0
QUIET_BEFORE_SAMPLE_SECONDS: Final = 5.0
SAMPLE_BOUND_SECONDS: Final = 10.0
MINIMUM_SAMPLE_SECONDS: Final = 1.0

TELEC: Final = "bin/telec"
SESSIONS: Final = "sessions"
SHOW: Final = "show"
SELF_TARGET: Final = "self"
FULL_FLAG: Final = "--full"
START: Final = "start"
END: Final = "end"
PATH_OPTION: Final = "--path"
AGENT_OPTION: Final = "--agent"
MODE_OPTION: Final = "--mode"
MESSAGE_OPTION: Final = "--message"
AGENT_NAME: Final = "claude"
FAST_MODE: Final = "fast"
OPERATIONS: Final = "operations"
GET: Final = "get"

NOT_A_SESSION_PHRASE: Final = "not a TeleClaude session"
STATUS_SUCCESS: Final = "success"
OPERATION_COMPLETED: Final = "completed"
OPERATION_FAILED_STATES: Final = frozenset({"failed", "stale", "cancelled"})
INITIALIZING: Final = "initializing"
ACTIVE: Final = "active"
CLOSED: Final = "closed"
MESSAGE_PREFIX: Final = "fixtureprobe"
MESSAGE_SUFFIX_LENGTH: Final = 12

FIELD_SESSION_ID: Final = "session_id"
FIELD_STATUS: Final = "status"
FIELD_TMUX: Final = "tmux_session_name"
FIELD_AGENT: Final = "agent"
FIELD_PROJECT: Final = "project_path"
FIELD_ACTIVE_AGENT: Final = "active_agent"
FIELD_LIFECYCLE: Final = "lifecycle_status"
FIELD_OBSERVED: Final = "runtime_start_observed"
FIELD_CLOSED_AT: Final = "closed_at"
FIELD_NATIVE: Final = "native_session_id"
FIELD_OPERATION: Final = "operation_id"
FIELD_STATE: Final = "state"

BINDING_FAILURE: Final = "fixture binding failure: {detail}"
PLATFORM_FAILURE: Final = "platform assertion failure: {detail}"
DETAIL_PATH_MISMATCH: Final = "{where} resolves `claude` to {found!r}, not the owned fixture {owned!r}"
DETAIL_NO_CLAUDE: Final = "{where} resolves no `claude` executable"
DETAIL_CONTEXT: Final = " (login context: {context})"
DETAIL_WINDOW: Final = "control window exceeded: {detail}"
DETAIL_NO_FRAME: Final = "the fixture reported no {frame} frame within {seconds} seconds"
DETAIL_FRAME_INVALID: Final = "the {frame} frame is malformed or truncated"
DETAIL_HOOK_UNREGISTERED: Final = "the supported installation registered no {frame} receiver in the Claude settings"
DETAIL_HOOK_FAILED: Final = "the installed {frame} receiver did not exit successfully: {run}"
DETAIL_EXECUTABLE: Final = "the launched fixture ran as {found!r}, not the owned {owned!r}"
DETAIL_NOT_SESSION: Final = "terminal `sessions show self` did not refuse as a non-session: exit {status}, {output!r}"
DETAIL_START_RESULT: Final = "the public create result is not a success naming a session, a pane and claude: {result!r}"
DETAIL_NEGATIVE: Final = "the pre-hook record or input monitor shows startup: {record!r}, inputs {inputs!r}"
DETAIL_RECORD: Final = (
    "the flat session record never reached the required startup state within {seconds} seconds: {record!r}"
)
DETAIL_INPUT_TEXT: Final = "the fixture received {received!r}, not the startup message"
DETAIL_SELF_PROBE: Final = "the fixture's own `sessions show self` returned {output!r}, not its session"
DETAIL_END: Final = "session end: {detail}"
DETAIL_CLEANUP: Final = "the owned fixture resources could not be removed: {detail}"


class FoundationFailure(RuntimeError):
    """An assertion about the platform failed."""


class FixtureBindingFailure(RuntimeError):
    """The fixture binding, not the platform, failed to hold: the case proves nothing either way."""


@dataclass(frozen=True)
class Outcome:
    """The bounded result of one command: its exit status (None when it did not finish) and its output."""

    exit_status: int | None
    output: str
    stderr: str = ""
    diagnostics: str = ""
    duration_seconds: float = 0.0

    def evidence(self, argv: Sequence[str]) -> EvidenceObject:
        """Retain the original native result before parsing, including failures and diagnostics."""
        return {
            "argv": list(argv),
            "exit_status": self.exit_status,
            "duration_seconds": self.duration_seconds,
            "stdout": self.output,
            "stderr": self.stderr,
            "diagnostics": self.diagnostics,
        }


class FoundationHost(Protocol):
    """What the journey needs from the profile that runs it."""

    @property
    def environment(self) -> Mapping[str, str]:
        """The profile\'s allowlisted child environment."""
        ...

    def cli(self, argv: Sequence[str], timeout_seconds: float, *, retain: bool = True) -> Outcome:
        """Run one fresh public CLI process on the authenticated owner terminal.

        ``retain`` keeps its bounded evidence in the report; a poll that repeats until a state is reached does not.
        """
        ...

    def process(
        self, argv: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout_seconds: float
    ) -> Outcome:
        """Run one bounded child process of the controller."""
        ...

    def note(self, argv: Sequence[str], outcome: Outcome, diagnostics: str) -> None:
        """Retain bounded evidence of a command the fixture ran for the journey."""
        ...


@dataclass(frozen=True)
class FixtureSetup:
    """The owned inert executable and the control directory it reports into."""

    executable: Path
    configuration: Path
    control: Path


def fixture_paths(home: Path, temporary_root: Path) -> FixtureSetup:
    """Where the profile's fixture and control directory live."""
    return FixtureSetup(
        executable=home / USER_BIN_RELATIVE / FIXTURE_NAME,
        configuration=home / CONFIG_RELATIVE,
        control=temporary_root / CONTROL_DIRECTORY_NAME,
    )


def install_fixture(source_root: Path, setup: FixtureSetup) -> None:
    """Install the inert executable and its sidecar configuration, before the supported installation runs."""
    setup.executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_root / FIXTURE_SOURCE, setup.executable)
    setup.executable.chmod(FIXTURE_MODE)
    setup.configuration.parent.mkdir(parents=True, exist_ok=True)
    setup.control.mkdir(parents=True, exist_ok=True)
    setup.configuration.write_text(
        json.dumps({CONFIG_CONTROL_DIRECTORY: str(setup.control), CONFIG_VERSION: VENDOR_VERSION}),
        encoding="utf-8",
    )


def remove_fixture(setup: FixtureSetup) -> list[str]:
    """Remove only what the profile installed; report every failure."""
    failures: list[str] = []
    for path in (setup.executable, setup.configuration):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            failures.append(f"{path.name}: {type(error).__name__}")
    try:
        shutil.rmtree(setup.control, ignore_errors=False)
    except FileNotFoundError:
        pass
    except OSError as error:
        failures.append(f"{setup.control.name}: {type(error).__name__}")
    return failures


def require_owned_resolution(
    host: FoundationHost, setup: FixtureSetup, environment: Mapping[str, str], cwd: Path, where: str, login: bool
) -> None:
    """Fail unless `command -v claude` resolves to the owned fixture under exactly this environment."""
    argv = (
        (LOGIN_SHELL_EXECUTABLE, LOGIN_SHELL_OPTION, COMMAND_V_SCRIPT)
        if login
        else (SHELL_EXECUTABLE, SHELL_COMMAND_OPTION, COMMAND_V_SCRIPT)
    )
    outcome = host.process(argv, cwd, environment, PROCESS_TIMEOUT_SECONDS)
    paths = [line.strip() for line in outcome.output.splitlines() if line.strip().startswith(PATH_ROOT)]
    found = paths[-1] if paths else ""
    if outcome.exit_status != 0 or not found:
        context = host.process(
            (LOGIN_SHELL_EXECUTABLE, LOGIN_SHELL_OPTION, LOGIN_CONTEXT_SCRIPT),
            cwd,
            environment,
            PROCESS_TIMEOUT_SECONDS,
        )
        detail = DETAIL_NO_CLAUDE.format(where=where) + DETAIL_CONTEXT.format(context=context.output.strip()[-600:])
        raise FixtureBindingFailure(BINDING_FAILURE.format(detail=detail))
    if Path(found).resolve() != setup.executable.resolve():
        detail = DETAIL_PATH_MISMATCH.format(where=where, found=found, owned=str(setup.executable))
        raise FixtureBindingFailure(BINDING_FAILURE.format(detail=detail))


def put_tools_on_login_path(home: Path, directories: Sequence[Path]) -> str:
    """Make the owner\'s login shell find the user-bin directory and the tools the CLI needs, as a user\'s profile does.

    A login shell of the disposable home starts from the system PATH and adds what the user\'s own profile adds; the
    platform captures the agent shells\' PATH from that login shell. A hosted image\'s profile adds neither the
    user-bin directory nor the directory of the `uv` the `telec` launcher runs, so this writes the same guarded line the
    supported installer suggests for the user-bin directory, once per directory, to the file bash reads first for a
    login shell, in the disposable home only. A directory a profile already names is left alone. Returns the file and
    the lines written, or an empty string.
    """
    for name in LOGIN_PROFILE_NAMES:
        profile = home / name
        if profile.exists():
            break
    else:
        profile = home / LOGIN_PROFILE_NAMES[-1]
    existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
    lines = [LOGIN_PATH_LINE.format(directory=str(directory)) for directory in directories]
    missing = [line for line in lines if line not in existing]
    if not missing:
        return ""
    prefix = LINE_FEED if existing and not existing.endswith(LINE_FEED) else ""
    with profile.open("a", encoding="utf-8") as handle:
        handle.write(prefix + LINE_FEED.join(missing) + LINE_FEED)
    return f"{profile.name}: {' ; '.join(missing)}"


def owner_login_environment(base: Mapping[str, str]) -> dict[str, str]:
    """The environment a login shell starts from for the owner: identity and locale only, no inherited PATH."""
    keys = ("HOME", "USER", "LOGNAME", "SHELL", "LANG")
    environment = {key: base[key] for key in keys if key in base}
    environment["PATH"] = LOGIN_BASE_PATH
    return environment


def _whole_frame(text: str) -> Mapping[str, object] | None:
    """Decode a fixture frame strictly: exactly one JSON object and its single terminating newline, nothing else."""
    if not text.endswith(LINE_FEED) or text.endswith(LINE_FEED * 2):
        return None
    try:
        value = json.loads(text[: -len(LINE_FEED)])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _frame_has_shape(name: str, frame: Mapping[str, object]) -> bool:
    """A frame carries the keys its writer emits for that frame name, with the types the writer gives them."""
    if name == FRAME_SELF_PROBE:
        return isinstance(frame.get("run"), dict) and FRAME_SELF_PROBE_KEYS <= frame.keys()
    if name.startswith(FRAME_WRITE_PREFIX):
        success = frame.get(FRAME_WRITE_OK)
        if success is True:
            rows = frame.get(FRAME_WRITE_ROWS)
            return (
                frozenset(frame) == FRAME_WRITE_SUCCESS_KEYS
                and isinstance(frame.get(FRAME_WRITE_CWD), str)
                and isinstance(rows, list)
                and all(
                    isinstance(row, Mapping)
                    and frozenset(row) == FRAME_WRITE_ROW_KEYS
                    and isinstance(row.get(FRAME_WRITE_PATH), str)
                    and isinstance(row.get(FRAME_WRITE_MODE), str)
                    and isinstance(row.get(FRAME_WRITE_BYTES), int)
                    and not isinstance(row.get(FRAME_WRITE_BYTES), bool)
                    and isinstance(row.get(FRAME_WRITE_SHA), str)
                    for row in rows
                )
            )
        if success is False:
            written = frame.get(FRAME_WRITE_COMPLETED)
            return (
                frozenset(frame) == FRAME_WRITE_FAILURE_KEYS
                and isinstance(frame.get(FRAME_WRITE_ERROR), str)
                and isinstance(written, list)
                and all(isinstance(path, str) for path in written)
            )
        return False
    if name.startswith(FRAME_COMMAND_PREFIX):
        return (
            isinstance(frame.get("run"), dict)
            and isinstance(frame.get("argv"), list)
            and FRAME_COMMAND_KEYS <= frame.keys()
        )
    runs = frame.get("runs")
    return FRAME_HOOK_KEYS <= frame.keys() and isinstance(runs, list) and isinstance(frame.get("registered"), bool)


def json_object(output: str) -> Mapping[str, object] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
    return None


def _read_number(path: Path) -> float | None:
    try:
        return float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def platform_failure(detail: str) -> FoundationFailure:
    return FoundationFailure(PLATFORM_FAILURE.format(detail=detail))


def binding_failure(detail: str) -> FixtureBindingFailure:
    return FixtureBindingFailure(BINDING_FAILURE.format(detail=detail))


class Journey:
    """One run of journey F0 against the profile's runtime."""

    def __init__(
        self,
        host: FoundationHost,
        setup: FixtureSetup,
        project: Path,
        owner_email: str,
        message: str | None = None,
        *,
        end_evidence: list[EvidenceValue] | None = None,
    ) -> None:
        self.host = host
        self.setup = setup
        self.project = project.resolve()
        self.owner_email = owner_email
        self.message = message if message is not None else f"{MESSAGE_PREFIX}{uuid.uuid4().hex[:MESSAGE_SUFFIX_LENGTH]}"
        self.session_id = ""
        self.start_evidence: tuple[tuple[str, ...], Outcome] | None = None
        self.end_evidence = end_evidence

    def _reset_control(self) -> None:
        for name in (CASE_START_FILE, RELEASE_FILE, COMPOSER_FILE, BARRIER_FILE, LAUNCH_FILE, INPUT_LOG_FILE):
            (self.setup.control / name).unlink(missing_ok=True)
        shutil.rmtree(self.setup.control / FRAMES_DIRECTORY, ignore_errors=True)

    def record(
        self,
        timeout_seconds: float = CLI_TIMEOUT_SECONDS,
        *,
        retain: bool = True,
        evidence: list[EvidenceValue] | None = None,
    ) -> Mapping[str, object] | None:
        outcome = self.host.cli((TELEC, SESSIONS, SHOW, self.session_id, FULL_FLAG), timeout_seconds, retain=retain)
        if evidence is not None:
            evidence.append(outcome.evidence((TELEC, SESSIONS, SHOW, self.session_id, FULL_FLAG)))
        if outcome.exit_status != 0:
            return None
        return json_object(outcome.output)

    def non_session_control(self) -> None:
        """Step 1: a terminal that is not a session is refused with its terminal identity, and gets no record."""
        outcome = self.host.cli((TELEC, SESSIONS, SHOW, SELF_TARGET, FULL_FLAG), CLI_TIMEOUT_SECONDS)
        record = json_object(outcome.output)
        refused = (
            outcome.exit_status not in (0, None)
            and NOT_A_SESSION_PHRASE in outcome.output
            and self.owner_email in outcome.output
            and (record is None or FIELD_SESSION_ID not in record)
        )
        if not refused:
            raise platform_failure(DETAIL_NOT_SESSION.format(status=outcome.exit_status, output=outcome.output[-400:]))

    def start_session(self, *, case_start_file: bool = True) -> float:
        """Step 2: a public start; its acknowledgement is not startup. Returns the case-start reading."""
        self.start_evidence = None
        self._reset_control()
        case_start = time.monotonic()
        if case_start_file:
            (self.setup.control / CASE_START_FILE).write_text(f"{case_start!r}\n", encoding="utf-8")
        argv = (
            TELEC,
            SESSIONS,
            START,
            PATH_OPTION,
            str(self.project),
            AGENT_OPTION,
            AGENT_NAME,
            MODE_OPTION,
            FAST_MODE,
            MESSAGE_OPTION,
            self.message,
        )
        outcome = self.host.cli(argv, CLI_TIMEOUT_SECONDS)
        self.start_evidence = (argv, outcome)
        result = json_object(outcome.output)
        valid = (
            outcome.exit_status == 0
            and result is not None
            and result.get(FIELD_STATUS) == STATUS_SUCCESS
            and isinstance(result.get(FIELD_SESSION_ID), str)
            and bool(result.get(FIELD_SESSION_ID))
            and bool(result.get(FIELD_TMUX))
            and result.get(FIELD_AGENT) == AGENT_NAME
        )
        if not valid or result is None:
            raise platform_failure(DETAIL_START_RESULT.format(result=outcome.output[-400:]))
        self.session_id = str(result[FIELD_SESSION_ID])
        return case_start

    def negative_control(self, case_start: float) -> None:
        """Step 3: inspect the session inside the pre-hook window, then release the fixture's barrier."""
        composer = self._await_number(self.setup.control / COMPOSER_FILE, case_start + WINDOW_AFTER_CASE_START_SECONDS)
        deadline = min(case_start + WINDOW_AFTER_CASE_START_SECONDS, composer + WINDOW_AFTER_COMPOSER_SECONDS)
        sample_at = composer + QUIET_BEFORE_SAMPLE_SECONDS
        if sample_at >= deadline - MINIMUM_SAMPLE_SECONDS:
            raise binding_failure(
                DETAIL_WINDOW.format(detail="the composer marker arrived too late for a qualifying sample")
            )
        while time.monotonic() < sample_at:
            time.sleep(0.1)
        remaining = deadline - time.monotonic()
        if remaining < MINIMUM_SAMPLE_SECONDS:
            raise binding_failure(DETAIL_WINDOW.format(detail="no time remained for the negative sample"))
        record = self.record(min(SAMPLE_BOUND_SECONDS, remaining))
        completed_at = time.monotonic()
        (self.setup.control / RELEASE_FILE).write_text("1\n", encoding="utf-8")
        if record is None or completed_at >= deadline:
            raise binding_failure(DETAIL_WINDOW.format(detail="the negative sample did not complete inside the window"))
        barrier = self.await_json(self.setup.control / BARRIER_FILE, POLL_SECONDS * 30)
        if barrier.get("released_by") != "controller":
            raise binding_failure(DETAIL_WINDOW.format(detail="the fixture released its own barrier first"))
        inputs = self.inputs()
        unchanged = (
            record.get(FIELD_SESSION_ID) == self.session_id
            and self.same_path(record.get(FIELD_PROJECT))
            and record.get(FIELD_ACTIVE_AGENT) == AGENT_NAME
            and record.get(FIELD_LIFECYCLE) == INITIALIZING
            and record.get(FIELD_OBSERVED) is False
            and record.get(FIELD_CLOSED_AT) is None
        )
        pre_hook_submissions = [entry for entry in inputs if entry.get("hook_started") is False]
        if not unchanged or pre_hook_submissions:
            raise platform_failure(DETAIL_NEGATIVE.format(record=record, inputs=pre_hook_submissions))

    def same_path(self, value: object) -> bool:
        return isinstance(value, str) and Path(value).resolve() == self.project

    def inputs(self) -> list[Mapping[str, object]]:
        path = self.setup.control / INPUT_LOG_FILE
        entries: list[Mapping[str, object]] = []
        if not path.exists():
            return entries
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = json_object(line)
            if parsed is not None:
                entries.append(parsed)
        return entries

    def _await_number(self, path: Path, deadline: float) -> float:
        while time.monotonic() < deadline:
            value = _read_number(path)
            if value is not None:
                return value
            time.sleep(0.1)
        raise binding_failure(DETAIL_WINDOW.format(detail=f"{path.name} never appeared"))

    def await_json(self, path: Path, timeout_seconds: float) -> Mapping[str, object]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if path.exists():
                parsed = json_object(path.read_text(encoding="utf-8"))
                if parsed is not None:
                    return parsed
            time.sleep(0.1)
        raise binding_failure(DETAIL_WINDOW.format(detail=f"{path.name} never appeared"))

    def await_frame(self, name: str, deadline: float) -> Mapping[str, object]:
        """Wait for a frame's completion marker, then parse the whole frame; partial or malformed output fails."""
        frames = self.setup.control / FRAMES_DIRECTORY
        marker = frames / f"{name}{FRAME_COMPLETE_SUFFIX}"
        while time.monotonic() < deadline:
            if marker.exists():
                text = (frames / f"{name}{FRAME_SUFFIX}").read_text(encoding="utf-8")
                parsed = _whole_frame(text)
                if parsed is None or not _frame_has_shape(name, parsed):
                    raise platform_failure(DETAIL_FRAME_INVALID.format(frame=name))
                return parsed
            time.sleep(POLL_SECONDS)
        raise platform_failure(DETAIL_NO_FRAME.format(frame=name, seconds=START_OBSERVATION_CAP_SECONDS))

    def require_hook(self, name: str, frame: Mapping[str, object]) -> None:
        runs = frame.get("runs")
        if frame.get("registered") is not True or not isinstance(runs, list) or not runs:
            raise binding_failure(DETAIL_HOOK_UNREGISTERED.format(frame=name))
        for run in runs:
            if not isinstance(run, dict):
                raise platform_failure(DETAIL_FRAME_INVALID.format(frame=name))
            argv = [str(part) for part in run.get("argv", [])]
            outcome = Outcome(
                run.get("exit_status") if isinstance(run.get("exit_status"), int) else None,
                f"{run.get('stdout', '')}{run.get('stderr', '')}",
            )
            self.host.note(argv, outcome, "")
            if outcome.exit_status != 0 or run.get("timed_out") is True:
                raise platform_failure(DETAIL_HOOK_FAILED.format(frame=name, run=run))

    def positive_start(self, release_at: float, *, captured: list[Mapping[str, object]] | None = None) -> str:
        """Steps 4-5: the hooks run through the installed receivers, the platform delivers MESSAGE, the record turns active."""
        deadline = release_at + START_OBSERVATION_CAP_SECONDS
        launch = self.await_json(self.setup.control / LAUNCH_FILE, POLL_SECONDS * 30)
        owned = str(self.setup.executable.resolve())
        if captured is not None:
            captured.append({"kind": "launch", "value": dict(launch), "owned_executable": owned})
        found = str(launch.get("executable"))
        if Path(found).resolve() != Path(owned) or Path(str(launch.get("resolved_command"))).resolve() != Path(owned):
            raise binding_failure(DETAIL_EXECUTABLE.format(found=launch, owned=owned))
        native = str(launch.get("native_session_id"))
        start_frame = self.await_frame(FRAME_SESSION_START, deadline)
        if captured is not None:
            captured.append({"kind": "session_start", "value": dict(start_frame)})
        self.require_hook(FRAME_SESSION_START, start_frame)
        prompt_frame = self.await_frame(FRAME_PROMPT_SUBMIT, deadline)
        if captured is not None:
            captured.append({"kind": "prompt_submit", "value": dict(prompt_frame)})
        self.require_hook(FRAME_PROMPT_SUBMIT, prompt_frame)
        received = [entry for entry in self.inputs() if entry.get("hook_started") is True]
        if captured is not None:
            captured.append({"kind": "inputs", "values": received})
        first = received[0].get("text") if received else None
        if first != self.message:
            raise platform_failure(DETAIL_INPUT_TEXT.format(received=first))
        self._await_record(native, deadline)
        return native

    def started(self, record: Mapping[str, object] | None, native: str) -> bool:
        """Whether the flat record shows the platform\'s completed startup of this fixture launch."""
        return (
            record is not None
            and record.get(FIELD_SESSION_ID) == self.session_id
            and self.same_path(record.get(FIELD_PROJECT))
            and record.get(FIELD_ACTIVE_AGENT) == AGENT_NAME
            and record.get(FIELD_NATIVE) == native
            and record.get(FIELD_LIFECYCLE) == ACTIVE
            and record.get(FIELD_OBSERVED) is True
            and record.get(FIELD_CLOSED_AT) is None
        )

    def _await_record(self, native: str, deadline: float) -> None:
        """Poll fresh public reads until the startup state shows; the read that shows it is the retained evidence."""
        last: Mapping[str, object] | None = None
        while time.monotonic() < deadline:
            record = self.record(retain=False)
            last = record if record is not None else last
            if self.started(record, native):
                confirmed = self.record()
                if self.started(confirmed, native):
                    return
                last = confirmed if confirmed is not None else last
            time.sleep(RECORD_POLL_SECONDS)
        self.record()
        raise platform_failure(DETAIL_RECORD.format(seconds=START_OBSERVATION_CAP_SECONDS, record=last))

    def self_identity(self, release_at: float) -> None:
        """Step 6: the fixture's own fresh `sessions show self --full`, run in its platform-created pane."""
        frame = self.await_frame(FRAME_SELF_PROBE, release_at + START_OBSERVATION_CAP_SECONDS)
        run = frame.get("run")
        if not isinstance(run, dict):
            raise platform_failure(DETAIL_FRAME_INVALID.format(frame=FRAME_SELF_PROBE))
        output = str(run.get("stdout", ""))
        self.host.note(
            [str(part) for part in run.get("argv", [])],
            Outcome(run.get("exit_status") if isinstance(run.get("exit_status"), int) else None, output),
            str(run.get("stderr", ""))[:400],
        )
        record = json_object(output)
        if run.get("exit_status") != 0 or record is None or record.get(FIELD_SESSION_ID) != self.session_id:
            raise platform_failure(DETAIL_SELF_PROBE.format(output=output[:400]))

    def end_session(self) -> None:
        """Step 8: end the session; acceptance is not closure, so read the operation and the retained record."""
        packet: EvidenceObject | None = None
        if self.end_evidence is not None:
            packet = {
                "kind": "foundation-end",
                "session_id": self.session_id,
                "started_ns": time.monotonic_ns(),
                "finished_ns": None,
                "command": None,
                "operation_reads": [],
                "retained_terminal": None,
                "closed_reads": [],
                "error": None,
            }
            self.end_evidence.append(packet)
        try:
            argv = (TELEC, SESSIONS, END, self.session_id)
            outcome = self.host.cli(argv, CLI_TIMEOUT_SECONDS)
            if packet is not None:
                packet["command"] = outcome.evidence(argv)
            receipt = json_object(outcome.output)
            operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
            if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
                raise platform_failure(DETAIL_END.format(detail=f"no operation receipt: {outcome.output[-300:]}"))
            deadline = time.monotonic() + START_OBSERVATION_CAP_SECONDS
            while True:
                argv = (TELEC, OPERATIONS, GET, operation)
                state_outcome = self.host.cli(argv, CLI_TIMEOUT_SECONDS, retain=False)
                if packet is not None:
                    cast(list[EvidenceValue], packet["operation_reads"]).append(state_outcome.evidence(argv))
                state = json_object(state_outcome.output)
                value = state.get(FIELD_STATE) if state is not None else None
                if value == OPERATION_COMPLETED:
                    terminal = self.host.cli(argv, CLI_TIMEOUT_SECONDS)
                    if packet is not None:
                        packet["retained_terminal"] = terminal.evidence(argv)
                    break
                if value in OPERATION_FAILED_STATES or time.monotonic() >= deadline:
                    terminal = self.host.cli(argv, CLI_TIMEOUT_SECONDS)
                    if packet is not None:
                        packet["retained_terminal"] = terminal.evidence(argv)
                    raise platform_failure(
                        DETAIL_END.format(detail=f"operation state {value!r}: {state_outcome.output[-300:]}")
                    )
                time.sleep(RECORD_POLL_SECONDS)
            record = self.record(evidence=cast(list[EvidenceValue], packet["closed_reads"]) if packet else None)
            if record is None or record.get(FIELD_CLOSED_AT) is None or record.get(FIELD_LIFECYCLE) != CLOSED:
                raise platform_failure(DETAIL_END.format(detail=f"retained record not closed: {record!r}"))
        except Exception as error:
            if packet is not None:
                packet["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            if packet is not None:
                packet["finished_ns"] = time.monotonic_ns()

    def release_session(self) -> None:
        """Best-effort cleanup of a session the journey left open; failures are reported by the caller's evidence."""
        if self.session_id:
            with suppress(Exception):  # the journey\'s own failure is the one to report, not the cleanup\'s
                self.host.cli((TELEC, SESSIONS, END, self.session_id), CLI_TIMEOUT_SECONDS)


def prepare_project(host: FoundationHost, project: Path) -> None:
    """Make the owned registered project a Git project, once."""
    if (project / GIT_DIRECTORY).exists():
        return
    outcome = host.process((GIT_EXECUTABLE, *GIT_INIT_ARGUMENTS), project, host.environment, PROCESS_TIMEOUT_SECONDS)
    if outcome.exit_status != 0:
        raise binding_failure(f"git init of the owned project failed: {outcome.output[-200:]}")


def run_foundation(host: FoundationHost, setup: FixtureSetup, project: Path, owner_email: str) -> None:
    """Run journey F0; raises FoundationFailure or FixtureBindingFailure."""
    prepare_project(host, project)
    journey = Journey(host, setup, project, owner_email)
    journey.non_session_control()
    try:
        case_start = journey.start_session()
        journey.negative_control(case_start)
        release_at = time.monotonic()
        native = journey.positive_start(release_at)
        del native
        journey.self_identity(release_at)
        journey.end_session()
    except BaseException:
        journey.release_session()
        raise
