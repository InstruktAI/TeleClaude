"""Profile-owned public event-window and witness carrier for workflow B3 through B6."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from tools.ci import workflow_creation as creation
from tools.ci import workflow_ledger as ledger

ITEM: Final = "b3-item"
TELEC: Final = "telec"
WINDOW_DIRECTORY: Final = "workflow-b3-b6-event-window"
RETAINED_EVIDENCE: Final = "B10 event evidence retained at {path}"
WINDOW_FILE: Final = "window.json"
WITNESSES_FILE: Final = "witnesses.jsonl"
CASE_REPORT_FILE: Final = "workflow-b3-b6-case-report.json"
ENCODING: Final = "utf-8"
LINE_BREAK: Final = "\n"
WINDOW_SCHEMA: Final = 1
CASE_REPORT_SCHEMA: Final = 1
CLI_SECONDS: Final = 60
FIRST_CASE: Final = "B3"
CASE_SEQUENCE: Final = ("B3", "B4", "B5", "B7", "B6")
EVENT_TYPES: Final = (
    "sdlc.todo.waiting",
    "sdlc.todo.phase_advanced",
    "sdlc.todo.claim_changed",
    "sdlc.todo.head_advanced",
    "sdlc.todo.ready",
)
DEFAULT_LIMIT: Final = 200
HEADER_PREFIX: Final = "### "
HEADER_BOUNDARY: Final = "\n### "
HEADER_ROLE_SEPARATOR: Final = " — "
HEADER_FIELD_SEPARATOR: Final = " · "
HEADER_OPEN_BOUND: Final = " ("
HEADER_CLOSE_BOUND: Final = ")"
EXPECTED_RETAINED_LIMIT: Final = "retained_only"
EXPECTED_COMPUTER_LIMIT: Final = "computer_local"
UNDECODABLE_LIMIT: Final = "undecodable_entries"
ROLE_WORK: Final = "work-orchestrator"
ROLE_BUILDER: Final = "builder"
ROLE_PREPARE: Final = "prepare-orchestrator"
ACT_REVIEWED: Final = "reviewed"
ACT_FINDING: Final = "finding"
ACT_REPLY: Final = "reply"
ACT_STAMP: Final = "stamp"
ACT_CLAIM: Final = "claim"
FINDING_TEXT: Final = "Important: the feature file lacks a trailing note"
REPLY_TEXT: Final = "fixed in the next commit"
LANE_ONE: Final = (
    "synthetic fixture lane report 1 of 2: recorded by the acceptance fixture; the constant-true native target exited 0; "
    "no application test suite ran; no specification approval is claimed"
)
LANE_TWO: Final = (
    "synthetic fixture lane report 2 of 2: recorded by the acceptance fixture after the head moved; "
    "the constant-true native target exited 0; no application test suite ran; no specification approval is claimed"
)

FIELD_SCHEMA: Final = "schema_version"
FIELD_CASES: Final = "cases"
FIELD_WINDOW_SHA: Final = "window_sha256"
FIELD_WINDOW_PATH: Final = "window_path"
FIELD_WITNESSES_PATH: Final = "witnesses_path"
FIELD_WITNESS_COUNT: Final = "witness_line_count"
FIELD_WITNESS_SHA: Final = "witness_sha256"
FIELD_STATUS: Final = "status"
FIELD_COMPLETE: Final = "complete"
FIELD_CASE: Final = "case"
FIELD_DATA: Final = "data"
FIELD_INITIAL_LOG: Final = "initial_log"
FIELD_ARTIFACTS: Final = "artifacts"
FIELD_CONTENT: Final = "artifact_content"
FIELD_LOG: Final = "log"
FIELD_ITEM: Final = "item"
FIELD_SUBJECT: Final = "subject"
FIELD_COMPUTER: Final = "computer"
FIELD_PROJECT: Final = "project"
FIELD_CURSOR: Final = "observation_cursor"
FIELD_OCCURRENCES: Final = "occurrences"
FIELD_SOURCE: Final = "source"
FIELD_ORIGIN: Final = "origin"
FIELD_ID: Final = "id"
FIELD_TYPE: Final = "type"
FIELD_EVENT_DATA: Final = "data"
FIELD_COVERAGE: Final = "coverage"
FIELD_CONTINUATION: Final = "continuation"
FIELD_REMAINS: Final = "remains"
FIELD_NEXT_CURSOR: Final = "cursor"
FIELD_LIMITS: Final = "limits"
FIELD_RETAINED_ONLY: Final = "retained_only"
FIELD_RETAINED_FROM: Final = "retained_from"
FIELD_RETAINED_TO: Final = "retained_to"
FIELD_PROJECT_PATH: Final = "project_path"
FIELD_SLUG: Final = "slug"
FIELD_PERSON: Final = "person"
FIELD_WAIT: Final = "wait"
FIELD_WAITED_PHASE: Final = "waited_phase"
FIELD_LIFECYCLE_PHASE: Final = "lifecycle_phase"
FIELD_PRIOR_PHASE: Final = "prior_lifecycle_phase"
FIELD_HOLDER: Final = "holder"
FIELD_PRIOR_HOLDER: Final = "prior_holder"
FIELD_BRANCH: Final = "branch"
FIELD_SHA: Final = "sha"
FIELD_DRIVER: Final = "driver_session_id"
FIELD_READY_AT: Final = "ready_at"

DETAIL_BINDING: Final = "B10 event window binding failure: {detail}"
DETAIL_EVIDENCE: Final = "B10 event evidence is unproven: {detail}"
DETAIL_CARRIER: Final = "B10 profile event carrier is incomplete: {detail}"
DETAIL_PROJECTS: Final = "the public projects list does not identify the registered workflow project"
DETAIL_PROJECT_CONFIG: Final = "the public project config does not match the registered slug and name"
DETAIL_COMPUTER: Final = "the public computers list does not identify exactly one online local computer"
DETAIL_MARK: Final = "the public event mark does not match the independently derived project selection"
DETAIL_WINDOW: Final = "the original event window is missing, unreadable, changed, or malformed"
DETAIL_SEAL: Final = "the previous case witness seal does not match the complete append-only file"
DETAIL_PAGE: Final = "the public event trail page is malformed or changed its selection"
DETAIL_EVENT: Final = "a required visible positive event occurrence is not established: {detail}"
DETAIL_LOG: Final = "the final public item log is malformed or does not preserve the observed B3 state"
DETAIL_LOG_HEADER: Final = "the public item log contains a malformed ledger header"
DETAIL_LOG_SECTION: Final = "the public item log contains a malformed ledger section"
WORK_CLAIM_BODY: Final = "{item} claimed by {role} session {session} on branch {branch}."


@dataclass(frozen=True)
class LogEntry:
    header: str
    timestamp: str
    role: str
    session: str
    act: str
    bound: str | None
    body: str


def parse_log_entries(log: str) -> list[LogEntry]:
    """Parse ledger sections at their next header and preserve every body byte except renderer framing."""
    matches = list(re.finditer(re.escape(HEADER_BOUNDARY), log))
    entries: list[LogEntry] = []
    for index, match in enumerate(matches):
        header_start = match.end() - len(HEADER_PREFIX)
        header_end = log.find(LINE_BREAK, header_start)
        if header_end < 0:
            raise creation.binding_failure(DETAIL_LOG_HEADER)
        header = log[header_start:header_end]
        timestamp, separator, remainder = header[len(HEADER_PREFIX) :].partition(HEADER_ROLE_SEPARATOR)
        role, role_separator, remainder = remainder.partition(HEADER_FIELD_SEPARATOR)
        session, session_separator, act_field = remainder.partition(HEADER_FIELD_SEPARATOR)
        if not timestamp or not separator or not role_separator or not session or not session_separator:
            raise creation.binding_failure(DETAIL_LOG_HEADER)
        bound: str | None = None
        open_index = act_field.find(HEADER_OPEN_BOUND)
        if open_index >= 0:
            if not act_field.endswith(HEADER_CLOSE_BOUND):
                raise creation.binding_failure(DETAIL_LOG_HEADER)
            act = act_field[:open_index]
            bound = act_field[open_index + len(HEADER_OPEN_BOUND) : -len(HEADER_CLOSE_BOUND)]
            if not bound:
                raise creation.binding_failure(DETAIL_LOG_HEADER)
        else:
            act = act_field
        if not act:
            raise creation.binding_failure(DETAIL_LOG_HEADER)
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(log)
        body = log[header_end + 1 : section_end]
        if not body.startswith(LINE_BREAK):
            raise creation.binding_failure(DETAIL_LOG_SECTION)
        body = body[1:]
        if body:
            if not body.endswith(LINE_BREAK):
                raise creation.binding_failure(DETAIL_LOG_SECTION)
            body = body[:-1]
        entries.append(LogEntry(header, timestamp, role, session, act, bound, body))
    return entries


@dataclass(frozen=True)
class EventWindowBinding:
    profile_root: Path
    carrier_root: Path
    window_path: Path
    witnesses_path: Path
    report_path: Path
    window_sha256: str
    project_slug: str
    project_home: str
    project_path: str
    computer: str

    def json_value(self) -> ledger.JsonObject:
        return {
            FIELD_WINDOW_PATH: str(self.window_path.resolve()),
            FIELD_WITNESSES_PATH: str(self.witnesses_path.resolve()),
            FIELD_WINDOW_SHA: self.window_sha256,
            "case_report_path": str(self.report_path.resolve()),
            "project_slug": self.project_slug,
            "project_home": self.project_home,
            FIELD_PROJECT_PATH: self.project_path,
            FIELD_COMPUTER: self.computer,
        }


type ByteReads = dict[Path, list[bytes]]


def _read_object(path: Path, detail: str, captured: ByteReads | None = None) -> Mapping[str, object]:
    try:
        data = path.read_bytes()
        if captured is not None:
            captured.setdefault(path, []).append(data)
        value = json.loads(data.decode(ENCODING))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=detail)) from error
    if not isinstance(value, Mapping):
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=detail))
    return value


def _file_sha(path: Path, captured: ByteReads | None = None) -> str:
    try:
        data = path.read_bytes()
        if captured is not None:
            captured.setdefault(path, []).append(data)
        return hashlib.sha256(data).hexdigest()
    except OSError as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(path))) from error


def _write_new_json(path: Path, value: ledger.JsonObject) -> None:
    try:
        with path.open("x", encoding=ENCODING) as handle:
            handle.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
            handle.write(LINE_BREAK)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(path))) from error


def _write_report(binding: EventWindowBinding, report: ledger.JsonObject) -> None:
    temporary = binding.report_path.with_name(f".{binding.report_path.name}.tmp")
    try:
        with temporary.open("w", encoding=ENCODING) as handle:
            json.dump(report, handle, sort_keys=True, separators=(",", ":"))
            handle.write(LINE_BREAK)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, binding.report_path)
    except OSError as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(binding.report_path))) from error


def _run_json(observer: creation.Observer, argv: tuple[str, ...], detail: str) -> object:
    outcome = observer.run(argv)
    if outcome.exit_status != 0:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"{detail}: {outcome.output[-300:]}"))
    value = _decode_json_value(outcome.output)
    if value is None:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=detail))
    return value


def _decode_json_value(output: str) -> object | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character not in ("{", "["):
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        return cast(object, value)
    return None


def _config_view(observer: creation.Observer, kind: str, *argv: str) -> Mapping[str, object]:
    payload = _run_json(observer, (TELEC, "config", kind, "get", *argv, "--format", "json"), kind)
    if not isinstance(payload, Mapping):
        raise creation.binding_failure(DETAIL_BINDING.format(detail=kind))
    return payload


def _registered_project(
    observer: creation.Observer, project: Path, project_slug: str, project_name: str, computer: str
) -> tuple[str, str]:
    project_payload = _config_view(observer, "project", project_slug)
    project_config = project_payload.get("project")
    revision = project_payload.get("revision")
    if (
        not isinstance(project_config, Mapping)
        or not isinstance(revision, str)
        or not revision
        or project_config.get("project_slug") != project_slug
    ):
        raise creation.binding_failure(DETAIL_PROJECT_CONFIG)
    configured_name = project_config.get("project_name")
    if configured_name is None or configured_name == "":
        catalog_name = project_slug
    elif isinstance(configured_name, str):
        catalog_name = configured_name
    else:
        raise creation.binding_failure(DETAIL_PROJECT_CONFIG)
    if catalog_name != project_name:
        raise creation.binding_failure(DETAIL_PROJECT_CONFIG)

    rows = _run_json(observer, (TELEC, "projects", "list"), "projects list")
    if not isinstance(rows, list):
        raise creation.binding_failure(DETAIL_PROJECTS)
    expected_path = str(project.resolve())
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("name") == catalog_name
        and row.get("path") == expected_path
        and row.get("computer") == computer
    ]
    if len(matches) != 1:
        raise creation.binding_failure(DETAIL_PROJECTS)
    return expected_path, f"project:{project_slug}"


def _current_computer(observer: creation.Observer) -> str:
    rows = _run_json(observer, (TELEC, "computers", "list"), "computers list")
    if not isinstance(rows, list):
        raise creation.binding_failure(DETAIL_COMPUTER)
    local_rows = [row for row in rows if isinstance(row, Mapping) and row.get("is_local") is True]
    if len(local_rows) != 1:
        raise creation.binding_failure(DETAIL_COMPUTER)
    local = local_rows[0]
    name = local.get("name")
    if local.get("status") != "online" or not isinstance(name, str) or not name:
        raise creation.binding_failure(DETAIL_COMPUTER)
    return name


def _initial_log(shown: Mapping[str, object]) -> ledger.JsonObject:
    names = shown.get(FIELD_ARTIFACTS)
    content = shown.get(FIELD_CONTENT)
    if (
        not isinstance(names, list)
        or not all(isinstance(name, str) for name in names)
        or not isinstance(content, Mapping)
    ):
        raise creation.binding_failure(DETAIL_LOG)
    has_name = FIELD_LOG in names
    has_content = FIELD_LOG in content
    if not has_name and not has_content:
        return {"presence": "absent"}
    value = content.get(FIELD_LOG)
    if has_name and has_content and isinstance(value, str):
        return {"presence": "present", "type": "string", "value": value}
    raise creation.binding_failure(DETAIL_LOG)


def begin_b3_window(
    observer: creation.Observer,
    setup_parent: Path,
    project: Path,
    project_slug: str,
    project_name: str,
    shown: Mapping[str, object],
) -> EventWindowBinding:
    """Ground public registration, capture initial log semantics, and create the one original event mark."""
    computer = _current_computer(observer)
    project_path, project_home = _registered_project(observer, project, project_slug, project_name, computer)
    result = _run_json(observer, (TELEC, "events", "trail", ITEM, "--mark"), "events trail mark")
    if not isinstance(result, Mapping):
        raise creation.binding_failure(DETAIL_MARK)
    item = result.get(FIELD_ITEM)
    cursor = result.get(FIELD_CURSOR)
    if (
        not isinstance(item, Mapping)
        or item.get(FIELD_SUBJECT) != f"todo:{ITEM}"
        or item.get(FIELD_PROJECT) != project_home
        or item.get(FIELD_COMPUTER) != computer
        or not isinstance(cursor, str)
        or not cursor
    ):
        raise creation.binding_failure(DETAIL_MARK)
    carrier_root = setup_parent / WINDOW_DIRECTORY
    try:
        carrier_root.mkdir()
    except OSError as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(carrier_root))) from error
    window_path = carrier_root / WINDOW_FILE
    witnesses_path = carrier_root / WITNESSES_FILE
    report_path = setup_parent / CASE_REPORT_FILE
    window: ledger.JsonObject = {
        FIELD_SCHEMA: WINDOW_SCHEMA,
        "project_slug": project_slug,
        "project_home": project_home,
        FIELD_PROJECT_PATH: project_path,
        FIELD_COMPUTER: computer,
        FIELD_ITEM: cast(ledger.JsonValue, dict(item)),
        FIELD_CURSOR: cursor,
        "raw_mark": cast(ledger.JsonValue, dict(result)),
        FIELD_INITIAL_LOG: _initial_log(shown),
    }
    _write_new_json(window_path, window)
    try:
        with witnesses_path.open("x", encoding=ENCODING) as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(witnesses_path))) from error
    sha = _file_sha(window_path)
    binding = EventWindowBinding(
        setup_parent.resolve(),
        carrier_root.resolve(),
        window_path.resolve(),
        witnesses_path.resolve(),
        report_path.resolve(),
        sha,
        project_slug,
        project_home,
        project_path,
        computer,
    )
    _write_report(
        binding,
        {
            FIELD_SCHEMA: CASE_REPORT_SCHEMA,
            FIELD_WINDOW_SHA: sha,
            FIELD_WINDOW_PATH: str(window_path.resolve()),
            FIELD_WITNESSES_PATH: str(witnesses_path.resolve()),
            FIELD_CASES: {},
        },
    )
    return binding


def load_binding(
    setup_parent: Path, expected_window_sha: str | None = None, *, captured: ByteReads | None = None
) -> EventWindowBinding:
    """Read the profile case report and immutable B3 window without accepting a later replacement mark."""
    report_path = setup_parent.resolve() / CASE_REPORT_FILE
    report = _read_object(report_path, str(report_path), captured)
    sha = report.get(FIELD_WINDOW_SHA)
    window_path = setup_parent.resolve() / WINDOW_DIRECTORY / WINDOW_FILE
    witnesses_path = setup_parent.resolve() / WINDOW_DIRECTORY / WITNESSES_FILE
    expected_paths = (str(window_path.resolve()), str(witnesses_path.resolve()))
    if (
        report.get(FIELD_SCHEMA) != CASE_REPORT_SCHEMA
        or not isinstance(sha, str)
        or (expected_window_sha is not None and sha != expected_window_sha)
        or report.get(FIELD_WINDOW_PATH) != expected_paths[0]
        or report.get(FIELD_WITNESSES_PATH) != expected_paths[1]
        or _file_sha(window_path, captured) != sha
    ):
        raise creation.binding_failure(DETAIL_WINDOW)
    window = _read_object(window_path, str(window_path), captured)
    project_slug = window.get("project_slug")
    project_home = window.get("project_home")
    project_path = window.get(FIELD_PROJECT_PATH)
    computer = window.get(FIELD_COMPUTER)
    item = window.get(FIELD_ITEM)
    cursor = window.get(FIELD_CURSOR)
    if (
        window.get(FIELD_SCHEMA) != WINDOW_SCHEMA
        or not isinstance(project_slug, str)
        or not isinstance(project_home, str)
        or not isinstance(project_path, str)
        or not isinstance(computer, str)
        or not isinstance(item, Mapping)
        or item.get(FIELD_SUBJECT) != f"todo:{ITEM}"
        or item.get(FIELD_PROJECT) != project_home
        or item.get(FIELD_COMPUTER) != computer
        or not isinstance(cursor, str)
        or not cursor
        or not isinstance(report.get(FIELD_CASES), Mapping)
    ):
        raise creation.binding_failure(DETAIL_WINDOW)
    return EventWindowBinding(
        setup_parent.resolve(),
        (setup_parent.resolve() / WINDOW_DIRECTORY),
        window_path.resolve(),
        witnesses_path.resolve(),
        report_path,
        sha,
        project_slug,
        project_home,
        project_path,
        computer,
    )


def _witness_lines(
    binding: EventWindowBinding, captured: ByteReads | None = None
) -> tuple[list[Mapping[str, object]], str]:
    try:
        raw = binding.witnesses_path.read_bytes()
        if captured is not None:
            captured.setdefault(binding.witnesses_path, []).append(raw)
        text = raw.decode(ENCODING)
    except (OSError, UnicodeError) as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(binding.witnesses_path))) from error
    if text and not text.endswith(LINE_BREAK):
        raise creation.binding_failure(DETAIL_SEAL)
    lines: list[Mapping[str, object]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise creation.binding_failure(DETAIL_SEAL) from error
        if not isinstance(value, Mapping) or value.get(FIELD_WINDOW_SHA) != binding.window_sha256:
            raise creation.binding_failure(DETAIL_SEAL)
        lines.append(value)
    return lines, hashlib.sha256(raw).hexdigest()


def seal_for(binding: EventWindowBinding, case: str, *, captured: ByteReads | None = None) -> ledger.JsonObject:
    report = _read_object(binding.report_path, str(binding.report_path), captured)
    cases = report.get(FIELD_CASES)
    entry = cases.get(case) if isinstance(cases, Mapping) else None
    if not isinstance(entry, Mapping):
        raise creation.binding_failure(DETAIL_SEAL)
    lines, sha = _witness_lines(binding, captured)
    count = entry.get(FIELD_WITNESS_COUNT)
    expected_sha = entry.get(FIELD_WITNESS_SHA)
    if not isinstance(count, int) or count != len(lines) or expected_sha != sha:
        raise creation.binding_failure(DETAIL_SEAL)
    return {FIELD_WITNESS_COUNT: count, FIELD_WITNESS_SHA: sha}


def read_records(binding: EventWindowBinding) -> list[Mapping[str, object]]:
    lines, _sha = _witness_lines(binding)
    return lines


def set_case_status(binding: EventWindowBinding, case: str, status: str) -> None:
    report = dict(_read_object(binding.report_path, str(binding.report_path)))
    cases_value = report.get(FIELD_CASES)
    cases = (
        {str(key): cast(ledger.JsonValue, value) for key, value in cases_value.items()}
        if isinstance(cases_value, Mapping)
        else None
    )
    entry = cases.get(case) if cases is not None else None
    if cases is None or not isinstance(entry, Mapping):
        raise creation.binding_failure(DETAIL_SEAL)
    updated = dict(entry)
    updated[FIELD_STATUS] = status
    cases[case] = cast(ledger.JsonValue, updated)
    report[FIELD_CASES] = cases
    _write_report(binding, cast(ledger.JsonObject, report))


def _captured_inputs(
    profile_root: Path, captured: ByteReads, cases: tuple[str, ...], error: str | None
) -> ledger.JsonObject:
    root = profile_root.resolve()
    paths = {
        "case_report": root / CASE_REPORT_FILE,
        "window": root / WINDOW_DIRECTORY / WINDOW_FILE,
        "witnesses": root / WINDOW_DIRECTORY / WITNESSES_FILE,
    }
    result: ledger.JsonObject = {"schema_version": 1, "selected_case_prefix": list(cases), "capture_error": error}
    for leaf, path in paths.items():
        result[leaf] = [
            {
                "raw_data": base64.b64encode(data).decode("ascii"),
                "raw_sha256": hashlib.sha256(data).hexdigest(),
                "raw_byte_count": len(data),
            }
            for data in captured.get(path, ())
        ]
    return result


def profile_report(profile_root: Path, *, selected_cases: tuple[str, ...] | None = None) -> ledger.JsonObject:
    captured: ByteReads | None = {} if selected_cases is not None else None
    error: str | None = None
    result = _profile_report(profile_root, selected_cases, captured)
    if captured is not None and selected_cases is not None:
        capture_failure = result.pop("input_capture_error", None)
        error = str(capture_failure) if capture_failure is not None else None
        result["input_capture"] = _captured_inputs(profile_root, captured, selected_cases, error)
    return result


def _profile_report(
    profile_root: Path, selected_cases: tuple[str, ...] | None, captured: ByteReads | None
) -> ledger.JsonObject:
    path = profile_root.resolve() / CASE_REPORT_FILE
    if not path.is_file():
        return {FIELD_STATUS: "not_started", FIELD_CASES: {}}
    try:
        report = dict(_read_object(path, str(path), captured))
    except creation.JourneyFailure as error:
        return {
            FIELD_STATUS: "unproven",
            FIELD_CASES: {},
            "case_report_path": str(path),
            "error": str(error),
            **({"input_capture_error": str(error)} if captured is not None else {}),
        }
    cases = report.get(FIELD_CASES)
    complete = isinstance(cases, Mapping) and all(
        isinstance(cases.get(case), Mapping) and cases[case].get(FIELD_STATUS) == "complete" for case in CASE_SEQUENCE
    )
    if complete or selected_cases:
        try:
            binding = load_binding(profile_root, captured=captured)
            verify_case(binding, selected_cases[-1] if selected_cases else "B6", captured=captured)
        except creation.JourneyFailure as error:
            complete = False
            if captured is not None:
                report["input_capture_error"] = str(error)
    report[FIELD_STATUS] = "complete" if complete else "unproven"
    report["case_report_path"] = str(path)
    return cast(ledger.JsonObject, report)


def verify_case(
    binding: EventWindowBinding,
    case: str,
    expected_seal: Mapping[str, object] | None = None,
    *,
    captured: ByteReads | None = None,
) -> None:
    report = _read_object(binding.report_path, str(binding.report_path), captured)
    if (
        report.get(FIELD_WINDOW_SHA) != binding.window_sha256
        or _file_sha(binding.window_path, captured) != binding.window_sha256
    ):
        raise creation.binding_failure(DETAIL_WINDOW)
    seal = seal_for(binding, case, captured=captured)
    if expected_seal is not None and any(
        seal.get(key) != expected_seal.get(key) for key in (FIELD_WITNESS_COUNT, FIELD_WITNESS_SHA)
    ):
        raise creation.binding_failure(DETAIL_SEAL)


def append_case(
    binding: EventWindowBinding,
    case: str,
    payload: Mapping[str, object],
    previous_case: str | None,
    expected_previous_seal: Mapping[str, object] | None = None,
    status: str = "complete",
) -> ledger.JsonObject:
    """Verify the previous published prefix, append complete public evidence, then publish its new seal."""
    if previous_case is not None:
        verify_case(binding, previous_case, expected_previous_seal)
    else:
        if case != FIRST_CASE or _file_sha(binding.window_path) != binding.window_sha256:
            raise creation.binding_failure(DETAIL_SEAL)
        report_before = _read_object(binding.report_path, str(binding.report_path))
        cases_before = report_before.get(FIELD_CASES)
        lines_before, _ = _witness_lines(binding)
        if not isinstance(cases_before, Mapping) or cases_before or lines_before:
            raise creation.binding_failure(DETAIL_SEAL)
    report_before = _read_object(binding.report_path, str(binding.report_path))
    cases_before = report_before.get(FIELD_CASES)
    if not isinstance(cases_before, Mapping) or case in cases_before:
        raise creation.binding_failure(DETAIL_SEAL)
    row: ledger.JsonObject = {
        FIELD_CASE: case,
        FIELD_WINDOW_SHA: binding.window_sha256,
        FIELD_DATA: cast(ledger.JsonValue, dict(payload)),
    }
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + LINE_BREAK
    try:
        with binding.witnesses_path.open("a", encoding=ENCODING) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise creation.binding_failure(DETAIL_CARRIER.format(detail=str(binding.witnesses_path))) from error
    lines, sha = _witness_lines(binding)
    report = dict(_read_object(binding.report_path, str(binding.report_path)))
    cases_value = report.get(FIELD_CASES)
    if not isinstance(cases_value, Mapping):
        raise creation.binding_failure(DETAIL_SEAL)
    cases: dict[str, ledger.JsonValue] = {str(key): cast(ledger.JsonValue, value) for key, value in cases_value.items()}
    if case in cases or cases != dict(cases_before):
        raise creation.binding_failure(DETAIL_SEAL)
    cases[case] = {
        FIELD_STATUS: status,
        FIELD_WITNESS_COUNT: len(lines),
        FIELD_WITNESS_SHA: sha,
    }
    report[FIELD_CASES] = cases
    _write_report(binding, cast(ledger.JsonObject, report))
    return {FIELD_WITNESS_COUNT: len(lines), FIELD_WITNESS_SHA: sha}


def read_pages(
    observer: creation.Observer, binding: EventWindowBinding
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]], str | None]:
    """Read one finite original-cursor chain; every result is retained as returned by the public CLI."""
    window = _read_object(binding.window_path, str(binding.window_path))
    cursor = window.get(FIELD_CURSOR)
    if not isinstance(cursor, str) or not cursor:
        raise creation.binding_failure(DETAIL_WINDOW)
    pages: list[Mapping[str, object]] = []
    coverages: list[Mapping[str, object]] = []
    error: str | None = None
    argv = (TELEC, "events", "trail", ITEM, "--since", cursor, "--limit", str(DEFAULT_LIMIT))
    while True:
        outcome = observer.run(argv)
        if outcome.exit_status != 0:
            error = f"events trail exited {outcome.exit_status}: {outcome.output[-300:]}"
            break
        value = _decode_json_value(outcome.output)
        if value is None:
            error = "events trail returned invalid JSON"
            break
        if not isinstance(value, Mapping):
            error = DETAIL_PAGE
            break
        pages.append(value)
        try:
            _validate_selection(value, binding)
        except creation.JourneyFailure as caught:
            error = str(caught)
            break
        coverage = value.get(FIELD_COVERAGE)
        if not isinstance(coverage, Mapping):
            error = DETAIL_PAGE
            break
        coverages.append(coverage)
        continuation = value.get(FIELD_CONTINUATION)
        if not isinstance(continuation, Mapping) or not isinstance(continuation.get(FIELD_REMAINS), bool):
            error = DETAIL_PAGE
            break
        if not continuation.get(FIELD_REMAINS):
            break
        next_cursor = continuation.get(FIELD_NEXT_CURSOR)
        if not isinstance(next_cursor, str) or not next_cursor:
            error = DETAIL_PAGE
            break
        argv = (TELEC, "events", "trail", ITEM, "--cursor", next_cursor, "--limit", str(DEFAULT_LIMIT))
    return pages, coverages, error


def _validate_selection(page: Mapping[str, object], binding: EventWindowBinding) -> None:
    item = page.get(FIELD_ITEM)
    if (
        not isinstance(item, Mapping)
        or item.get(FIELD_SUBJECT) != f"todo:{ITEM}"
        or item.get(FIELD_PROJECT) != binding.project_home
        or item.get(FIELD_COMPUTER) != binding.computer
    ):
        raise creation.binding_failure(DETAIL_PAGE)


def assert_positive_facts(
    binding: EventWindowBinding,
    records: list[Mapping[str, object]],
    pages: list[Mapping[str, object]],
    coverages: list[Mapping[str, object]],
    final_item: Mapping[str, object],
) -> None:
    """Assert only the approved visible positive event and public-log facts for the recorded B3-B7 witnesses."""
    window = _read_object(binding.window_path, str(binding.window_path))
    assert_positive_window(binding, window, records, pages, coverages, final_item)


def assert_positive_window(
    binding: EventWindowBinding,
    window: Mapping[str, object],
    records: list[Mapping[str, object]],
    pages: list[Mapping[str, object]],
    coverages: list[Mapping[str, object]],
    final_item: Mapping[str, object],
) -> None:
    """Apply the existing public-event/log predicates to an already captured original window, with no file reads."""
    initial_log = window.get(FIELD_INITIAL_LOG)
    content = final_item.get(FIELD_CONTENT)
    final_log = content.get(FIELD_LOG) if isinstance(content, Mapping) else None
    if not isinstance(initial_log, Mapping) or not isinstance(final_log, str):
        raise creation.platform_failure(DETAIL_LOG)
    try:
        final_log_observation = _initial_log(final_item)
    except creation.JourneyFailure as error:
        raise creation.platform_failure(DETAIL_LOG) from error
    if final_log_observation.get("presence") != "present":
        raise creation.platform_failure(DETAIL_LOG)
    if initial_log.get("presence") == "present":
        original = initial_log.get("value")
        if not isinstance(original, str) or not final_log.startswith(original):
            raise creation.platform_failure(DETAIL_LOG)
    elif initial_log.get("presence") != "absent":
        raise creation.platform_failure(DETAIL_LOG)
    event_rows = _visible_events(binding, pages)
    for record in records:
        case = record.get(FIELD_CASE)
        data = record.get(FIELD_DATA)
        if not isinstance(case, str) or not isinstance(data, Mapping):
            raise creation.binding_failure(DETAIL_SEAL)
        _assert_event_payloads(binding, case, data, event_rows)
        _assert_log_payloads(case, data, final_log)
    if not coverages or any(not _coverage_complete(coverage) for coverage in coverages):
        raise creation.platform_failure(DETAIL_EVIDENCE.format(detail="the original cursor interval is incomplete"))
    if any(_coverage_has_undecodable(coverage) for coverage in coverages):
        raise creation.platform_failure(DETAIL_EVIDENCE.format(detail="the public reader reported undecodable entries"))


def _visible_events(binding: EventWindowBinding, pages: list[Mapping[str, object]]) -> list[Mapping[str, object]]:
    events: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for page in pages:
        _validate_selection(page, binding)
        occurrences = page.get(FIELD_OCCURRENCES)
        if not isinstance(occurrences, list):
            raise creation.binding_failure(DETAIL_PAGE)
        for raw in occurrences:
            if not isinstance(raw, Mapping):
                raise creation.binding_failure(DETAIL_PAGE)
            source = raw.get(FIELD_SOURCE)
            data = raw.get(FIELD_EVENT_DATA)
            identifier = raw.get(FIELD_ID)
            if (
                not isinstance(identifier, str)
                or not identifier
                or not isinstance(source, Mapping)
                or source.get(FIELD_COMPUTER) != binding.computer
                or source.get(FIELD_ORIGIN) != binding.project_home
                or raw.get(FIELD_SUBJECT) != f"todo:{ITEM}"
                or not isinstance(data, Mapping)
                or raw.get(FIELD_TYPE) not in EVENT_TYPES
            ):
                raise creation.binding_failure(DETAIL_PAGE)
            if identifier not in seen:
                seen.add(identifier)
                events.append(raw)
    return events


def _assert_event_payloads(
    binding: EventWindowBinding,
    case: str,
    data: Mapping[str, object],
    events: list[Mapping[str, object]],
) -> None:
    project_path = binding.project_path
    if case == "B3":
        _require_witness_text(data, "person", "first_driver", "wait_key")
        _require_event(
            events,
            "sdlc.todo.waiting",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PERSON: data.get("person"),
                FIELD_WAITED_PHASE: "preparation",
                FIELD_WAIT: data.get("wait_key"),
            },
        )
        _require_event(
            events,
            "sdlc.todo.claim_changed",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PRIOR_HOLDER: None,
                FIELD_HOLDER: data.get("first_driver"),
            },
        )
        _require_event(
            events,
            "sdlc.todo.claim_changed",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PRIOR_HOLDER: data.get("first_driver"),
                FIELD_HOLDER: None,
            },
        )
        _require_phase(events, project_path, "preparation", "waiting")
        _require_phase(events, project_path, "waiting", "preparation")
    elif case == "B4":
        _require_witness_text(data, "author", "child", "worker", "R0", "R1", "R2")
        _require_phase(events, project_path, "preparation", "prepared")
        _require_phase(events, project_path, "prepared", "work")
    elif case == "B5":
        _require_witness_text(
            data,
            "w2",
            "w3",
            "C1",
            "C2",
            "C3",
            "finding_key",
            "ready_since_C2",
            "ready_since_C3",
            "lane_one",
            "lane_two",
        )
        _require_event(
            events,
            "sdlc.todo.claim_changed",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PRIOR_HOLDER: None,
                FIELD_HOLDER: data.get("w2"),
            },
        )
        _require_event(
            events,
            "sdlc.todo.claim_changed",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PRIOR_HOLDER: data.get("w2"),
                FIELD_HOLDER: None,
            },
        )
        for _label, sha in (("C1", data.get("C1")), ("C2", data.get("C2")), ("C3", data.get("C3"))):
            _require_event(
                events,
                "sdlc.todo.head_advanced",
                {FIELD_SLUG: ITEM, FIELD_PROJECT_PATH: project_path, FIELD_BRANCH: ITEM, FIELD_SHA: sha},
            )
        _require_event(
            events,
            "sdlc.todo.ready",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_BRANCH: ITEM,
                FIELD_SHA: data.get("C2"),
                FIELD_DRIVER: data.get("w2"),
                FIELD_READY_AT: data.get("ready_since_C2"),
            },
        )
        _require_event(
            events,
            "sdlc.todo.ready",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_BRANCH: ITEM,
                FIELD_SHA: data.get("C3"),
                FIELD_DRIVER: data.get("w3"),
                FIELD_READY_AT: data.get("ready_since_C3"),
            },
        )
        _require_phase(events, project_path, "work", "ready")
    elif case == "B7":
        _require_witness_text(
            data, "w4", "first", "second", "reason_one_note", "reason_two_note", "reason_one", "reason_two"
        )
        _require_event(
            events,
            "sdlc.todo.claim_changed",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PRIOR_HOLDER: None,
                FIELD_HOLDER: data.get("w4"),
            },
        )
        _require_event(
            events,
            "sdlc.todo.claim_changed",
            {
                FIELD_SLUG: ITEM,
                FIELD_PROJECT_PATH: project_path,
                FIELD_PRIOR_HOLDER: data.get("w4"),
                FIELD_HOLDER: None,
            },
        )


def _require_event(events: list[Mapping[str, object]], event_type: str, expected: Mapping[str, object]) -> None:
    for row in events:
        data = row.get(FIELD_EVENT_DATA)
        if (
            row.get(FIELD_TYPE) == event_type
            and isinstance(data, Mapping)
            and all(key in data and data.get(key) == value for key, value in expected.items())
        ):
            return
    raise creation.platform_failure(DETAIL_EVENT.format(detail=f"{event_type}: {dict(expected)!r}"))


def _require_phase(events: list[Mapping[str, object]], project_path: str, previous: str, current: str) -> None:
    _require_event(
        events,
        "sdlc.todo.phase_advanced",
        {
            FIELD_SLUG: ITEM,
            FIELD_PROJECT_PATH: project_path,
            FIELD_PRIOR_PHASE: previous,
            FIELD_LIFECYCLE_PHASE: current,
        },
    )


def _coverage_complete(coverage: Mapping[str, object]) -> bool:
    limits = coverage.get(FIELD_LIMITS)
    return (
        coverage.get(FIELD_COMPLETE) is True
        and coverage.get(FIELD_RETAINED_ONLY) is True
        and isinstance(coverage.get(FIELD_RETAINED_FROM), (str, type(None)))
        and isinstance(coverage.get(FIELD_RETAINED_TO), (str, type(None)))
        and isinstance(limits, list)
        and all(isinstance(limit, str) for limit in limits)
        and EXPECTED_RETAINED_LIMIT in limits
        and EXPECTED_COMPUTER_LIMIT in limits
    )


def _coverage_has_undecodable(coverage: Mapping[str, object]) -> bool:
    limits = coverage.get(FIELD_LIMITS)
    return isinstance(limits, list) and any(UNDECODABLE_LIMIT in str(limit) for limit in limits)


def _require_witness_text(data: Mapping[str, object], *fields: str) -> None:
    if any(not isinstance(data.get(field), str) or not data.get(field) for field in fields):
        raise creation.binding_failure(DETAIL_SEAL)


def _assert_log_payloads(case: str, data: Mapping[str, object], log: str) -> None:
    entries = parse_log_entries(log)
    if case == "B3":
        _require_witness_text(data, "person", "first_driver", "owner", "question", "answer")
        _require_log_record(
            entries, ROLE_PREPARE, str(data["first_driver"]), "waiting", str(data["person"]), str(data["question"])
        )
        _require_log_record(entries, "", str(data["owner"]), "decision", str(data["person"]), str(data["answer"]))
        return
    if case == "B4":
        _require_witness_text(data, "author", "worker", "R1")
        _require_log_record(entries, ROLE_PREPARE, str(data["author"]), "prepared", str(data["R1"]), "")
        _require_log_record(
            entries,
            ROLE_WORK,
            str(data["worker"]),
            ACT_CLAIM,
            None,
            WORK_CLAIM_BODY.format(item=ITEM, role=ROLE_WORK, session=data["worker"], branch=ITEM),
        )
        return
    if case == "B5":
        _require_witness_text(data, "w2", "builder", "w3", "C1", "C2", "C3", "finding_key")
        w2, builder, w3, c1, c2, c3, finding_key = (
            str(data[name]) for name in ("w2", "builder", "w3", "C1", "C2", "C3", "finding_key")
        )
        finding_digest = hashlib.sha256(FINDING_TEXT.encode(ENCODING)).hexdigest()[:16]
        reply_digest = hashlib.sha256(REPLY_TEXT.encode(ENCODING)).hexdigest()[:16]
        _require_log_record(entries, ROLE_WORK, w2, ACT_REVIEWED, c1, "")
        _require_log_record(entries, ROLE_WORK, w2, ACT_FINDING, f"{c1}:{finding_digest}", FINDING_TEXT)
        _require_log_record(entries, ROLE_BUILDER, builder, ACT_REPLY, f"{finding_key}:{reply_digest}", REPLY_TEXT)
        _require_log_record(entries, ROLE_WORK, w2, ACT_STAMP, c2, LANE_ONE)
        _require_log_record(
            entries,
            ROLE_WORK,
            w3,
            ACT_CLAIM,
            None,
            WORK_CLAIM_BODY.format(item=ITEM, role=ROLE_WORK, session=w3, branch=ITEM),
        )
        _require_log_record(entries, ROLE_WORK, w3, ACT_STAMP, c3, LANE_TWO)
        return
    if case == "B7":
        _require_witness_text(data, "first", "second", "w4", "reason_one", "reason_two")
        first = str(data["first"])
        second = str(data["second"])
        w4 = str(data["w4"])
        reason_one = str(data["reason_one"])
        reason_two = str(data["reason_two"])
        first_digest = hashlib.sha256(reason_one.encode(ENCODING)).hexdigest()[:16]
        second_digest = hashlib.sha256(reason_two.encode(ENCODING)).hexdigest()[:16]
        _require_log_record(entries, "", first, "note", first_digest, reason_one)
        _require_log_record(entries, "", second, "note", second_digest, reason_two)
        _require_log_record(entries, ROLE_WORK, w4, "release", w4, "")


def _require_log_record(
    entries: list[LogEntry], role: str, session: str, act: str, bound: str | None, body: str
) -> None:
    matches = [
        entry
        for entry in entries
        if entry.role == role
        and entry.session == session
        and entry.act == act
        and entry.bound == bound
        and entry.body == body
    ]
    if len(matches) != 1:
        raise creation.platform_failure(
            DETAIL_EVENT.format(detail=f"log {act} record for {session} has {len(matches)} exact matches")
        )
