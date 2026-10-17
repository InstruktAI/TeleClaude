"""Journey B3 of the workflow acceptance: a driver waits on the owner, a dispatched session cannot decide, the owner\'s can.

The journey\'s assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/b3-waiting-decision-assertion-draft.md`, approved at exact SHA-256
dd390a30129379b499339eb972d8f805ef30cd4893904b9b84498be5fdc953c4, with the approved setup amendment that this case owns
its publication preparation; it reuses the B1 draft 8139046b04adbf9219f29b472e8bb49e513da9cd7946ee60ddfaf0bb964df1e6
with its act-row amendment d7270641fcb963b66f58c79201ac936d293358665b967f493a7e625a3eac0728 and its title amendment
f9a4d846c18e44c8d5a65082532a2e0245ab357b4f33254843977e6db81e600f, and the B2 per-launch pool; authority the pending
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and `.../procedure-entry` contracts of issue 128).

On the published installation a real preparation driver claims, starts its child and performs `waiting` naming the
owner: the item waits, the claim is released, the live child is closed, every entry point refuses naming the owner. A
session dispatched from the owner\'s own session carries the owner\'s lineage and cannot decide, but its note stays in
the log. After the owner ends the first driver, the owner\'s own roleless session decides and exactly one next driver
starts and claims.

Its close follows amendment A4, `journeys/b2-b3-b4-close-hold-handover-amendment-rev2-draft.md` at exact SHA-256
6871ce0dae59a98e6c24f3de945b3f2e2cb51c74daf847a2ee96820f8f522b21 (see `workflow_handover`): the owner\'s manual end of
a holding driver sets the session-close hold, which the case classifies and releases explicitly before it ends.

It proves no event, no stored waited phase, no prepared/work/ready/delivery, no racing decisions and no model
following; the order of the child\'s end and the claim\'s release inside the act is a source-review obligation. This
controller creates no session record, role, reservation, identity or authentication state, reads no private store and
imports no application module. Identity limit: the client carries the session context (same-computer, client-asserted).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from dataclasses import field as dataclass_field
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from tools.ci import acceptance_work as payload_work
from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_events as events
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_handover as handover
from tools.ci import workflow_publication as publication
from tools.ci.workflow_foundation import FoundationHost

TELEC: Final = "bin/telec"
TODO: Final = "todo"
CONFIG: Final = "config"
PERSON: Final = "person"
GET: Final = "get"
FORMAT_OPTION: Final = "--format"
JSON_FORMAT: Final = "json"
SESSIONS: Final = "sessions"
START: Final = "start"
ITEM: Final = "b3-item"
CONTENT: Final = "b3 waiting content"
CONTROL_NAME: Final = "native-fixture-control-b3"

QUESTION: Final = "which of these outcomes do you want"
ANSWER: Final = "answer from the owner session"
ANSWER_DISPATCHED: Final = "answer from the dispatched session"
NOTE_TEXT: Final = "context from the dispatched session"
DISPATCH_MESSAGE: Final = "b3 dispatched probe"
CHILD_PROCEDURE: Final = "sdlc/procedure/lifecycle/prepare/intake-v2"
CHILD_ROLE: Final = "intaker"
DRIVER_ROLE: Final = "prepare-orchestrator"
PHASE_WAITING: Final = "waiting"
PHASE_PREPARATION: Final = "preparation"
B13_ASSERTION_PATH: Final = "journeys/b13-waiting-retired-kickback-budget-final.md"
B13_ASSERTION_SHA: Final = "475e83482b23a70873dbb62d8e40ce8fb9185e4ee38708a2a8e9de9fb76ab2b0"
B13_ISSUE_REVISION: Final = "UCE_lAHOQMTdPc8AAAABXPR6wc8AAAABB_Nr9Q"


class B13Status(StrEnum):
    """Closed B13 report status vocabulary."""

    NOT_SELECTED = "not_selected"
    NOT_RUN = "not_run"
    PARTIAL = "partial"
    COMPLETE = "complete"
    UNPROVEN = "unproven"


class B13AttemptEvent(StrEnum):
    """Closed B13 append-only ledger event vocabulary."""

    OPEN = "open"
    RESULT = "result"
    PUBLIC_READ = "public_read"


class B13Framing(StrEnum):
    """Closed B13 attempt-ledger framing vocabulary."""

    COMPLETE = "complete_newline_terminated_jsonl"
    PARTIAL = "partial_trailing_record"


class B13OperationState(StrEnum):
    """Closed sentinels for a receipt state that is absent or unreadable."""

    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


B13_STATUS_NOT_SELECTED: Final = B13Status.NOT_SELECTED
B13_STATUS_NOT_RUN: Final = B13Status.NOT_RUN
B13_STATUS_PARTIAL: Final = B13Status.PARTIAL
B13_STATUS_COMPLETE: Final = B13Status.COMPLETE
B13_STATUS_UNPROVEN: Final = B13Status.UNPROVEN
B13_SCENARIO_SECONDS: Final = 600.0
B13_REASON_TEXT: Final = "b13 waiting door"
B13_DIRECTORY: Final = "b13-waiting-kickback"
B13_MARKER_FILE: Final = "RETAINED.json"
B13_ATTEMPTS_FILE: Final = "attempts.jsonl"
B13_CARRIER_SUFFIX: Final = ".b13-waiting-kickback.json"
B13_RETENTION_KEY: Final = "b13-waiting-kickback"
B13_RETENTION_REASON: Final = (
    "B13 waiting kickback unresolved; retain candidate publication, waiting control pool and profile resources "
    "until a terminal negative refusal, unchanged public readbacks and valid report seal exist"
)
B13_ERROR_PREFIX: Final = "B13 waiting kickback evidence is unproven: "
B13_ERROR_DEADLINE: Final = "the 600-second scenario deadline expired"
B13_ERROR_CARRIER: Final = "the report-side carrier is not outside the disposable profile root"
B13_ERROR_ALREADY_EXISTS: Final = "the owned B13 evidence directory or carrier already exists"
B13_ERROR_WAITING: Final = "the item no longer matches B3's waiting checkpoint"
B13_ERROR_START_OPEN: Final = "a B3 start attempt is still unresolved"
B13_ERROR_REFUSAL: Final = "the public kickback call was not one terminal HTTP 409 refusal"
B13_ERROR_DIAGNOSTIC: Final = "the public kickback call carries a command diagnostic"
B13_ERROR_SNAPSHOT_MISSING: Final = "the independently reviewed complete-output snapshot is missing"
B13_ERROR_SNAPSHOT_MISMATCH: Final = "the complete public kickback output differs from its reviewed snapshot"
B13_ERROR_CHANGED: Final = "public state changed after the refusal: {differences}"
B13_ERROR_SEAL: Final = "the B13 evidence carrier failed its byte/hash read-back"
B13_ERROR_READBACK_COUNT: Final = "B13 did not capture all six required post-call observations"


def _require_b13_completed_result(outcome: foundation.Outcome, operation: str | None) -> None:
    """Allow effect readbacks only after one completed nonzero command without a receipt or diagnostic."""
    if outcome.exit_status in (None, B13_SUCCESS_EXIT) or operation is not None:
        raise ValueError(B13_ERROR_REFUSAL)
    if outcome.diagnostics:
        raise ValueError(B13_ERROR_DIAGNOSTIC)


def _require_b13_snapshot(output: str) -> None:
    """Require the complete public refusal to match its reviewed snapshot."""
    snapshot_state = creation.retired_snapshot_state(creation.RETIRED_SNAPSHOT_B13_KICKBACK, output)
    if snapshot_state is creation.RetiredSnapshotState.MISSING:
        raise ValueError(B13_ERROR_SNAPSHOT_MISSING)
    if snapshot_state is creation.RetiredSnapshotState.MISMATCH:
        raise ValueError(B13_ERROR_SNAPSHOT_MISMATCH)


B13_CALL_ARGV: Final = ("bin/telec", "todo", "stamp", "b3-item", "--kickback", "--reason", B13_REASON_TEXT)
B13_READ_ARGV: Final = (
    ("bin/telec", "todo", "show", ITEM, "--include-artifact-content"),
    ("bin/telec", "sessions", "list", "--all", "--closed"),
    ("bin/telec", "todo", "list", "--json", "--include-icebox", "--include-delivered", "--include-removed"),
)
B13_UTF8: Final = "utf-8"
B13_NEWLINE: Final = "\n"
B13_JSON_SEPARATORS: Final = (",", ":")
B13_TEMP_SUFFIX: Final = ".tmp"
B13_FILE_MODE: Final = 0o600
B13_SUCCESS_EXIT: Final = 0
B13_SETTLE_SECONDS: Final = 5.0
B13_SCHEMA_VERSION: Final = 2
B13_ATTEMPT_OPEN: Final = B13AttemptEvent.OPEN
B13_ATTEMPT_RESULT: Final = B13AttemptEvent.RESULT
B13_OBSERVATION_BEFORE: Final = "before"
B13_OBSERVATION_IMMEDIATE: Final = "immediate"
B13_OBSERVATION_SETTLED: Final = "settled"
B13_EVENT: Final = "event"
B13_PRECALL: Final = "pre_call"
B13_RESPONSE: Final = "response"
B13_PUBLIC_READ: Final = B13AttemptEvent.PUBLIC_READ
B13_STATUS_FIELD: Final = "status"
B13_REASON_FIELD: Final = "reason"
B13_SOURCE_REVISION_FIELD: Final = "source_revision"
B13_SOURCE_TREE_FIELD: Final = "source_tree"
B13_ISSUE_REVISION_FIELD: Final = "issue_revision"
B13_ASSERTION_SHA_FIELD: Final = "assertion_sha256"
B13_CARRIER_SHA_FIELD: Final = "carrier_sha256"
B13_CARRIER_BYTES_FIELD: Final = "carrier_byte_count"
B13_MARKER_SHA_FIELD: Final = "marker_sha256"
B13_MARKER_BYTES_FIELD: Final = "marker_byte_count"
B13_MARKER_PATH_FIELD: Final = "marker_path"
B13_CARRIER_PATH_FIELD: Final = "carrier_path"
B13_REPORT_PATH_FIELD: Final = "report_path"
B13_ATTEMPTS_PATH_FIELD: Final = "attempts_path"
B13_ATTEMPTS_SHA_FIELD: Final = "attempts_sha256"
B13_ATTEMPTS_BYTES_FIELD: Final = "attempts_byte_count"
B13_ATTEMPTS_TEXT_FIELD: Final = "attempts_sanitized_text"
B13_ATTEMPTS_TEXT_TRUNCATED_FIELD: Final = "attempts_text_truncated"
B13_ATTEMPTS_FRAMING_FIELD: Final = "attempts_framing"
B13_ATTEMPTS_COUNT_FIELD: Final = "attempts_record_count"
B13_ATTEMPTS_EXPECTED_RECORDS: Final = 11
B13_FRAMING_COMPLETE: Final = B13Framing.COMPLETE
B13_FRAMING_PARTIAL: Final = B13Framing.PARTIAL
B13_ITEM_FIELD: Final = "item"
B13_ARGV_FIELD: Final = "argv"
B13_BEFORE_FIELD: Final = "before"
B13_READBACKS_FIELD: Final = "readbacks"
B13_ACTORS_FIELD: Final = "actors"
B13_CANDIDATE_FIELD: Final = "candidate_identity"
B13_CONTROL_PATHS_FIELD: Final = "control_paths"
B13_DURATION_FIELD: Final = "duration_seconds"
B13_OUTPUT_FIELD: Final = "output"
B13_STDERR_FIELD: Final = "stderr"
B13_DIAGNOSTICS_FIELD: Final = "diagnostics"
B13_EXIT_FIELD: Final = "exit_status"
B13_OPERATION_FIELD: Final = "operation_id"
B13_OPERATION_STATUS_FIELD: Final = "operation_status"
B13_OPERATION_NOT_APPLICABLE: Final = B13OperationState.NOT_APPLICABLE
B13_OPERATION_UNKNOWN: Final = B13OperationState.UNKNOWN
B13_LEDGER_ORIGINAL_SHA_FIELD: Final = "original_sha256"
B13_LEDGER_ORIGINAL_BYTES_FIELD: Final = "original_byte_count"
B13_LEDGER_PATH_FIELD: Final = "path"
B13_LEDGER_READ_ERROR_FIELD: Final = "read_error"
B13_LEDGER_TEXT_FIELD: Final = "sanitized_text"
B13_LEDGER_TEXT_TRUNCATED_FIELD: Final = "sanitized_text_truncated"
B13_LEDGER_FRAMING_FIELD: Final = "framing"
B13_LEDGER_RECORD_COUNT_FIELD: Final = "record_count"
B13_LEDGER_PARSE_ERROR_FIELD: Final = "parse_error"
B13_ERROR_DETAIL_FORMAT: Final = "{error_class}: {detail}"
B13_BYTE_NEWLINE: Final = b"\n"
B13_EVIDENCE_FIELD: Final = "evidence"
B13_PRIMARY_FAILURE_FIELD: Final = "primary_failure"
B13_EVIDENCE_FAILURE_FIELD: Final = "evidence_failure"
B13_EXPORT_FAILURE_FIELD: Final = "export_failure"
B13_DIAGNOSTIC_LIMIT: Final = 65536

FRAME_CLAIM: Final = "cmd_claim"
FRAME_CHILD: Final = "cmd_child"
FRAME_WAITING: Final = "cmd_waiting"
FRAME_DISPATCH: Final = "cmd_dispatchx"
FRAME_REFUSED: Final = "cmd_refused"
FRAME_NOTE: Final = "cmd_note"
FRAME_DECISION: Final = "cmd_decision"
GATE_WAITING: Final = "go_waiting"
GATE_DISPATCH: Final = "go_x"
GATE_REFUSED: Final = "go_xd"
GATE_NOTE: Final = "go_xn"
GATE_DECISION: Final = "go_decision"
ARGV_REFUSED: Final = "xdecision.argv"
ARGV_DECISION: Final = "decision.argv"

STARTED_CHILD: Final = re.compile(r"Started (?P<procedure>\S+) as session (?P<session>\S+)")
WAIT_COMPLETE: Final = re.compile(r"^Performed waiting on " + re.escape(ITEM) + r".*, complete\s*$", re.MULTILINE)
NOTE_HEADER: Final = re.compile(r" · note(?: \(|$)")
WAIT_KEY: Final = re.compile(r"wait key: (?P<key>\S+)")
PERFORMED: Final = "Performed {act} on {item}"

START_CAP_SECONDS: Final = 900.0
FRAME_SECONDS: Final = 60.0
POLL_SECONDS: Final = 2.0
LAUNCH_SECONDS: Final = 30.0
OPERATION_SECONDS: Final = 60.0

FIELD_PRINCIPAL: Final = "principal"
FIELD_INITIATOR: Final = "initiator_session_id"
FIELD_ROLE: Final = "role"
FIELD_JOB: Final = "job"
FIELD_CLOSED_AT: Final = foundation.FIELD_CLOSED_AT
FIELD_LIFECYCLE: Final = foundation.FIELD_LIFECYCLE
FIELD_STATE: Final = publication.FIELD_STATE
FIELD_ERROR: Final = publication.FIELD_ERROR
STATE_FAILED: Final = publication.STATE_FAILED

DETAIL_PERSON: Final = "the configured owner {slug} does not read email {email!r}: {output!r}"
DETAIL_FACTS: Final = "{actor} {session}: record facts {found!r} are not the contract's definition {expected!r}"
DETAIL_FRAME: Final = "the fixture frame {name} is not a completed public call: {frame!r}"
DETAIL_CHILD: Final = "the child frame printed {stdout!r}, not `Started {procedure} as session <id>`"
DETAIL_CHILD_RECORD: Final = "the child {session} record has {field} {found!r}, not {expected!r}"
DETAIL_LIVE: Final = "{actor} {session} is not live and unclosed {when}: {record!r}"
DETAIL_WAIT: Final = "the waiting act printed {stdout!r}, lacking {needle!r}"
DETAIL_SHOWN: Final = "{when}: {path} is {found!r}, not {expected!r}"
DETAIL_CLOSED: Final = "{actor} {session} is not closed {when}: {record!r}"
DETAIL_LOG: Final = "{when}: the log does not show {needle!r}: {log!r}"
DETAIL_LOG_COUNT: Final = "{when}: the log holds {count} headers {kind!r}, not {expected}: {headers!r}"
DETAIL_ENTRY_REFUSED: Final = "the prepare while waiting ended {state!r} ({error!r}), not a refusal naming {needles!r}"
DETAIL_SESSIONS: Final = "{when}: the sessions beyond the baseline are {found!r}, not {expected!r}"
DETAIL_REFUSAL: Final = "the dispatched session's decision {problem}: exit {status}, {output!r}"
DETAIL_CHANGED: Final = "{when}: the item differs from before at {paths}"
DETAIL_NOT_DRIVER: Final = "session {session} holds the driver role {role!r}; only the second driver may"
DETAIL_POOL: Final = "the pool directories claimed are {found!r}, not the planned {expected!r}"
DETAIL_NOT_STARTED: Final = "{actor} {session} never showed a completed startup within {seconds} seconds: {record!r}"
LATE_ARGV_UNREADABLE: Final = "late argument list unreadable"
DETAIL_LATE_UNREADABLE: Final = "the fixture could not read the late-bound argument list of {name}: {frame!r}"
DETAIL_MAPPING: Final = (
    "{actor} {session}: the record names native session {recorded!r}, but its pool directory launched {launched!r}"
)
DETAIL_LATE_ARGV: Final = "the late-bound argument list {name} could not be written: {error}"
DETAIL_RECEIPT: Final = "`telec todo prepare` printed no operation receipt: exit {status}, {output!r}"
DETAIL_CONTROLS_KEPT: Final = "closure was not proven, so the control directories {control} are kept for diagnosis"

type Json = Mapping[str, object]


@dataclass
class WaitingKickbackEvidence:
    """Typed report evidence for B13's waiting-door retired kickback assertion."""

    schema_version: int
    status: B13Status
    assertion_path: str
    assertion_sha256: str
    issue_revision: str
    source_revision: str
    source_tree: str
    item: str
    argv: list[str]
    prerequisites: creation.EvidenceObject = dataclass_field(default_factory=dict)
    before: creation.EvidenceObject = dataclass_field(default_factory=dict)
    response: creation.EvidenceObject = dataclass_field(default_factory=dict)
    readbacks: list[creation.EvidenceObject] = dataclass_field(default_factory=list)
    attempt_ledger: creation.EvidenceObject = dataclass_field(default_factory=dict)
    carrier: creation.EvidenceObject = dataclass_field(default_factory=dict)
    duration_seconds: float = 0.0
    primary_failure: str = ""
    evidence_failure: str = ""
    export_failure: str = ""


def empty_b13_evidence(
    *, status: B13Status = B13_STATUS_NOT_SELECTED, source_revision: str = "", source_tree: str = ""
) -> WaitingKickbackEvidence:
    """Create a fail-closed typed B13 state for every report profile."""
    return WaitingKickbackEvidence(
        schema_version=B13_SCHEMA_VERSION,
        status=status,
        assertion_path=B13_ASSERTION_PATH,
        assertion_sha256=B13_ASSERTION_SHA,
        issue_revision=B13_ISSUE_REVISION,
        source_revision=source_revision,
        source_tree=source_tree,
        item=ITEM,
        argv=list(B13_CALL_ARGV),
    )


def _b13_safe(value: object, sanitize: Callable[[str], str]) -> creation.EvidenceValue:
    """Sanitize path-bearing evidence recursively without changing non-text values."""
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, Mapping):
        return {str(key): _b13_safe(item, sanitize) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_b13_safe(item, sanitize) for item in value]
    return cast(creation.EvidenceValue, value)


def _b13_payload(evidence: WaitingKickbackEvidence) -> creation.EvidenceObject:
    """Canonical report payload whose exact bytes are carried outside disposable profile state."""
    payload = asdict(evidence)
    payload.pop("carrier", None)
    return cast(creation.EvidenceObject, payload)


def _b13_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=B13_JSON_SEPARATORS) + B13_NEWLINE).encode(B13_UTF8)


def _b13_fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _b13_write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, B13_FILE_MODE)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _b13_atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + B13_TEMP_SUFFIX)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, B13_FILE_MODE)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    temporary.replace(path)
    _b13_fsync_directory(path.parent)


def _b13_append(path: Path, record: Mapping[str, object]) -> None:
    payload = _b13_json_bytes(record)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    try:
        with os.fdopen(descriptor, "ab", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def capture_b13_attempt_ledger(
    evidence: WaitingKickbackEvidence, marker_path: Path, sanitize: Callable[[str], str]
) -> None:
    """Record the latest readable ledger bytes in report memory without refreshing a failed seal."""
    attempts_path = marker_path.parent / B13_ATTEMPTS_FILE
    try:
        attempts_raw = attempts_path.read_bytes()
    except OSError as error:
        evidence.attempt_ledger = {
            B13_LEDGER_PATH_FIELD: sanitize(str(attempts_path)),
            B13_LEDGER_READ_ERROR_FIELD: sanitize(
                B13_ERROR_DETAIL_FORMAT.format(error_class=type(error).__name__, detail=error)
            ),
        }
        return
    attempts_text = sanitize(attempts_raw.decode(B13_UTF8, errors="replace"))
    attempts_records = 0
    parse_error = ""
    for line in attempts_raw.splitlines():
        if line:
            try:
                json.loads(line)
                attempts_records += 1
            except (UnicodeDecodeError, ValueError) as error:
                parse_error = B13_ERROR_DETAIL_FORMAT.format(error_class=type(error).__name__, detail=error)
                break
    evidence.attempt_ledger = {
        B13_LEDGER_ORIGINAL_SHA_FIELD: hashlib.sha256(attempts_raw).hexdigest(),
        B13_LEDGER_ORIGINAL_BYTES_FIELD: len(attempts_raw),
        B13_LEDGER_TEXT_FIELD: attempts_text[:B13_DIAGNOSTIC_LIMIT],
        B13_LEDGER_TEXT_TRUNCATED_FIELD: len(attempts_text) > B13_DIAGNOSTIC_LIMIT,
        B13_LEDGER_FRAMING_FIELD: (
            B13_FRAMING_COMPLETE if not attempts_raw or attempts_raw.endswith(B13_BYTE_NEWLINE) else B13_FRAMING_PARTIAL
        ),
        B13_LEDGER_RECORD_COUNT_FIELD: attempts_records,
        B13_LEDGER_PATH_FIELD: sanitize(str(attempts_path.resolve())),
        B13_LEDGER_READ_ERROR_FIELD: "",
        B13_LEDGER_PARSE_ERROR_FIELD: sanitize(parse_error),
    }


def append_b13_attempt(
    evidence: WaitingKickbackEvidence,
    marker_path: Path,
    carrier_path: Path,
    record: Mapping[str, object],
    sanitize: Callable[[str], str],
    *,
    final_elapsed_start: float | None = None,
) -> None:
    """Append one exact ledger frame only after the prior seal and ledger bytes validate."""
    attempts_path = marker_path.parent / B13_ATTEMPTS_FILE
    previous = attempts_path.read_bytes()
    prior = evidence.attempt_ledger
    if prior:
        if (
            hashlib.sha256(previous).hexdigest() != prior.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
            or len(previous) != prior.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
            or not verify_b13_seal(evidence, marker_path, carrier_path)
        ):
            raise ValueError(B13_ERROR_SEAL)
    elif marker_path.exists() or carrier_path.read_bytes() or previous:
        raise ValueError(B13_ERROR_SEAL)
    frame = _b13_json_bytes(record)
    _b13_append(attempts_path, record)
    updated = attempts_path.read_bytes()
    if updated != previous + frame:
        raise ValueError(B13_ERROR_SEAL)
    freeze_b13_evidence(evidence, marker_path, carrier_path, sanitize, authorized_append=frame)
    if final_elapsed_start is not None:
        evidence.duration_seconds = time.monotonic() - final_elapsed_start
        if evidence.duration_seconds > B13_SCENARIO_SECONDS:
            evidence.status = B13_STATUS_UNPROVEN
            evidence.primary_failure = B13_ERROR_DEADLINE
        if not verify_b13_seal(evidence, marker_path, carrier_path):
            raise ValueError(B13_ERROR_SEAL)
        freeze_b13_evidence(evidence, marker_path, carrier_path, sanitize, authorized_refresh=frame)


def _b13_marker_record(evidence: WaitingKickbackEvidence) -> creation.EvidenceObject:
    """Persist the B13 ownership key and current evidence-carrier seal in the retained marker."""
    return cast(
        creation.EvidenceObject,
        {
            "schema_version": B13_SCHEMA_VERSION,
            B13_STATUS_FIELD: evidence.status,
            B13_REASON_FIELD: B13_RETENTION_REASON,
            B13_SOURCE_REVISION_FIELD: evidence.source_revision,
            B13_SOURCE_TREE_FIELD: evidence.source_tree,
            B13_ISSUE_REVISION_FIELD: evidence.issue_revision,
            B13_ASSERTION_SHA_FIELD: evidence.assertion_sha256,
            B13_ITEM_FIELD: evidence.item,
            B13_ARGV_FIELD: evidence.argv,
            B13_BEFORE_FIELD: evidence.before,
            B13_ACTORS_FIELD: evidence.prerequisites.get(B13_ACTORS_FIELD, {}),
            B13_CANDIDATE_FIELD: evidence.prerequisites.get(B13_CANDIDATE_FIELD, ""),
            B13_CONTROL_PATHS_FIELD: evidence.prerequisites.get(B13_CONTROL_PATHS_FIELD, []),
            B13_ATTEMPTS_PATH_FIELD: evidence.carrier.get(B13_ATTEMPTS_PATH_FIELD, ""),
            B13_ATTEMPTS_SHA_FIELD: evidence.attempt_ledger.get("original_sha256", ""),
            B13_ATTEMPTS_BYTES_FIELD: evidence.attempt_ledger.get("original_byte_count", 0),
            B13_CARRIER_PATH_FIELD: evidence.carrier.get(B13_CARRIER_PATH_FIELD, ""),
            B13_REPORT_PATH_FIELD: evidence.carrier.get(B13_REPORT_PATH_FIELD, ""),
            B13_CARRIER_SHA_FIELD: evidence.carrier.get(B13_CARRIER_SHA_FIELD, ""),
            B13_CARRIER_BYTES_FIELD: evidence.carrier.get(B13_CARRIER_BYTES_FIELD, 0),
        },
    )


def freeze_b13_evidence(
    evidence: WaitingKickbackEvidence,
    marker_path: Path,
    carrier_path: Path,
    sanitize: Callable[[str], str],
    *,
    authorized_bootstrap: bool = False,
    authorized_append: bytes | None = None,
    authorized_refresh: bytes | None = None,
    authorized_completion: bool = False,
    authorized_failure: bool = False,
) -> None:
    """Refresh a durable seal only when its previous bytes and one authorized append are verified."""
    if evidence.carrier.get("owned") is not True:
        raise ValueError(B13_ERROR_ALREADY_EXISTS)
    attempts_path = marker_path.parent / B13_ATTEMPTS_FILE
    attempts_raw = attempts_path.read_bytes()
    prior = evidence.attempt_ledger
    if authorized_bootstrap:
        if (
            prior
            or attempts_raw
            or evidence.status != B13_STATUS_PARTIAL
            or marker_path.exists()
            or carrier_path.read_bytes()
            or authorized_append is not None
            or authorized_refresh is not None
            or authorized_completion
            or authorized_failure
        ):
            raise ValueError(B13_ERROR_SEAL)
    elif authorized_failure:
        if (
            not prior
            or evidence.status != B13_STATUS_UNPROVEN
            or not evidence.primary_failure
            or hashlib.sha256(attempts_raw).hexdigest() != prior.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
            or len(attempts_raw) != prior.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
            or not verify_b13_seal(evidence, marker_path, carrier_path)
            or authorized_append is not None
            or authorized_refresh is not None
            or authorized_completion
        ):
            raise ValueError(B13_ERROR_SEAL)
    elif authorized_completion:
        prior_size = prior.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
        prior_hash = prior.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
        prior_evidence = replace(evidence, status=B13_STATUS_PARTIAL)
        if (
            evidence.status != B13_STATUS_COMPLETE
            or type(prior_size) is not int
            or not isinstance(prior_hash, str)
            or hashlib.sha256(attempts_raw).hexdigest() != prior_hash
            or len(attempts_raw) != prior_size
            or carrier_path.read_bytes() != _b13_json_bytes(_b13_safe(_b13_payload(prior_evidence), sanitize))
            or marker_path.read_bytes() != _b13_json_bytes(_b13_safe(_b13_marker_record(prior_evidence), sanitize))
            or not verify_b13_seal(prior_evidence, marker_path, carrier_path)
            or authorized_append is not None
            or authorized_refresh is not None
        ):
            raise ValueError(B13_ERROR_SEAL)
    elif authorized_refresh is not None:
        if (
            not prior
            or not attempts_raw.endswith(authorized_refresh)
            or hashlib.sha256(attempts_raw).hexdigest() != prior.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
            or len(attempts_raw) != prior.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
            or not verify_b13_seal(evidence, marker_path, carrier_path)
        ):
            raise ValueError(B13_ERROR_SEAL)
    elif prior:
        prior_size = prior.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
        prior_hash = prior.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
        if (
            type(prior_size) is not int
            or not isinstance(prior_hash, str)
            or len(attempts_raw) != prior_size + (len(authorized_append) if authorized_append is not None else 0)
            or hashlib.sha256(attempts_raw[:prior_size]).hexdigest() != prior_hash
            or (authorized_append is not None and attempts_raw[prior_size:] != authorized_append)
            or (authorized_append is None and hashlib.sha256(attempts_raw).hexdigest() != prior_hash)
            or not verify_b13_seal(evidence, marker_path, carrier_path, check_attempts=False)
        ):
            raise ValueError(B13_ERROR_SEAL)
    elif (
        authorized_append is None
        or attempts_raw != authorized_append
        or marker_path.exists()
        or carrier_path.read_bytes()
    ):
        raise ValueError(B13_ERROR_SEAL)
    ledger_read_error = ""

    attempts_text = sanitize(attempts_raw.decode(B13_UTF8, errors="replace"))
    attempts_lines = attempts_raw.splitlines()
    attempts_records = 0
    ledger_parse_error = ""
    for line in attempts_lines:
        if line:
            try:
                json.loads(line)
                attempts_records += 1
            except (UnicodeDecodeError, ValueError) as error:
                ledger_parse_error = f"{type(error).__name__}: {error}"
                break
    attempts_framing = B13_FRAMING_COMPLETE if not attempts_raw or attempts_raw.endswith(b"\n") else B13_FRAMING_PARTIAL
    evidence.attempt_ledger = {
        B13_LEDGER_ORIGINAL_SHA_FIELD: hashlib.sha256(attempts_raw).hexdigest(),
        B13_LEDGER_ORIGINAL_BYTES_FIELD: len(attempts_raw),
        B13_LEDGER_TEXT_FIELD: attempts_text[:B13_DIAGNOSTIC_LIMIT],
        B13_LEDGER_TEXT_TRUNCATED_FIELD: len(attempts_text) > B13_DIAGNOSTIC_LIMIT,
        B13_LEDGER_FRAMING_FIELD: attempts_framing,
        B13_LEDGER_RECORD_COUNT_FIELD: attempts_records,
        B13_LEDGER_PATH_FIELD: sanitize(str(attempts_path.resolve())),
        B13_LEDGER_READ_ERROR_FIELD: sanitize(ledger_read_error),
        B13_LEDGER_PARSE_ERROR_FIELD: sanitize(ledger_parse_error),
    }
    if evidence.status == B13_STATUS_COMPLETE and (
        attempts_framing != B13_FRAMING_COMPLETE
        or attempts_records != B13_ATTEMPTS_EXPECTED_RECORDS
        or ledger_read_error
        or ledger_parse_error
    ):
        raise ValueError(B13_ERROR_SEAL)
    evidence.carrier[B13_ATTEMPTS_PATH_FIELD] = sanitize(str(attempts_path.resolve()))
    payload = _b13_json_bytes(_b13_safe(_b13_payload(evidence), sanitize))
    _b13_atomic_write(carrier_path, payload)
    carrier_sha = hashlib.sha256(payload).hexdigest()
    evidence.carrier.update(
        {
            B13_CARRIER_PATH_FIELD: sanitize(str(carrier_path.resolve())),
            B13_CARRIER_SHA_FIELD: carrier_sha,
            B13_CARRIER_BYTES_FIELD: len(payload),
            "sanitized": True,
            "carrier_truncated": False,
        }
    )
    _b13_atomic_write(marker_path, _b13_json_bytes(_b13_safe(_b13_marker_record(evidence), sanitize)))
    carrier_read = carrier_path.read_bytes()
    marker_read = marker_path.read_bytes()
    marker_json = json.loads(marker_read)
    if (
        carrier_read != payload
        or hashlib.sha256(carrier_read).hexdigest() != evidence.carrier[B13_CARRIER_SHA_FIELD]
        or len(carrier_read) != evidence.carrier[B13_CARRIER_BYTES_FIELD]
        or not isinstance(marker_json, dict)
        or marker_json.get(B13_CARRIER_SHA_FIELD) != evidence.carrier[B13_CARRIER_SHA_FIELD]
        or marker_json.get(B13_CARRIER_BYTES_FIELD) != evidence.carrier[B13_CARRIER_BYTES_FIELD]
    ):
        raise ValueError(B13_ERROR_SEAL)
    evidence.carrier[B13_MARKER_PATH_FIELD] = sanitize(str(marker_path.resolve()))
    evidence.carrier[B13_MARKER_SHA_FIELD] = hashlib.sha256(marker_read).hexdigest()
    evidence.carrier[B13_MARKER_BYTES_FIELD] = len(marker_read)


def verify_b13_seal(
    evidence: WaitingKickbackEvidence,
    marker_path: Path,
    carrier_path: Path,
    *,
    check_attempts: bool = True,
) -> bool:
    """Verify the retained marker and carrier against their recorded seal without rewriting either."""
    try:
        marker = marker_path.read_bytes()
        carrier = carrier_path.read_bytes()
        record = json.loads(marker)
        attempts_path = marker_path.parent / B13_ATTEMPTS_FILE
        attempts = attempts_path.read_bytes()
        ledger = evidence.attempt_ledger
        return (
            isinstance(record, dict)
            and hashlib.sha256(carrier).hexdigest() == evidence.carrier.get(B13_CARRIER_SHA_FIELD)
            and len(carrier) == evidence.carrier.get(B13_CARRIER_BYTES_FIELD)
            and hashlib.sha256(marker).hexdigest() == evidence.carrier.get(B13_MARKER_SHA_FIELD)
            and len(marker) == evidence.carrier.get(B13_MARKER_BYTES_FIELD)
            and record.get(B13_CARRIER_SHA_FIELD) == evidence.carrier.get(B13_CARRIER_SHA_FIELD)
            and record.get(B13_ATTEMPTS_SHA_FIELD) == ledger.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
            and record.get(B13_ATTEMPTS_BYTES_FIELD) == ledger.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
            and (
                not check_attempts
                or (
                    hashlib.sha256(attempts).hexdigest() == ledger.get(B13_LEDGER_ORIGINAL_SHA_FIELD)
                    and len(attempts) == ledger.get(B13_LEDGER_ORIGINAL_BYTES_FIELD)
                )
            )
        )
    except (OSError, ValueError, TypeError):
        return False


def verify_b13_delivery(
    evidence: WaitingKickbackEvidence,
    marker_path: Path,
    carrier_path: Path,
    sanitize: Callable[[str], str],
) -> bool:
    """Check that a complete report value, external carrier and retained marker all name the same bytes."""
    try:
        carrier = carrier_path.read_bytes()
        marker = marker_path.read_bytes()
        marker_record = json.loads(marker)
        expected_payload = _b13_json_bytes(_b13_safe(_b13_payload(evidence), sanitize))
        return (
            evidence.status == B13_STATUS_COMPLETE
            and verify_b13_seal(evidence, marker_path, carrier_path)
            and carrier == expected_payload
            and hashlib.sha256(carrier).hexdigest() == evidence.carrier.get(B13_CARRIER_SHA_FIELD)
            and len(carrier) == evidence.carrier.get(B13_CARRIER_BYTES_FIELD)
            and hashlib.sha256(marker).hexdigest() == evidence.carrier.get(B13_MARKER_SHA_FIELD)
            and len(marker) == evidence.carrier.get(B13_MARKER_BYTES_FIELD)
            and isinstance(marker_record, dict)
            and marker_record.get(B13_STATUS_FIELD) == B13_STATUS_COMPLETE
            and marker_record.get(B13_CARRIER_SHA_FIELD) == evidence.carrier.get(B13_CARRIER_SHA_FIELD)
        )
    except (OSError, ValueError, TypeError):
        return False


def complete_b13_evidence(
    evidence: WaitingKickbackEvidence,
    marker_path: Path,
    carrier_path: Path,
    sanitize: Callable[[str], str],
) -> None:
    """Commit the verified partial seal's single status transition to complete."""
    if evidence.status != B13_STATUS_PARTIAL or not verify_b13_seal(evidence, marker_path, carrier_path):
        raise ValueError(B13_ERROR_SEAL)
    evidence.status = B13_STATUS_COMPLETE
    freeze_b13_evidence(evidence, marker_path, carrier_path, sanitize, authorized_completion=True)


def log_entries(log: str) -> list[tuple[str, str]]:
    """The exact renderer sections as (header line, body), retaining empty and adjacent entries."""
    return [(entry.header, entry.body) for entry in events.parse_log_entries(log)]


class _Waiting:
    """One run of journey B3."""

    def __init__(
        self,
        host: FoundationHost,
        setup: foundation.FixtureSetup,
        project: Path,
        source_root: Path,
        owner_email: str,
        owner_slug: str,
        register_company: Callable[[], None],
        retain: Callable[[str], None],
        retain_key: Callable[[str, str], None],
        release_key: Callable[[str], None],
        report_path: Path | None,
        b13_evidence: WaitingKickbackEvidence,
        sanitize: Callable[[str], str],
    ) -> None:
        self.host = host
        self.retain = retain
        self.retain_key = retain_key
        self.release_key = release_key
        self.report_path = report_path
        self.b13_evidence = b13_evidence
        self.sanitize = sanitize
        self.observer = creation.Observer(host)
        self.publication = publication.Publication(
            host, self.observer, setup.control.parent, source_root, register_company
        )
        self.controls = controls.Controls(setup, CONTROL_NAME)
        self.source_root = source_root
        self.project = project.resolve()
        self.owner_email = owner_email
        self.owner_slug = owner_slug
        self.baseline: creation.SessionView | None = None
        self.starts: dict[str, str] = {}
        self.setups: list[foundation.FixtureSetup] = []
        self.journeys: dict[str, foundation.Journey] = {}
        self.clone: Path = source_root
        self.person = ""
        self.key = ""
        self.snapshot: Json = {}
        self.decision_attempt = ""
        self.b13_marker: Path | None = None
        self.b13_carrier: Path | None = None
        self.b13_first_claimed = False
        self.b13_waiting_completed = False
        self.b13_child_closed = False
        self.b13_first_live = False
        self.handover = handover.Handover(self.observer, host)
        self.accounting: creation.EvidenceObject | None = None

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _known(self, *sessions: str) -> frozenset[str]:
        assert self.baseline is not None
        return self.baseline.ids | frozenset(sessions)

    def _journey(self, name: str, index: int) -> foundation.Journey:
        journey = foundation.Journey(
            self.host,
            self.setups[index],
            self.project,
            self.owner_email,
            end_evidence=cast(list[creation.EvidenceValue], self.accounting["ends"]) if self.accounting else None,
        )
        self.journeys[name] = journey
        return journey

    def _gate(self, index: int, name: str) -> None:
        (self.setups[index].control / name).write_text("1\n", encoding="utf-8")

    def _late_argv(self, index: int, name: str, argv: list[str]) -> None:
        try:
            (self.setups[index].control / name).write_text(json.dumps(argv), encoding="utf-8")
        except OSError as error:
            raise creation.binding_failure(DETAIL_LATE_ARGV.format(name=name, error=type(error).__name__)) from error

    def _record(self, session: str, effect: creation.EvidenceObject | None = None) -> Json:
        started_ns = time.monotonic_ns()
        outcome = self.observer.run((TELEC, SESSIONS, foundation.SHOW, session, foundation.FULL_FLAG), retain=False)
        finished_ns = time.monotonic_ns()
        if effect is not None:
            cast(list[creation.EvidenceValue], effect["session_reads"]).append(
                creation.command_evidence((TELEC, SESSIONS, foundation.SHOW, session, foundation.FULL_FLAG), outcome)
            )
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        if record is None:
            raise creation.binding_failure(f"session {session} is unreadable: {outcome.output[-300:]!r}")
        if (
            self.accounting is not None
            and record.get(FIELD_CLOSED_AT) is not None
            and record.get(FIELD_LIFECYCLE) == foundation.CLOSED
        ):
            cast(list[creation.EvidenceValue], self.accounting["closed_reads"]).append(
                {
                    "session_id": session,
                    "started_ns": started_ns,
                    "finished_ns": finished_ns,
                    "command": creation.command_evidence(
                        (TELEC, SESSIONS, foundation.SHOW, session, foundation.FULL_FLAG), outcome
                    ),
                }
            )
        return record

    def _frame(self, journey: foundation.Journey, name: str, effect: creation.EvidenceObject | None = None) -> Json:
        """A completed frame of one actor, with its public call and its output."""
        frame = journey.await_frame(name, time.monotonic() + FRAME_SECONDS)
        if effect is not None:
            cast(list[creation.EvidenceValue], effect["frames"]).append(
                {"name": name, "frame": cast(creation.EvidenceValue, dict(frame))}
            )
        run = frame.get("run")
        if not isinstance(run, dict):
            raise creation.platform_failure(DETAIL_FRAME.format(name=name, frame=frame))
        if run.get("error") == LATE_ARGV_UNREADABLE:
            raise creation.binding_failure(DETAIL_LATE_UNREADABLE.format(name=name, frame=frame))
        return frame

    @staticmethod
    def _output(frame: Json) -> tuple[int | None, str]:
        run = frame.get("run")
        assert isinstance(run, dict)
        status = run.get("exit_status")
        text = f"{run.get('stdout', '')}{run.get('stderr', '')}"
        return (status if isinstance(status, int) else None), text

    def _require_pool(self, claimed: int) -> None:
        expected = [self.setups[index].control for index in range(claimed)]
        found = self.controls.claimed()
        if found != expected:
            raise creation.binding_failure(
                DETAIL_POOL.format(found=[path.name for path in found], expected=[path.name for path in expected])
            )

    def _discover(self, known: frozenset[str]) -> str:
        deadline = time.monotonic() + START_CAP_SECONDS
        found: list[str] = []
        while time.monotonic() < deadline:
            found = sorted(self.observer.sessions(retain=False).ids - known)
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise creation.platform_failure(DETAIL_SESSIONS.format(when="discovery", found=found, expected="one"))
            payload_work.sleep(POLL_SECONDS)
        raise creation.platform_failure(DETAIL_SESSIONS.format(when="discovery", found=found, expected="one"))

    def _startup(
        self,
        actor: str,
        session: str,
        journey: foundation.Journey,
        index: int,
        evidence: creation.EvidenceObject | None = None,
    ) -> None:
        """F0 startup evidence for a session another actor started: active, observed, the launch\'s native id."""
        journey.session_id = session
        launch = journey.await_json(self.setups[index].control / foundation.LAUNCH_FILE, LAUNCH_SECONDS)
        if evidence is not None:
            evidence["launch"] = cast(creation.EvidenceValue, dict(launch))
        native = str(launch.get("native_session_id"))
        deadline = time.monotonic() + START_CAP_SECONDS
        record: Json | None = None
        while time.monotonic() < deadline:
            record = journey.record(retain=False)
            if journey.started(record, native):
                if evidence is not None and record is not None:
                    evidence["startup_record"] = cast(creation.EvidenceValue, dict(record))
                return
            recorded = record.get(foundation.FIELD_NATIVE) if record is not None else None
            if isinstance(recorded, str) and recorded and recorded != native:
                raise creation.binding_failure(
                    DETAIL_MAPPING.format(actor=actor, session=session, recorded=recorded, launched=native)
                )
            payload_work.sleep(POLL_SECONDS)
        raise creation.platform_failure(
            DETAIL_NOT_STARTED.format(actor=actor, session=session, seconds=int(START_CAP_SECONDS), record=record)
        )

    def _effect(self, name: str, actor: str | None) -> creation.EvidenceObject | None:
        """Keep the original observations of one B3 effect, without another public call."""
        if self.accounting is None:
            return None
        packet: creation.EvidenceObject = {
            "name": name,
            "actor": actor,
            "person": self.person,
            "wait_key": self.key,
            "started_ns": time.monotonic_ns(),
            "finished_ns": None,
            "frames": [],
            "shown": [],
            "session_reads": [],
        }
        cast(list[creation.EvidenceValue], self.accounting["effects"]).append(packet)
        return packet

    def _shown(self, effect: creation.EvidenceObject | None = None) -> Json:
        shown = driver.shown_with_content(self.observer, ITEM)
        if effect is not None:
            cast(list[creation.EvidenceValue], effect["shown"]).append(cast(creation.EvidenceValue, dict(shown)))
        return shown

    def _log(self, effect: creation.EvidenceObject | None = None) -> str:
        _, log = creation.dig(self._shown(effect), "artifact_content.log")
        return str(log) if isinstance(log, str) else ""

    def _require_unchanged(self, when: str, effect: creation.EvidenceObject | None = None) -> None:
        changed = creation.differences(self.snapshot, self._shown(effect))
        if changed:
            raise creation.platform_failure(DETAIL_CHANGED.format(when=when, paths=changed))

    # -- setup -----------------------------------------------------------------------------------------------------
    def setup_pool(self) -> None:
        dispatch_argv = [
            "telec", SESSIONS, START, "--path", str(self.project), "--agent", "claude", "--mode", "fast",
            "--message", DISPATCH_MESSAGE,
        ]  # fmt: skip
        owner = [
            controls.command("dispatchx", dispatch_argv, GATE_DISPATCH),
            controls.late("decision", ARGV_DECISION, GATE_DECISION),
        ]
        first_driver = [
            controls.command("claim", ["telec", TODO, "prepare", ITEM]),
            controls.command("child", ["telec", TODO, "child", ITEM]),
            controls.command("waiting", ["telec", TODO, "act", ITEM, "waiting", "--person", self.owner_slug, QUESTION], GATE_WAITING),
        ]  # fmt: skip
        dispatched = [
            controls.late("refused", ARGV_REFUSED, GATE_REFUSED),
            controls.command("note", ["telec", TODO, "act", ITEM, "note", NOTE_TEXT], GATE_NOTE),
        ]
        second_driver = [controls.command("claim", ["telec", TODO, "prepare", ITEM])]
        plans = [
            controls.PlanFile(commands=commands)
            for commands in (owner, first_driver, [], dispatched, second_driver, [], [])
        ]
        self.setups = self.controls.pool(plans)

    def verify_owner(self) -> None:
        """The owner terminal reads as the configured administrator: its email by whoami, its standing by the person record."""
        who = self.observer.run((TELEC, "auth", "whoami"))
        emails = [
            line.partition(": ")[2].strip()
            for line in who.output.replace("\r\n", "\n").split("\n")
            if line.startswith("Email: ")
        ]
        outcome = self.observer.run((TELEC, CONFIG, PERSON, GET, self.owner_slug, FORMAT_OPTION, JSON_FORMAT))
        person = foundation.json_object(outcome.output)
        roles = person.get("roles") if person is not None else None
        administrator = isinstance(roles, list) and any(
            isinstance(role, Mapping) and role.get("platform") == "admin" for role in roles
        )
        if emails != [self.owner_email] or outcome.exit_status != 0 or not administrator:
            raise creation.binding_failure(
                DETAIL_PERSON.format(
                    slug=self.owner_slug,
                    email=self.owner_email,
                    output=f"whoami emails {emails!r}; person {outcome.output[-200:]}",
                )
            )
        self.person = self.owner_slug

    # -- steps -----------------------------------------------------------------------------------------------------
    def step1_owner_session(self) -> str:
        journey = self._journey("owner", 0)
        evidence = driver.actor_inputs(self.accounting, "owner", 0)
        if evidence is not None:
            evidence["message"] = journey.message
            evidence["expected_principal"] = f"human:{self.owner_email}"
        attempt = driver.begin_attempt(self.starts, "session-owner")
        try:
            started = journey.start_session()
        finally:
            if evidence is not None and journey.start_evidence is not None:
                evidence["start_command"] = creation.command_evidence(*journey.start_evidence)
        owner = journey.session_id
        if evidence is not None:
            evidence["session_id"] = owner
        driver.release_attempt(self.starts, attempt)  # the public answer named the session; settlement closes it
        journey.positive_start(
            started,
            captured=cast(list[Mapping[str, object]], evidence["positive_start"]) if evidence is not None else None,
        )
        record = self._record(owner)
        if evidence is not None:
            evidence["fact_record"] = cast(creation.EvidenceValue, dict(record))
        facts = {
            FIELD_PRINCIPAL: record.get(FIELD_PRINCIPAL),
            FIELD_INITIATOR: record.get(FIELD_INITIATOR) or None,
            FIELD_ROLE: record.get(FIELD_ROLE) or None,
            FIELD_JOB: record.get(FIELD_JOB) or None,
        }
        expected = {
            FIELD_PRINCIPAL: f"human:{self.owner_email}",
            FIELD_INITIATOR: None,
            FIELD_ROLE: None,
            FIELD_JOB: None,
        }
        if facts != expected:
            raise creation.binding_failure(
                DETAIL_FACTS.format(actor="owner session", session=owner, found=facts, expected=expected)
            )
        created = (
            self.observer.sessions(
                evidence=cast(list[creation.EvidenceValue], evidence["lists"]) if evidence is not None else None
            ).ids
            - self._known()
        )
        if created != frozenset({owner}):
            raise creation.platform_failure(
                DETAIL_SESSIONS.format(when="step 1", found=sorted(created), expected=[owner])
            )
        if evidence is not None:
            evidence["finished_ns"] = time.monotonic_ns()
        return owner

    def step2_first_driver(self, owner: str) -> tuple[driver.DriverCase, str, str]:
        child_attempt = driver.begin_attempt(self.starts, "session-child")  # the driver\'s plan starts it unsupervised
        outcome, starter = driver.start_call(
            self.starts,
            self.observer,
            (TELEC, TODO, "prepare", ITEM),
            "start",
            evidence=cast(list[creation.EvidenceValue], self.accounting["start_calls"])
            if self.accounting is not None
            else None,
        )
        if outcome.exit_status != 0 or starter is None:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        first = self._discover(self._known(owner))
        case = self._driver_case("first", 1)
        case.check_startup(first, frozenset({owner, first}))
        self._require_pool(2)
        instruction = case.claim_call([starter])
        case.check_instruction(first, instruction)
        case.observe_claim(first, holds_nothing=[owner])
        self.starts[starter] = publication.START_CLAIMED
        self.b13_first_claimed = True
        child_evidence = driver.actor_inputs(self.accounting, "child", 2)
        frame = self._frame(self.journeys["first"], FRAME_CHILD)
        if child_evidence is not None:
            child_evidence["start_frame"] = cast(creation.EvidenceValue, dict(frame))
            child_evidence["parent_actor"] = first
        status, text = self._output(frame)
        started = STARTED_CHILD.search(text)
        if status != 0 or started is None or started.group("procedure") != CHILD_PROCEDURE:
            raise creation.platform_failure(DETAIL_CHILD.format(stdout=text[-300:], procedure=CHILD_PROCEDURE))
        child = started.group("session")
        if child_evidence is not None:
            child_evidence["session_id"] = child
        driver.release_attempt(self.starts, child_attempt)
        child_journey = self._journey("child", 2)
        self._startup("child", child, child_journey, 2, child_evidence)
        record = self._record(child)
        if child_evidence is not None:
            child_evidence["fact_record"] = cast(creation.EvidenceValue, dict(record))
        for field, expected in ((FIELD_ROLE, CHILD_ROLE), (FIELD_INITIATOR, first)):
            if record.get(field) != expected:
                raise creation.platform_failure(
                    DETAIL_CHILD_RECORD.format(session=child, field=field, found=record.get(field), expected=expected)
                )
        self._require_pool(3)
        if child_evidence is not None:
            child_evidence["finished_ns"] = time.monotonic_ns()
        return case, first, child

    def _driver_case(self, name: str, index: int) -> driver.DriverCase:
        journey = self._journey(name, index)
        assert self.baseline is not None
        return driver.DriverCase(
            host=self.host,
            observer=self.observer,
            journey=journey,
            item=ITEM,
            launch_setup=self.setups[index],
            clone=self.clone,
            baseline=self.baseline,
            case_evidence=driver.driver_inputs(
                self.accounting, name, index, driver.DRIVER_ID, "prepare", PHASE_PREPARATION
            ),
        )

    def step3_before_waiting(self, first: str, child: str) -> None:
        effect = self._effect("before-waiting", first)
        record = self._record(child, effect)
        if record.get(FIELD_CLOSED_AT) is not None or record.get(foundation.FIELD_LIFECYCLE) != foundation.ACTIVE:
            raise creation.platform_failure(
                DETAIL_LIVE.format(actor="child", session=child, when="before waiting", record=record)
            )
        creation.require_value(ITEM, self._shown(effect), "state.active_runner", first)
        if effect is not None:
            effect["finished_ns"] = time.monotonic_ns()

    def step4_wait(self, first: str, child: str) -> None:
        effect = self._effect("waiting", first)
        self._gate(1, GATE_WAITING)
        frame = self._frame(self.journeys["first"], FRAME_WAITING, effect)
        status, text = self._output(frame)
        performed = PERFORMED.format(act="waiting", item=ITEM)
        completed = WAIT_COMPLETE.search(text.replace("\r\n", "\n"))
        if status != 0 or performed not in text or completed is None:
            raise creation.platform_failure(
                DETAIL_WAIT.format(stdout=text[-300:], needle=performed + " ... , complete")
            )
        key = WAIT_KEY.search(text)
        if key is None:
            raise creation.binding_failure(DETAIL_WAIT.format(stdout=text[-300:], needle="wait key: <key>"))
        self.key = key.group("key")
        if effect is not None:
            effect["wait_key"] = self.key
        shown = self._shown(effect)
        for path, expected in (
            ("state.lifecycle_phase", PHASE_WAITING),
            ("standing.phase", PHASE_WAITING),
            ("standing.waiting_on", self.person),
        ):
            creation.require_value(ITEM, shown, path, expected)
        creation.require_unclaimed(ITEM, shown)
        record = self._record(child, effect)
        if record.get(FIELD_CLOSED_AT) is None or record.get(FIELD_LIFECYCLE) != foundation.CLOSED:
            raise creation.platform_failure(
                DETAIL_CLOSED.format(actor="child", session=child, when="after waiting", record=record)
            )
        if self._record(first, effect).get(FIELD_CLOSED_AT) is not None:
            raise creation.binding_failure(
                DETAIL_LIVE.format(actor="first driver", session=first, when="after waiting", record="closed")
            )
        self.b13_child_closed = True
        self.b13_first_live = True
        entries = [entry for entry in log_entries(self._log(effect)) if f" · waiting ({self.person})" in entry[0]]
        if len(entries) != 1 or first not in entries[0][0] or entries[0][1] != QUESTION:
            raise creation.platform_failure(
                DETAIL_LOG_COUNT.format(
                    when="after waiting",
                    count=len(entries),
                    kind="waiting",
                    expected="exactly one naming the driver with the question",
                    headers=entries,
                )
            )
        self.snapshot = self._shown(effect)
        self.b13_waiting_completed = True
        if effect is not None:
            effect["finished_ns"] = time.monotonic_ns()

    def _b13_paths(self) -> tuple[Path, Path, Path]:
        """Establish the retention guard before refusing any missing, conflicting or unsafe carrier path."""
        marker_root = self.controls.root.parent / B13_DIRECTORY
        marker_path = marker_root / B13_MARKER_FILE
        self.b13_marker = marker_path
        self.retain_key(B13_RETENTION_KEY, B13_RETENTION_REASON)
        report_path = self.report_path
        if report_path is None:
            self.b13_evidence.status = B13_STATUS_UNPROVEN
            self.b13_evidence.primary_failure = B13_ERROR_CARRIER
            raise creation.binding_failure(B13_ERROR_PREFIX + B13_ERROR_CARRIER)
        carrier_path = report_path.with_name(report_path.name + B13_CARRIER_SUFFIX)
        self.b13_carrier = carrier_path
        inside_profile = carrier_path.resolve().is_relative_to(self.publication.temporary_root.resolve())
        if inside_profile or carrier_path.exists():
            failure = B13_ERROR_CARRIER if inside_profile else B13_ERROR_ALREADY_EXISTS
            self.b13_evidence.status = B13_STATUS_UNPROVEN
            self.b13_evidence.primary_failure = failure
            raise creation.binding_failure(B13_ERROR_PREFIX + failure)
        if marker_root.exists():
            self.b13_evidence.status = B13_STATUS_UNPROVEN
            self.b13_evidence.primary_failure = B13_ERROR_ALREADY_EXISTS
            raise creation.binding_failure(B13_ERROR_PREFIX + B13_ERROR_ALREADY_EXISTS)
        return marker_root, marker_path, carrier_path

    def step4b_retired_kickback(
        self,
        owner: str,
        first: str,
        child: str,
        source_revision: str,
        source_tree: str,
    ) -> None:
        """B13: refuse one retired kickback at the naturally reached waiting-on-owner checkpoint."""
        started = time.monotonic()
        deadline = started + B13_SCENARIO_SECONDS
        observer = creation.Observer(
            self.host, deadline=deadline, deadline_detail=B13_ERROR_PREFIX + B13_ERROR_DEADLINE
        )
        evidence = self.b13_evidence
        evidence.status = B13_STATUS_PARTIAL
        evidence.source_revision = source_revision
        evidence.source_tree = source_tree
        marker_root, marker_path, carrier_path = self._b13_paths()
        report_path = self.report_path
        assert report_path is not None
        try:
            marker_root.mkdir(parents=True, exist_ok=False)
            carrier_path.parent.mkdir(parents=True, exist_ok=True)
            _b13_write_exclusive(carrier_path, b"")
            _b13_fsync_directory(marker_root)
            _b13_fsync_directory(marker_root.parent)
            _b13_fsync_directory(carrier_path.parent)
            evidence.carrier.update(
                {
                    "owned": True,
                    B13_CARRIER_PATH_FIELD: self.sanitize(str(carrier_path.resolve())),
                    B13_REPORT_PATH_FIELD: self.sanitize(str(report_path.resolve())),
                    B13_MARKER_PATH_FIELD: self.sanitize(str(marker_path.resolve())),
                    B13_ATTEMPTS_PATH_FIELD: self.sanitize(str((marker_root / B13_ATTEMPTS_FILE).resolve())),
                    "sanitized": True,
                    "carrier_truncated": False,
                }
            )
            _b13_write_exclusive(self.controls.root.parent / B13_DIRECTORY / B13_ATTEMPTS_FILE, b"")
            evidence.prerequisites = {
                B13_ACTORS_FIELD: {"owner": owner, "owner_slug": self.person, "first_driver": first, "child": child},
                B13_CANDIDATE_FIELD: self.publication.candidate,
                B13_CONTROL_PATHS_FIELD: [str(path.resolve()) for path in self.controls.directories],
                "first_claim_positive": self.b13_first_claimed,
                "waiting_act_positive": self.b13_waiting_completed,
                "child_closed": self.b13_child_closed,
                "first_driver_live": self.b13_first_live,
                "unresolved_start_attempts": [],
            }
            evidence.prerequisites = cast(creation.EvidenceObject, _b13_safe(evidence.prerequisites, self.sanitize))
            evidence.before = {"argv": [list(argv) for argv in B13_READ_ARGV]}
            freeze_b13_evidence(evidence, marker_path, carrier_path, self.sanitize, authorized_bootstrap=True)
            before_item = observer.show(ITEM)
            clean_before_item = _b13_safe(dict(before_item), self.sanitize) if before_item is not None else None
            evidence.before["item"] = clean_before_item
            append_b13_attempt(
                evidence,
                marker_path,
                carrier_path,
                {
                    B13_EVENT: B13_PUBLIC_READ,
                    "when": B13_OBSERVATION_BEFORE,
                    B13_ARGV_FIELD: list(B13_READ_ARGV[0]),
                    "item": clean_before_item,
                },
                self.sanitize,
            )
            before_sessions = observer.sessions()
            evidence.before["session_ids"] = cast(list[creation.EvidenceValue], sorted(before_sessions.ids))
            append_b13_attempt(
                evidence,
                marker_path,
                carrier_path,
                {
                    B13_EVENT: B13_PUBLIC_READ,
                    "when": B13_OBSERVATION_BEFORE,
                    B13_ARGV_FIELD: list(B13_READ_ARGV[1]),
                    "session_ids": sorted(before_sessions.ids),
                },
                self.sanitize,
            )
            before_slugs = observer.slugs()
            evidence.before["slugs"] = cast(list[creation.EvidenceValue], sorted(before_slugs))
            append_b13_attempt(
                evidence,
                marker_path,
                carrier_path,
                {
                    B13_EVENT: B13_PUBLIC_READ,
                    "when": B13_OBSERVATION_BEFORE,
                    B13_ARGV_FIELD: list(B13_READ_ARGV[2]),
                    "slugs": sorted(before_slugs),
                },
                self.sanitize,
            )
            if before_item is None or creation.differences(self.snapshot, before_item):
                raise ValueError(B13_ERROR_WAITING)
            creation.require_value(ITEM, before_item, "state.lifecycle_phase", PHASE_WAITING)
            creation.require_value(ITEM, before_item, "standing.phase", PHASE_WAITING)
            creation.require_value(ITEM, before_item, "standing.waiting_on", self.person)
            creation.require_unclaimed(ITEM, before_item)
            has_admitted, _ = creation.dig(before_item, "standing.admitted")
            if has_admitted:
                raise ValueError(B13_ERROR_WAITING)
            if not (
                self.b13_first_claimed and self.b13_waiting_completed and self.b13_child_closed and self.b13_first_live
            ):
                raise ValueError(B13_ERROR_WAITING)
            if any(value == publication.START_OPEN for value in self.starts.values()):
                raise ValueError(B13_ERROR_START_OPEN)
            append_b13_attempt(
                evidence,
                marker_path,
                carrier_path,
                {B13_EVENT: B13_ATTEMPT_OPEN, B13_ARGV_FIELD: list(B13_CALL_ARGV), B13_PRECALL: evidence.before},
                self.sanitize,
            )
            outcome = observer.run(B13_CALL_ARGV)
            receipt = creation.decode_object(outcome.output)
            operation_value = receipt.get(publication.FIELD_OPERATION) if receipt is not None else None
            operation = operation_value if isinstance(operation_value, str) and operation_value else None
            receipt_state = receipt.get(FIELD_STATE) if receipt is not None else None
            evidence.response = {
                B13_ARGV_FIELD: list(B13_CALL_ARGV),
                B13_EXIT_FIELD: outcome.exit_status,
                B13_OUTPUT_FIELD: self.sanitize(outcome.output),
                B13_STDERR_FIELD: self.sanitize(outcome.stderr),
                B13_DIAGNOSTICS_FIELD: self.sanitize(outcome.diagnostics),
                B13_DURATION_FIELD: outcome.duration_seconds,
                B13_OPERATION_FIELD: operation,
                B13_OPERATION_STATUS_FIELD: (
                    receipt_state
                    if operation is not None and isinstance(receipt_state, str) and receipt_state
                    else B13_OPERATION_UNKNOWN
                    if operation is not None
                    else B13_OPERATION_NOT_APPLICABLE
                ),
                "stdout_sanitized": True,
                "stderr_sanitized": True,
                "diagnostics_sanitized": True,
                "output_truncated": outcome.diagnostics == creation.B12_OUTPUT_LIMIT_DIAGNOSTIC,
                "stderr_truncated": False,
            }
            append_b13_attempt(
                evidence, marker_path, carrier_path, {B13_EVENT: B13_ATTEMPT_RESULT, **evidence.response}, self.sanitize
            )
            _require_b13_completed_result(outcome, operation)
            for label, pause in ((B13_OBSERVATION_IMMEDIATE, 0.0), (B13_OBSERVATION_SETTLED, B13_SETTLE_SECONDS)):
                if pause:
                    observer.wait(pause)
                observation: creation.EvidenceObject = {
                    "argv": [list(argv) for argv in B13_READ_ARGV],
                    "when": label,
                }
                evidence.readbacks.append(observation)
                item = observer.show(ITEM)
                clean_item = _b13_safe(dict(item), self.sanitize) if item is not None else None
                observation["item"] = clean_item
                append_b13_attempt(
                    evidence,
                    marker_path,
                    carrier_path,
                    {
                        B13_EVENT: B13_PUBLIC_READ,
                        "when": label,
                        B13_ARGV_FIELD: list(B13_READ_ARGV[0]),
                        "item": clean_item,
                    },
                    self.sanitize,
                )
                sessions = observer.sessions()
                observation["session_ids"] = cast(list[creation.EvidenceValue], sorted(sessions.ids))
                append_b13_attempt(
                    evidence,
                    marker_path,
                    carrier_path,
                    {
                        B13_EVENT: B13_PUBLIC_READ,
                        "when": label,
                        B13_ARGV_FIELD: list(B13_READ_ARGV[1]),
                        "session_ids": sorted(sessions.ids),
                    },
                    self.sanitize,
                )
                slugs = observer.slugs()
                observation["slugs"] = cast(list[creation.EvidenceValue], sorted(slugs))
                changed = creation.differences(evidence.before["item"], clean_item) if item is not None else ["absent"]
                readback_matches = (
                    item is not None and not changed and sessions.ids == before_sessions.ids and slugs == before_slugs
                )
                final_readback = label == B13_OBSERVATION_SETTLED and len(evidence.readbacks) == 2
                if final_readback:
                    evidence.duration_seconds = time.monotonic() - started
                    evidence.status = (
                        B13_STATUS_PARTIAL
                        if readback_matches and evidence.duration_seconds <= B13_SCENARIO_SECONDS
                        else B13_STATUS_UNPROVEN
                    )
                    if not readback_matches:
                        evidence.primary_failure = B13_ERROR_CHANGED.format(differences=changed)
                    elif evidence.duration_seconds > B13_SCENARIO_SECONDS:
                        evidence.primary_failure = B13_ERROR_DEADLINE
                append_b13_attempt(
                    evidence,
                    marker_path,
                    carrier_path,
                    {
                        B13_EVENT: B13_PUBLIC_READ,
                        "when": label,
                        B13_ARGV_FIELD: list(B13_READ_ARGV[2]),
                        "slugs": sorted(slugs),
                    },
                    self.sanitize,
                    final_elapsed_start=started if final_readback else None,
                )
                if not readback_matches:
                    raise ValueError(B13_ERROR_CHANGED.format(differences=changed))
            if len(evidence.readbacks) != 2:
                raise ValueError(B13_ERROR_READBACK_COUNT)
            if evidence.status != B13_STATUS_PARTIAL:
                raise ValueError(evidence.primary_failure or B13_ERROR_DEADLINE)
            _require_b13_snapshot(outcome.output)
            complete_b13_evidence(evidence, marker_path, carrier_path, self.sanitize)
            if not verify_b13_delivery(evidence, marker_path, carrier_path, self.sanitize):
                raise ValueError(B13_ERROR_SEAL)
            if time.monotonic() - started > B13_SCENARIO_SECONDS:
                evidence.status = B13_STATUS_UNPROVEN
                evidence.primary_failure = B13_ERROR_DEADLINE
                raise ValueError(B13_ERROR_DEADLINE)
            self.release_key(B13_RETENTION_KEY)
        except BaseException as error:
            evidence.status = B13_STATUS_UNPROVEN
            evidence.primary_failure = self.sanitize(f"{type(error).__name__}: {error}")
            evidence.duration_seconds = time.monotonic() - started
            if evidence.carrier.get("owned") is True and marker_path.exists() and carrier_path.exists():
                try:
                    if verify_b13_seal(evidence, marker_path, carrier_path):
                        freeze_b13_evidence(evidence, marker_path, carrier_path, self.sanitize, authorized_failure=True)
                    else:
                        evidence.evidence_failure = B13_ERROR_SEAL
                        capture_b13_attempt_ledger(evidence, marker_path, self.sanitize)
                except Exception as seal_error:
                    evidence.evidence_failure = self.sanitize(
                        B13_ERROR_DETAIL_FORMAT.format(error_class=type(seal_error).__name__, detail=seal_error)
                    )
                    evidence.export_failure = B13_ERROR_SEAL
                    capture_b13_attempt_ledger(evidence, marker_path, self.sanitize)
            raise creation.binding_failure(B13_ERROR_PREFIX + evidence.primary_failure) from error

    def step5_entry_refused(self, owner: str, first: str, child: str) -> None:
        effect = self._effect("entry-refused", None)
        if effect is not None:
            effect["baseline"] = cast(creation.EvidenceValue, dict(self.snapshot))
            effect["start_calls"] = []
            effect["operation_reads"] = []
            effect["lists"] = []
        outcome, operation = driver.start_call(
            self.starts,
            self.observer,
            (TELEC, TODO, "prepare", ITEM),
            "refused-start",
            evidence=cast(list[creation.EvidenceValue], effect["start_calls"]) if effect else None,
        )
        if outcome.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        state = publication.await_terminal(
            self.observer,
            operation,
            OPERATION_SECONDS,
            evidence=cast(list[creation.EvidenceValue], effect["operation_reads"]) if effect else None,
        )
        error = state.get(FIELD_ERROR)
        needles = (ITEM, PHASE_WAITING, self.person)
        if (
            state.get(FIELD_STATE) != STATE_FAILED
            or not isinstance(error, str)
            or any(needle.lower() not in error.lower() for needle in needles)
        ):
            raise creation.platform_failure(
                DETAIL_ENTRY_REFUSED.format(state=state.get(FIELD_STATE), error=error, needles=list(needles))
            )
        self.starts[operation] = publication.START_REFUSED
        created = (
            self.observer.sessions(evidence=cast(list[creation.EvidenceValue], effect["lists"]) if effect else None).ids
            - self._known()
        )
        if created != frozenset({owner, first, child}):
            raise creation.platform_failure(
                DETAIL_SESSIONS.format(when="step 5", found=sorted(created), expected=[owner, first, child])
            )
        self._require_unchanged("after the refused entry", effect)
        if effect is not None:
            effect["finished_ns"] = time.monotonic_ns()

    def step6_dispatched(self, owner: str, first: str, child: str) -> str:
        dispatch_attempt = driver.begin_attempt(self.starts, "session-dispatched")
        evidence = driver.actor_inputs(self.accounting, "dispatched", 3)
        if evidence is not None:
            evidence["message"] = DISPATCH_MESSAGE
        self._gate(0, GATE_DISPATCH)
        frame = self._frame(self.journeys["owner"], FRAME_DISPATCH)
        if evidence is not None:
            evidence["start_frame"] = cast(creation.EvidenceValue, dict(frame))
            evidence["parent_actor"] = owner
        status, text = self._output(frame)
        result = foundation.json_object(text)
        dispatched = result.get(foundation.FIELD_SESSION_ID) if result is not None else None
        if (
            status != 0
            or result is None
            or result.get(foundation.FIELD_STATUS) != foundation.STATUS_SUCCESS
            or not isinstance(dispatched, str)
            or not dispatched
        ):
            raise creation.platform_failure(DETAIL_FRAME.format(name=FRAME_DISPATCH, frame=frame))
        driver.release_attempt(self.starts, dispatch_attempt)
        if evidence is not None:
            evidence["session_id"] = dispatched
        journey = self._journey("dispatched", 3)
        self._startup("dispatched", dispatched, journey, 3, evidence)
        self._require_pool(4)
        record = self._record(dispatched)
        owner_record = self._record(owner)
        if evidence is not None:
            evidence["fact_record"] = cast(creation.EvidenceValue, dict(record))
            evidence["parent_record"] = cast(creation.EvidenceValue, dict(owner_record))
            evidence["finished_ns"] = time.monotonic_ns()
        facts = {FIELD_INITIATOR: record.get(FIELD_INITIATOR), FIELD_PRINCIPAL: record.get(FIELD_PRINCIPAL)}
        expected = {FIELD_INITIATOR: owner, FIELD_PRINCIPAL: owner_record.get(FIELD_PRINCIPAL)}
        if facts != expected:
            raise creation.binding_failure(
                DETAIL_FACTS.format(actor="dispatched session", session=dispatched, found=facts, expected=expected)
            )
        effect = self._effect("dispatched-decision-and-note", dispatched)
        if effect is not None:
            effect["baseline"] = cast(creation.EvidenceValue, dict(self.snapshot))
        self._late_argv(
            3, ARGV_REFUSED, ["telec", TODO, "act", ITEM, "decision", "--wait", self.key, ANSWER_DISPATCHED]
        )
        refused_attempt = driver.begin_attempt(self.starts, "decision-dispatched")
        self._gate(3, GATE_REFUSED)
        refusal = self._frame(journey, FRAME_REFUSED, effect)
        status, text = self._output(refusal)
        problems = []
        if status in (0, None):
            problems.append("was not refused with a non-zero exit")
        if PERFORMED.format(act="decision", item=ITEM) in text:
            problems.append("printed a performed decision")
        if "decision" not in text.lower() or self.person.lower() not in text.lower():
            problems.append(f"does not name decision and {self.person}")
        if problems:
            raise creation.platform_failure(
                DETAIL_REFUSAL.format(problem="; ".join(problems), status=status, output=text[-300:])
            )
        self._require_unchanged("after the refused decision", effect)
        if any(" · decision (" in header for header, _ in log_entries(self._log(effect))):
            raise creation.platform_failure(
                DETAIL_LOG.format(
                    when="after the refused decision", needle="no decision header", log=self._log(effect)[-600:]
                )
            )
        driver.release_attempt(self.starts, refused_attempt)  # refused, nothing cleared, no driver reserved
        self._gate(3, GATE_NOTE)
        noted = self._frame(journey, FRAME_NOTE, effect)
        status, text = self._output(noted)
        if status != 0 or PERFORMED.format(act="note", item=ITEM) not in text:
            raise creation.platform_failure(DETAIL_FRAME.format(name=FRAME_NOTE, frame=noted))
        entries = log_entries(self._log(effect))
        notes = [entry for entry in entries if NOTE_HEADER.search(entry[0].rstrip())]
        if len(notes) != 1 or dispatched not in notes[0][0] or notes[0][1] != NOTE_TEXT:
            raise creation.platform_failure(
                DETAIL_LOG_COUNT.format(
                    when="after the note",
                    count=len(notes),
                    kind="note",
                    expected="exactly one naming the dispatched session",
                    headers=notes or entries[-6:],
                )
            )
        creation.require_value(ITEM, self._shown(effect), "state.lifecycle_phase", PHASE_WAITING)
        if effect is not None:
            effect["finished_ns"] = time.monotonic_ns()
        return dispatched

    def step7_end_first(self, case: driver.DriverCase, first: str) -> None:
        case.require_title_stable(first)
        journey = self.journeys["first"]
        journey.session_id = first
        journey.end_session()

    def step8_decide(self, owner: str) -> None:
        effect = self._effect("owner-decision", owner)
        self._late_argv(0, ARGV_DECISION, ["telec", TODO, "act", ITEM, "decision", "--wait", self.key, ANSWER])
        self.decision_attempt = driver.begin_attempt(self.starts, "decision-owner")
        self._gate(0, GATE_DECISION)
        frame = self._frame(self.journeys["owner"], FRAME_DECISION, effect)
        status, text = self._output(frame)
        if status != 0 or PERFORMED.format(act="decision", item=ITEM) not in text:
            raise creation.platform_failure(DETAIL_FRAME.format(name=FRAME_DECISION, frame=frame))
        decisions = [entry for entry in log_entries(self._log(effect)) if f" · decision ({self.person})" in entry[0]]
        if len(decisions) != 1 or owner not in decisions[0][0] or decisions[0][1] != ANSWER:
            raise creation.platform_failure(
                DETAIL_LOG_COUNT.format(
                    when="after the decision",
                    count=len(decisions),
                    kind="decision",
                    expected="exactly one naming the owner session with the answer",
                    headers=decisions,
                )
            )
        shown = self._shown(effect)
        creation.require_value(ITEM, shown, "state.lifecycle_phase", PHASE_PREPARATION)
        found, standing = creation.dig(shown, "standing")
        if found and isinstance(standing, Mapping) and "waiting_on" in standing:
            raise creation.platform_failure(
                DETAIL_SHOWN.format(
                    when="after the decision", path="standing.waiting_on", found="present", expected="absent"
                )
            )
        if effect is not None:
            effect["finished_ns"] = time.monotonic_ns()

    def step9_second_driver(self, owner: str, first: str, child: str, dispatched: str) -> tuple[driver.DriverCase, str]:
        second = self._discover(self._known(owner, first, child, dispatched))
        case = self._driver_case("second", 4)
        case.check_startup(second, frozenset({owner, first, child, dispatched, second}))
        self._require_pool(5)
        instruction = case.claim_call([])
        case.check_instruction(second, instruction)
        case.observe_claim(second, holds_nothing=[owner, dispatched], earlier=[first])
        driver.release_attempt(self.starts, self.decision_attempt)  # consumed by the second driver\'s claim
        effect = self._effect("second-claim-context", second)
        for session in (owner, child, dispatched):
            role = self._record(session, effect).get(FIELD_ROLE)
            if role == DRIVER_ROLE:
                raise creation.platform_failure(DETAIL_NOT_DRIVER.format(session=session, role=role))
        if effect is not None:
            effect["finished_ns"] = time.monotonic_ns()
        return case, second

    def step10_close(self, case: driver.DriverCase, second: str, owner: str, dispatched: str) -> None:
        self.handover.before(ITEM, second, PHASE_PREPARATION)
        case.close(second)
        for name, session in (("dispatched", dispatched), ("owner", owner)):
            journey = self.journeys[name]
            journey.session_id = session
            journey.end_session()
        self.handover.after([ITEM])


def run_waiting(
    host: FoundationHost,
    setup: foundation.FixtureSetup,
    project: Path,
    source_root: Path,
    owner_email: str,
    owner_slug: str,
    project_slug: str,
    project_name: str,
    register_company: Callable[[], None],
    retain: Callable[[str], None],
    retain_key: Callable[[str, str], None],
    release_key: Callable[[str], None],
    report_path: Path | None,
    source_revision: str,
    source_tree: str,
    b13_evidence: WaitingKickbackEvidence,
    sanitize: Callable[[str], str],
    accounting: creation.EvidenceObject | None = None,
) -> None:
    """Journey B3; raises JourneyFailure leading with its class."""
    waiting = _Waiting(
        host,
        setup,
        project,
        source_root,
        owner_email,
        owner_slug,
        register_company,
        retain,
        retain_key,
        release_key,
        report_path,
        b13_evidence,
        sanitize,
    )
    observer = waiting.observer
    waiting.accounting = accounting
    failure: BaseException | None = None
    event_binding: events.EventWindowBinding | None = None
    try:
        creation.require_manual_runner(observer)
        waiting.publication.begin(own_generation=True)
        creation.enter_project(observer, project)
        waiting.baseline = observer.sessions(
            evidence=cast(list[creation.EvidenceValue], accounting["baseline"]) if accounting is not None else None
        )
        waiting.verify_owner()
        waiting.setup_pool()
        creation.require_created(creation.create_item(observer, ITEM, CONTENT, "feature", approved=True), ITEM)
        before = driver.shown_with_content(observer, ITEM)
        creation.require_value(ITEM, before, "state.lifecycle_phase", PHASE_PREPARATION)
        creation.require_unclaimed(ITEM, before)
        creation.require_standing_clear(ITEM, before)
        event_binding = events.begin_b3_window(
            observer, setup.control.parent, project, project_slug, project_name, before
        )
        retain(f"B10 event evidence retained at {event_binding.carrier_root}")
        waiting.clone = waiting.publication.prepare()
        creation.enter_project(observer, project)
        publication.negative_control(observer, ITEM, waiting.baseline, before, waiting.starts)
        waiting.publication.publish()
        waiting.publication.verify_parity()
        creation.enter_project(observer, project)
        owner = waiting.step1_owner_session()
        first_case, first, child = waiting.step2_first_driver(owner)
        waiting.step3_before_waiting(first, child)
        waiting.step4_wait(first, child)
        waiting.step4b_retired_kickback(owner, first, child, source_revision, source_tree)
        waiting.step5_entry_refused(owner, first, child)
        dispatched = waiting.step6_dispatched(owner, first, child)
        waiting.step7_end_first(first_case, first)
        waiting.step8_decide(owner)
        second_case, second = waiting.step9_second_driver(owner, first, child, dispatched)
        waiting.step10_close(second_case, second, owner, dispatched)
        events.append_case(
            event_binding,
            events.FIRST_CASE,
            {
                "person": waiting.person,
                "owner": owner,
                "first_driver": first,
                "child": child,
                "dispatched": dispatched,
                "second_driver": second,
                "wait_key": waiting.key,
                "question": QUESTION,
                "answer": ANSWER,
                "waited_phase": PHASE_PREPARATION,
            },
            previous_case=None,
        )
    except BaseException as error:
        failure = error
        if accounting is not None:
            accounting["journey_error"] = f"{type(error).__name__}: {error}"
        retain(
            f"B10 event interval remains unproven at "
            f"{event_binding.carrier_root if event_binding else setup.control.parent}"
        )
        raise
    finally:
        try:
            _cleanup(waiting, failure)
        except BaseException as error:
            if accounting is not None:
                accounting["cleanup_error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            if accounting is not None:
                accounting["finished_ns"] = time.monotonic_ns()


def _cleanup(waiting: _Waiting, failure: BaseException | None) -> None:
    """Settle the sessions the journey owns, restore the candidate publication and the sidecar, report every failure."""
    b13_safe = waiting.b13_marker is None
    if waiting.b13_marker is not None and waiting.b13_carrier is not None:
        b13_seal_valid = False
        try:
            if waiting.b13_evidence.carrier.get("owned") is True:
                b13_seal_valid = verify_b13_seal(waiting.b13_evidence, waiting.b13_marker, waiting.b13_carrier)
                if waiting.b13_evidence.status == B13_STATUS_COMPLETE:
                    b13_safe = b13_seal_valid and verify_b13_delivery(
                        waiting.b13_evidence, waiting.b13_marker, waiting.b13_carrier, waiting.sanitize
                    )
                    if not b13_safe and not waiting.b13_evidence.evidence_failure:
                        waiting.b13_evidence.evidence_failure = B13_ERROR_SEAL
        except BaseException as error:
            waiting.b13_evidence.status = B13_STATUS_UNPROVEN
            waiting.b13_evidence.evidence_failure = waiting.sanitize(f"{type(error).__name__}: {error}")
            b13_safe = False
        if waiting.b13_evidence.carrier.get("owned") is True and not b13_seal_valid:
            if not waiting.b13_evidence.evidence_failure:
                waiting.b13_evidence.evidence_failure = B13_ERROR_SEAL
            capture_b13_attempt_ledger(waiting.b13_evidence, waiting.b13_marker, waiting.sanitize)
        if not b13_safe:
            waiting.retain_key(B13_RETENTION_KEY, B13_RETENTION_REASON)
    settlement = publication.settle_sessions(
        waiting.observer,
        waiting.baseline,
        waiting.starts,
        waiting.controls.directories,
        evidence=cast(creation.EvidenceObject, waiting.accounting["settlement"])
        if waiting.accounting is not None
        else None,
    )
    problems = list(settlement.problems)
    if b13_safe:
        problems.extend(waiting.publication.restore())
    else:
        problems.append(B13_RETENTION_REASON)
    if b13_safe and settlement.proven and not waiting.handover.unrelated:
        problems.extend(waiting.controls.restore())
    else:
        kept = DETAIL_CONTROLS_KEPT.format(control=waiting.controls.root)
        if not b13_safe:
            kept = f"{kept}; {B13_RETENTION_REASON}"
        if waiting.handover.unrelated:
            kept = f"{kept}; {waiting.handover.unrelated}"
        problems.append(kept)
        waiting.retain(kept)
    try:
        creation.leave_project(waiting.observer, waiting.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    problems.extend(waiting.publication.candidate_unchanged())
    if waiting.accounting is not None:
        waiting.accounting["cleanup_problems"] = list(problems)
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        waiting.publication.note("cleanup-problems", "; ".join(problems))
