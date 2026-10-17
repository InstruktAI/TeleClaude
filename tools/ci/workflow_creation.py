"""Journeys R1 and R4 of the workflow acceptance: plain creation, the acknowledgement gate and a retired act's refusal.

The journeys' assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/r1-r4-assertion-draft.md`, approved at exact SHA-256 (amended once, for the configuration readback path computer.workflow.runner)
8134aaaa2575f55c18e5fb41c58b885c517e1a1d56e9aad3cd88072fd69074f3; authority
`local/projects/teleclaude/spec/feature/workflow/todo-creation` and `.../item-lifecycle`, both in the pending view of
issue 128). R1 proves that a plain creation of a feature, change and bug item reads `preparation`, unclaimed and unheld
with its input artifact, that the creation line without the acknowledgement flag creates nothing while the identical
line with it does, and that no session appears while the manual runner is configured. R4 proves that a retired
previous-machine act is refused naming the door (and the replacing performer where the contract gives one), and that
the refusal writes nothing. They prove no claim, hold, removal, activation or dispatch behaviour.

Every observation is a public CLI read through a fresh process on the authenticated owner terminal. The controller
imports no application module and creates no record, identity or authentication state. Expected values come from the
approved draft; a captured output is never an oracle. Failures are reported in four distinct classes: binding, trace,
gate not reached and platform assertion.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from tools.ci import acceptance_work as payload_work
from tools.ci.terminal import TerminalFailureCause
from tools.ci.workflow_foundation import EvidenceObject as EvidenceObject
from tools.ci.workflow_foundation import EvidenceValue as EvidenceValue
from tools.ci.workflow_foundation import FoundationHost, Outcome

TELEC: Final = "bin/telec"
CHANGE_DIRECTORY: Final = "cd"
PRINT_DIRECTORY: Final = "pwd"
CLI_TIMEOUT_SECONDS: Final = 60
JSON_OBJECT_START: Final = "{"
EMPTY: Final = ""
SPACE: Final = " "
LINE_BREAK: Final = "\n"
DOT: Final = "."
MARK_FAILURE: Final = "{kind}: {detail}"

CLASS_BINDING: Final = "binding failure"
CLASS_TRACE: Final = "trace failure"
CLASS_GATE: Final = "gate not reached"
CLASS_PLATFORM: Final = "platform assertion failure"

TODO: Final = "todo"
SHOW: Final = "show"
LIST: Final = "list"
CREATE: Final = "create"
STAMP: Final = "stamp"
SESSIONS: Final = "sessions"
CONFIG: Final = "config"
COMPUTER: Final = "computer"
GET: Final = "get"
FORMAT_OPTION: Final = "--format"
JSON_FORMAT: Final = "json"
JSON_FLAG: Final = "--json"
INCLUDE_ARTIFACT_CONTENT: Final = "--include-artifact-content"
INCLUDE_ICEBOX: Final = "--include-icebox"
INCLUDE_DELIVERED: Final = "--include-delivered"
INCLUDE_REMOVED: Final = "--include-removed"
ALL_FLAG: Final = "--all"
CLOSED_FLAG: Final = "--closed"
KIND_OPTION: Final = "--kind"
APPROVED_FLAG: Final = "--approved"
PRD_APPROVED_FLAG: Final = "--prd-approved"
BUILD_STARTED_FLAG: Final = "--build-started"
KICKBACK_FLAG: Final = "--kickback"
REASON_OPTION: Final = "--reason"

SLUG_FEATURE: Final = "ra-feature"
SLUG_CHANGE: Final = "ra-change"
SLUG_BUG: Final = "ra-bug"
SLUG_GATE: Final = "ra-noack"
KIND_FEATURE: Final = "feature"
KIND_CHANGE: Final = "change"
KIND_BUG: Final = "bug"
CONTENT_FEATURE: Final = "r1 feature content one"
CONTENT_CHANGE: Final = "r1 change content two"
CONTENT_BUG: Final = "r1 bug content three"
CONTENT_GATE: Final = "r1 gate control four"
KICKBACK_REASON: Final = "r4 retired kickback"
B12_MATRIX_DIRECTORY: Final = "b12-retired-act-preparation"
B12_MARKER_FILE: Final = "RETAINED.json"
B12_ATTEMPTS_FILE: Final = "attempts.jsonl"
B12_COMPLETED_FILE: Final = "completed.json"
B12_ARTIFACT_PATH: Final = "journeys/b12-retired-act-report-evidence-budget.md"
B12_ARTIFACT_SHA: Final = "e229801eacff1f674b0a7156c2a47d0682386be827451a9dc63ca98377d9357e"
B12_ISSUE_REVISION: Final = "UCE_lAHOQMTdPc8AAAABXPR6wc8AAAABB_Nr9Q"
B12_SCENARIO_SECONDS: Final = 600.0
B12_CASE_TIMEOUT_SECONDS: Final = 60.0
B12_INITIAL_STABILITY_SECONDS: Final = 2.0
B12_SETTLE_SECONDS: Final = 5.0


class B12Status(StrEnum):
    """Closed durable/report status vocabulary for the B12 amendment."""

    NOT_SELECTED = "not_selected"
    NOT_RUN = "not_run"
    PARTIAL = "partial"
    COMPLETE = "complete"
    UNPROVEN = "unproven"


class B12Classification(StrEnum):
    """Closed per-case classification vocabulary for B12."""

    OPEN = "open"
    VERIFIED = "verified_refusal"
    UNPROVEN = "unproven"
    NOT_RUN = "not_run"


class RetiredSnapshotState(StrEnum):
    """Exact comparison result for one approved emitted-string snapshot."""

    MATCH = "match"
    MISSING = "missing"
    MISMATCH = "mismatch"


class B12AttemptEvent(StrEnum):
    """Closed append-only attempt-ledger event vocabulary for B12."""

    OPEN = "open"
    RESULT = "result"
    VERIFIED = "verified_refusal"


class B12Outcome(StrEnum):
    """Closed terminal outcome vocabulary for an individual B12 public call."""

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"


class B12Framing(StrEnum):
    """Closed byte-framing vocabulary for B12's durable attempts carrier."""

    COMPLETE = "complete newline-terminated JSONL"
    PARTIAL = "partial trailing record"
    MISSING = "missing_attempt_file"
    NOT_CREATED = "not_created"


class B12OperationReceiptState(StrEnum):
    """Closed B12 receipt status values used when a refusal unexpectedly returns an operation."""

    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


B12_STATUS_NOT_SELECTED: Final = B12Status.NOT_SELECTED
B12_STATUS_NOT_RUN: Final = B12Status.NOT_RUN
B12_STATUS_PARTIAL: Final = B12Status.PARTIAL
B12_STATUS_COMPLETE: Final = B12Status.COMPLETE
B12_STATUS_UNPROVEN: Final = B12Status.UNPROVEN
B12_CLASS_OPEN: Final = B12Classification.OPEN
B12_CLASS_VERIFIED: Final = B12Classification.VERIFIED
B12_CLASS_UNPROVEN: Final = B12Classification.UNPROVEN
B12_CLASS_NOT_RUN: Final = B12Classification.NOT_RUN
B12_EVENT_OPEN: Final = B12AttemptEvent.OPEN
B12_EVENT_RESULT: Final = B12AttemptEvent.RESULT
B12_EVENT_VERIFIED: Final = B12AttemptEvent.VERIFIED
B12_REASON: Final = "B12 retired-act matrix evidence is incomplete; retain the full profile resources"
B12_ERROR_PREFIX: Final = "B12 matrix evidence is unproven: "
B12_JSON_SCHEMA: Final = 1
B12_LINE_ENDING: Final = "\n"
B12_CARRIAGE_RETURN_LINE_ENDING: Final = "\r\n"
B12_OUTCOME_COMPLETED: Final = B12Outcome.COMPLETED
B12_OUTCOME_TIMEOUT: Final = B12Outcome.TIMEOUT
B12_OUTCOME_TRANSPORT: Final = B12Outcome.TRANSPORT
B12_TIMEOUT_DIAGNOSTIC: Final = TerminalFailureCause.TIMEOUT.value
B12_TERMINAL_EXIT_DIAGNOSTIC: Final = TerminalFailureCause.EXITED.value
B12_TERMINAL_NOT_STARTED_DIAGNOSTIC: Final = TerminalFailureCause.NOT_STARTED.value
B12_OUTPUT_LIMIT_DIAGNOSTIC: Final = TerminalFailureCause.OUTPUT_LIMIT.value
B12_PTY_CAPTURE: Final = "stdout/stderr are merged by the authenticated PTY"
B12_UTF8: Final = "utf-8"
B12_JSON_SEPARATORS: Final = (",", ":")
B12_MODE_WRITE: Final = "w"
B12_MODE_EXCLUSIVE: Final = "x"
B12_MODE_APPEND: Final = "a"
B12_JSON_SUFFIX: Final = ".json.tmp"
B12_STANDARD_ERROR: Final = "stderr"
B12_DETAIL_NOT_OBJECT: Final = "a public observation was not a JSON object"
B12_DETAIL_UNSUPPORTED: Final = "the upload snapshot contains an unsupported value"
B12_DETAIL_TRAILING_LINE: Final = "the attempt ledger has an incomplete trailing line"
B12_DETAIL_EMPTY_COMPLETE: Final = "the complete attempt ledger is empty"
B12_DETAIL_NOT_OBJECT_LINE: Final = "an attempt ledger line is not an object"
B12_DETAIL_EXTRA_RECORDS: Final = "the attempt ledger has extra or missing records"
B12_DETAIL_UNORDERED_OPEN: Final = "case {case_id} has no exact ordered open attempt"
B12_DETAIL_UNORDERED_RESULT: Final = "case {case_id} has no ordered result record"
B12_DETAIL_INVALID_RESULT: Final = "case {case_id} result is not a verified refusal"
B12_DETAIL_UNORDERED_CLASSIFICATION: Final = "case {case_id} has no final classification record"
B12_DETAIL_NOT_VERIFIED: Final = "case {case_id} is not verified"
B12_REFUSAL_RECEIPT: Final = "the synchronous refusal unexpectedly returned an operation receipt"
B12_REFUSAL_NO_TERMINAL: Final = "the public request timed out or did not return a terminal outcome"
B12_REFUSAL_ZERO_EXIT: Final = "the public refusal command returned success"
B12_REFUSAL_DIAGNOSTIC: Final = "the public request carried an unresolved command diagnostic: {detail}"
B12_SNAPSHOT_ID_PREFIX: Final = "b12-"
B12_MARKER_MISSING_ATTEMPT: Final = "the attempt file is missing while its retention marker exists"
B12_FRAMING_COMPLETE: Final = B12Framing.COMPLETE
B12_FRAMING_PARTIAL: Final = B12Framing.PARTIAL
B12_FRAMING_MISSING: Final = B12Framing.MISSING
B12_FRAMING_NOT_CREATED: Final = B12Framing.NOT_CREATED
B12_CAPTURE_IMMEDIATE: Final = "immediate"
B12_CAPTURE_SETTLED: Final = "settled"
B12_OUTCOME_UNKNOWN: Final = B12OperationReceiptState.NOT_APPLICABLE
B12_OPERATION_UNKNOWN: Final = B12OperationReceiptState.UNKNOWN
B12_STATUS_JSON: Final = "status"
B12_COMPLETED_VALIDATION_FAILED: Final = "the completed report failed read-back validation"
B12_SNAPSHOT_INCOMPLETE: Final = "the in-memory upload snapshot is incomplete"
B12_UPLOAD_VALIDATION_FAILED: Final = "the upload-carried evidence snapshot failed validation"
B12_DETAIL_PRECALL_STATE_CHANGED: Final = "public state changed before case {case_id}: {differences!r}"
B12_DETAIL_MODE: Final = "B12 matrix was selected without complete evidence"
B12_DETAIL_SIXTEEN: Final = "B12 matrix snapshot does not contain sixteen verified refusals"
B12_AMENDMENT: Final = "B12"
B12_OPERATION_NOT_APPLICABLE: Final = B12OperationReceiptState.NOT_APPLICABLE
B12_CASE_IMMEDIATE: Final = "immediate"
B12_CASE_SETTLED: Final = "settled"
B12_CARRIER_ERROR_MARKER: Final = "the attempt file is missing while its retention marker exists"
B12_EXCEPTION_DETAIL: Final = "{error_class}: {detail}"
B12_INTERRUPT_DETAIL: Final = "KeyboardInterrupt: {detail}"
B12_RETAIN_REASON: Final = "B12 retained evidence at {path}"
B12_DETAIL_DEADLINE: Final = "the 600-second scenario deadline expired"
B12_DETAIL_COMPLETED_SNAPSHOT: Final = "the completed report failed read-back validation"
B12_DETAIL_UPLOAD_SNAPSHOT: Final = "the upload-carried evidence snapshot failed validation"
B12_DETAIL_MEMORY_SNAPSHOT: Final = "the in-memory upload snapshot is incomplete"
B12_DETAIL_MISSING_CARRIER: Final = "the B12 attempt carrier is missing before report freeze"
B12_DETAIL_CARRIER_MISMATCH: Final = "the B12 local retention carrier did not match its written bytes"
B12_EMBEDDED_SCOPE: Final = "sanitized baselines and ordered case evidence"
B12_DETAIL_POSTFREEZE: Final = "B12 evidence changed or disappeared during the cleanup report freeze"
B12_UTF8_REPLACE: Final = "replace"
B12_CLEARANCE_EVIDENCE: Final = "--build-started was refused by the CLI-owned clearance control"
B12_OWNER_IDENTITY_EVIDENCE: Final = "UC-RA3 and fresh public whoami/person read before the matrix"
B12_CASE_PRD_ID: Final = "01"
B12_CASE_KICKBACK_ID: Final = "15"
B12_DETAIL_CASE_ABSENT: Final = "{case_id}: item absent {when} the refusal"
B12_DETAIL_SESSIONS_CHANGED: Final = "{case_id}: session-id set changed {when} the refusal"
B12_DETAIL_SLUGS_CHANGED: Final = "{case_id}: slug set changed {when} the refusal"


class B12Field(StrEnum):
    """Closed JSON field vocabulary for the B12 durable and upload evidence."""

    SCHEMA_VERSION = "schema_version"
    STATUS = "status"
    SELECTED_AMENDMENT = "selected_amendment"
    ASSERTION_PATH = "assertion_path"
    ASSERTION_SHA256 = "assertion_sha256"
    SOURCE_REVISION = "source_revision"
    SOURCE_TREE = "source_tree"
    ISSUE_REVISION = "issue_revision"
    ORDERED_CASES = "ordered_cases"
    PREREQUISITES = "prerequisites"
    BASELINES = "baselines"
    CASES = "cases"
    CARRIER = "carrier"
    DURATION_SECONDS = "duration_seconds"
    PRIMARY_FAILURE = "primary_failure"
    EVIDENCE_FAILURE = "evidence_failure"
    CASE_ID = "case_id"
    RETIRED_TYPE = "retired_type"
    CLASSIFICATION = "classification"
    WHEN = "when"
    ITEM = "item"
    STATE = "state"
    SESSION_IDS = "session_ids"
    SLUGS = "slugs"
    READS = "reads"
    ARGV = "argv"
    EVENT = "event"
    STARTED_MONOTONIC_SECONDS = "started_monotonic_seconds"
    REASON = "reason"
    PROJECT_PATH = "project_path"
    CALLER_EVIDENCE = "caller_evidence"
    ATTEMPTS_PATH = "attempts_path"
    ORDERED_CASE_PLAN = "ordered_case_plan"
    MANUAL_RUNNER = "manual_runner"
    PROJECT_CWD = "project_cwd"
    CLEARANCE = "clearance"
    OWNER_IDENTITY_EVIDENCE = "owner_identity_evidence"
    OWNER_IDENTITY = "owner_identity"
    S0 = "S0"
    B0 = "B0"
    T0 = "T0"
    STABLE_SHOW_READS = "stable_show_reads"
    SEPARATION_SECONDS = "separation_seconds"
    EXIT_STATUS = "exit_status"
    OUTCOME = "outcome"
    STDOUT = "stdout"
    STDOUT_SHA256 = "stdout_sha256"
    STDOUT_BYTE_COUNT = "stdout_byte_count"
    EMBEDDED_STDOUT_SHA256 = "embedded_stdout_sha256"
    EMBEDDED_STDOUT_BYTE_COUNT = "embedded_stdout_byte_count"
    STDERR = "stderr"
    STDERR_CAPTURE = "stderr_capture"
    DIAGNOSTICS = "diagnostics"
    OUTPUT_TRUNCATED = "output_truncated"
    RETURNED_SUFFIX_DIAGNOSTIC = "returned_suffix_diagnostic"
    READBACKS = "readbacks"
    UNCHANGED = "unchanged"
    DIFFERENCES = "differences"
    OPERATION_ID = "operation_id"
    OPERATION_STATUS = "operation_status"
    REFUSAL_FAILURE = "refusal_failure"
    ATTEMPTS_SHA256 = "attempts_sha256"
    ATTEMPTS_BYTE_COUNT = "attempts_byte_count"
    ATTEMPTS_LINE_COUNT = "attempts_line_count"
    ORDERED_RESULTS = "ordered_results"
    ORIGINAL_SHA256 = "original_sha256"
    ORIGINAL_BYTE_COUNT = "original_byte_count"
    LINE_COUNT = "line_count"
    FRAMING = "framing"
    EMBEDDED_SHA256 = "embedded_sha256"
    EMBEDDED_BYTE_COUNT = "embedded_byte_count"
    READ_ERROR = "read_error"
    RAW_TEXT = "raw_text"
    RAW_TEXT_TRUNCATED = "raw_text_truncated"
    COMPLETED_PATH = "completed_path"
    COMPLETED_SHA256 = "completed_sha256"
    COMPLETED_BYTE_COUNT = "completed_byte_count"
    COMPLETED_RAW_TEXT = "completed_raw_text"
    COMPLETED_RAW_TEXT_TRUNCATED = "completed_raw_text_truncated"
    COMPLETED_READ_ERROR = "completed_read_error"
    MARKER_SHA256 = "marker_sha256"
    MARKER_BYTE_COUNT = "marker_byte_count"
    MARKER_PATH = "marker_path"
    MARKER_RAW_TEXT = "marker_raw_text"
    MARKER_RAW_TEXT_TRUNCATED = "marker_raw_text_truncated"
    EMBEDDED_SCOPE = "embedded_scope"
    RETIRED_ACT_EVIDENCE = "retired_act_evidence"
    EMAIL = "email"
    ROLE = "role"
    PERSON_IS_ADMINISTRATOR = "person_is_administrator"
    INITIAL_SHOW_READS = "initial_show_reads"
    BEFORE = "before"
    BEFORE_SHOW_READS = "show_reads"
    BEFORE_SESSIONS = "session_ids"
    BEFORE_SLUGS = "slugs"
    PRECALL_DIFFERENCES = "precall_differences"


RETIRED_SNAPSHOT_DIRECTORY: Final = "snapshots"
RETIRED_SNAPSHOT_PREFIX: Final = "retired-output-"
RETIRED_SNAPSHOT_SUFFIX: Final = ".txt"
RETIRED_SNAPSHOT_R4_CLEARANCE: Final = "r4-clearance"
RETIRED_SNAPSHOT_R4_PRD: Final = "r4-prd"
RETIRED_SNAPSHOT_R4_KICKBACK: Final = "r4-kickback"
RETIRED_SNAPSHOT_B13_KICKBACK: Final = "b13-kickback"
B12_REFUSAL_SNAPSHOT_MISSING: Final = (
    "the independently reviewed complete refusal snapshot is missing for case {case_id}"
)
B12_REFUSAL_SNAPSHOT_MISMATCH: Final = (
    "the complete refusal output differs from its reviewed snapshot for case {case_id}"
)
B12_CASES: Final = (
    ("01", (TELEC, TODO, STAMP, SLUG_FEATURE, PRD_APPROVED_FLAG), "prd_approved"),
    ("02", (TELEC, TODO, STAMP, SLUG_FEATURE, "--requirements-ready"), "requirements_ready"),
    ("03", (TELEC, TODO, STAMP, SLUG_FEATURE, "--plan-ready"), "plan_ready"),
    ("04", (TELEC, TODO, STAMP, SLUG_FEATURE, "--verdict", "approve", "--phase", "prd_review"), "verdict"),
    (
        "05",
        (TELEC, TODO, STAMP, SLUG_FEATURE, "--verdict", "approve", "--phase", "architecture_review"),
        "verdict",
    ),
    ("06", (TELEC, TODO, STAMP, SLUG_FEATURE, "--verdict", "approve", "--phase", "plan_review"), "verdict"),
    ("07", (TELEC, TODO, STAMP, SLUG_FEATURE, "--verdict", "approve", "--phase", "build_review"), "verdict"),
    (
        "08",
        (TELEC, TODO, STAMP, SLUG_FEATURE, "--architecture-skipped", "b12 retired architecture"),
        "architecture_skipped",
    ),
    ("09", (TELEC, TODO, STAMP, SLUG_FEATURE, "--diagnosis-settled"), "diagnosis_settled"),
    (
        "10",
        (TELEC, TODO, STAMP, SLUG_FEATURE, "--diagnosis-unresolved", REASON_OPTION, "b12 retired diagnosis"),
        "diagnosis_unresolved",
    ),
    (
        "11",
        (TELEC, TODO, STAMP, SLUG_FEATURE, "--drift-reviewed", "plan", "substantive", "b12 retired drift"),
        "drift_reviewed",
    ),
    ("12", (TELEC, TODO, STAMP, SLUG_FEATURE, "--deferrals-processed"), "deferrals_processed"),
    ("13", (TELEC, TODO, STAMP, SLUG_FEATURE, "--build-complete"), "build_complete"),
    ("14", (TELEC, TODO, STAMP, SLUG_FEATURE, "--finalize-ready"), "finalize_ready"),
    (
        "15",
        (TELEC, TODO, STAMP, SLUG_FEATURE, KICKBACK_FLAG, REASON_OPTION, KICKBACK_REASON),
        "kickback",
    ),
    (
        "16",
        (
            TELEC,
            TODO,
            "return-to-work",
            SLUG_FEATURE,
            REASON_OPTION,
            "b12 retired return",
            "--evidence",
            "b12-retired-act-preparation-matrix#case16",
        ),
        "return_to_work",
    ),
)
CREATED_PHRASE: Final = "Created todo: {slug}"
CREATED_PREFIX: Final = "Created todo:"
INPUT_ARTIFACT: Final = "input"
INPUT_BODY: Final = "# {slug} — Input\n\n{content}\n"
NOT_FOUND_PHRASE: Final = "slug '{slug}' not found in todo list"

PHASE_PREPARATION: Final = "preparation"
STATUS_ACTIVE: Final = "active"
RUNNER_MANUAL: Final = "manual"
STANDING_FORBIDDEN_KEYS: Final = (
    "held_by",
    "held_since",
    "admitted",
    "creative_episode",
    "waiting_on",
    "creative_orchestrator",
    "running_sessions_of_earlier_claims",
    "door",
)
FIELD_SLUG: Final = "slug"
FIELD_STATUS: Final = "status"
FIELD_CHILDREN: Final = "children"
FIELD_SESSION_ID: Final = "session_id"
FIELD_WORKING_SLUG: Final = "working_slug"
FIELD_CLOSED_AT: Final = "closed_at"
FIELD_ROADMAP: Final = "roadmap"
FIELD_STATE: Final = "state"
FIELD_KIND: Final = "kind"
FIELD_PHASE: Final = "lifecycle_phase"
FIELD_HOLD: Final = "hold"
FIELD_RUNNER: Final = "active_runner"
FIELD_STANDING: Final = "standing"
FIELD_STANDING_PHASE: Final = "phase"
FIELD_ARTIFACTS: Final = "artifacts"
FIELD_ARTIFACT_CONTENT: Final = "artifact_content"
FIELD_COMPUTER_SECTION: Final = "computer"
FIELD_WORKFLOW: Final = "workflow"
FIELD_RUNNER_MODE: Final = "runner"

QUIESCENCE_GAP_SECONDS: Final = 2.0
SETTLE_SECONDS: Final = 5.0
ABSENCE_WINDOW_SECONDS: Final = 65.0
ABSENCE_POLL_SECONDS: Final = 5.0

DETAIL_RUNNER: Final = "`telec config computer get --format json` does not read workflow.runner == manual: {output!r}"
DETAIL_DIRECTORY: Final = "the owner terminal is in {found!r}, not the owned project {project!r}"
DETAIL_UNDECODABLE: Final = "{what} output is not a decodable JSON object: {output!r}"
DETAIL_SESSION_RECORD: Final = "a session listing row is not an object carrying a session_id: {record!r}"
DETAIL_UNDECODABLE_LIST: Final = "{what} output is not a decodable JSON array: {output!r}"
DETAIL_NOT_FOUND_AMBIGUOUS: Final = "`todo show {slug}` failed without the not-found phrase: exit {status}, {output!r}"
DETAIL_SLUG_PRESENT: Final = "slug {slug} exists before the journey: {slugs!r}"
DETAIL_CREATE: Final = "`todo create` of {slug} did not report `Created todo: {slug}`: exit {status}, {output!r}"
DETAIL_VALUE: Final = "{slug}: {path} is {found!r}, the contract owes {expected!r}"
DETAIL_PATH_ABSENT: Final = "{slug}: the shown payload has no {path} (a source-traced path)"
DETAIL_ARTIFACT_SHAPE: Final = "{slug}: `artifacts` is not a list of artifact names: {found!r}"
DETAIL_STANDING_KEY: Final = (
    "{slug}: standing carries {key!r}, which an unclaimed, unadmitted item without episode lacks"
)
DETAIL_GATE_EXIT: Final = "the line without {flag} exited {status} with output {output!r}"
DETAIL_GATE_CREATED: Final = "the line without {flag} printed the creation confirmation: {output!r}"
DETAIL_GATE_SILENT: Final = "the line without {flag} printed nothing"
DETAIL_GATE_ITEM: Final = "the line without {flag} left an item {slug}: slugs {slugs!r}, found {found!r}"
DETAIL_SESSIONS_CHANGED: Final = "sessions changed from the baseline {baseline!r} to {now!r} {when}"
DETAIL_SESSION_FOR_SLUG: Final = "session {session} works on {slug}"
DETAIL_NOT_QUIESCENT: Final = "the item is being written by something else; differing paths: {paths}"
DETAIL_WRITE_LANDED: Final = "{case}: the item shown {when} differs from before the command; differing paths: {paths}"
DETAIL_SLUGS_CHANGED: Final = "{case}: the set of slugs changed from {before!r} to {after!r}"
DETAIL_PRECONDITION: Final = "{slug} is not in the table row this journey tests: {path} is {found!r}"
DETAIL_SNAPSHOT_MISSING: Final = "the reviewed complete-output snapshot is missing for {case}"
DETAIL_SNAPSHOT_MISMATCH: Final = "the complete public output differs from the reviewed snapshot for {case}"
DETAIL_REFUSAL_SHAPE: Final = "the public refusal for {case} was not a completed nonzero command without a receipt"
DETAIL_COMMAND: Final = "`{command}` exited {status}: {output!r}"

CASE_PRD: Final = "R4-1"
CASE_KICKBACK: Final = "R4-2"


class JourneyFailure(RuntimeError):
    """A journey result that proves something other than a pass; the message leads with its class."""


def fail(kind: str, detail: str) -> JourneyFailure:
    return JourneyFailure(MARK_FAILURE.format(kind=kind, detail=detail))


def binding_failure(detail: str) -> JourneyFailure:
    return fail(CLASS_BINDING, detail)


def trace_failure(detail: str) -> JourneyFailure:
    return fail(CLASS_TRACE, detail)


def platform_failure(detail: str) -> JourneyFailure:
    return fail(CLASS_PLATFORM, detail)


def normalized(output: str) -> str:
    """Runs of whitespace, newlines included, as one space."""
    return SPACE.join(output.split())


def retired_snapshot_state(snapshot_id: str, output: str) -> RetiredSnapshotState:
    """Compare one complete emitted string after only PTY line-ending and controller-separator normalization."""
    snapshot_path = (
        Path(__file__).parent
        / RETIRED_SNAPSHOT_DIRECTORY
        / (f"{RETIRED_SNAPSHOT_PREFIX}{snapshot_id}{RETIRED_SNAPSHOT_SUFFIX}")
    )
    try:
        expected = snapshot_path.read_text(encoding=B12_UTF8)
    except FileNotFoundError:
        return RetiredSnapshotState.MISSING
    observed = output.replace(B12_CARRIAGE_RETURN_LINE_ENDING, B12_LINE_ENDING)
    if observed.endswith(B12_LINE_ENDING):
        observed = observed[:-1]
    return RetiredSnapshotState.MATCH if observed == expected else RetiredSnapshotState.MISMATCH


def decode_object(output: str) -> Mapping[str, object] | None:
    """The JSON object starting on the first line whose first character opens one; text before it is not asserted."""
    decoder = json.JSONDecoder()
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith(JSON_OBJECT_START):
            continue
        try:
            value, _ = decoder.raw_decode(LINE_BREAK.join(lines[index:]))
        except json.JSONDecodeError:
            return None
        return {str(key): item for key, item in value.items()} if isinstance(value, dict) else None
    return None


def decode_array(output: str) -> list[object] | None:
    """The JSON array starting on the first line whose first character opens one."""
    decoder = json.JSONDecoder()
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("["):
            continue
        try:
            value, _ = decoder.raw_decode(LINE_BREAK.join(lines[index:]))
        except json.JSONDecodeError:
            return None
        return list(value) if isinstance(value, list) else None
    return None


def dig(value: object, path: str) -> tuple[bool, object]:
    """Follow a dotted path through nested objects; (False, None) when a step is absent."""
    current = value
    for step in path.split(DOT):
        if not isinstance(current, Mapping) or step not in current:
            return False, None
        current = current[step]
    return True, current


def differences(before: object, after: object, path: str = EMPTY) -> list[str]:
    """The paths at which two decoded values differ; object key order is ignored, list order is significant."""
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        found: list[str] = []
        for key in sorted({*before, *after}, key=str):
            where = f"{path}{DOT}{key}" if path else str(key)
            if key not in before or key not in after:
                found.append(where)
            else:
                found.extend(differences(before[key], after[key], where))
        return found
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [path or "<root>"]
        found = []
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            found.extend(differences(left, right, f"{path}[{index}]"))
        return found
    return [] if before == after else [path or "<root>"]


def collect_slugs(value: object) -> set[str]:
    """Every `slug` found recursively in the sectioned list payload."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        slug = value.get(FIELD_SLUG)
        if isinstance(slug, str):
            found.add(slug)
        for item in value.values():
            found |= collect_slugs(item)
    elif isinstance(value, list):
        for item in value:
            found |= collect_slugs(item)
    return found


@dataclass(frozen=True)
class SessionView:
    """The sessions the public listing shows: their ids, and which item each works on."""

    ids: frozenset[str]
    working: Mapping[str, str]
    closed: frozenset[str] = frozenset()


def command_evidence(argv: Sequence[str], outcome: Outcome) -> EvidenceObject:
    """Retain the original native result before parsing, including diagnostics and unsuccessful status."""
    return outcome.evidence(argv)


@dataclass
class RetiredActEvidence:
    """Typed, upload-carried B12 evidence retained independently of temporary files."""

    schema_version: int
    status: B12Status
    selected_amendment: str
    assertion_path: str
    assertion_sha256: str
    source_revision: str
    source_tree: str
    issue_revision: str
    ordered_cases: list[str]
    ordered_case_plan: list[EvidenceObject]
    prerequisites: EvidenceObject
    baselines: EvidenceObject
    cases: list[EvidenceObject]
    carrier: EvidenceObject
    duration_seconds: float
    primary_failure: str
    evidence_failure: str


def empty_retired_act_evidence(
    *,
    status: B12Status = B12_STATUS_NOT_SELECTED,
    source_revision: str = EMPTY,
    source_tree: str = EMPTY,
) -> RetiredActEvidence:
    """Create an explicit typed evidence state; an empty object is never a pass."""
    return RetiredActEvidence(
        schema_version=B12_JSON_SCHEMA,
        status=status,
        selected_amendment=B12_STATUS_NOT_SELECTED if status == B12_STATUS_NOT_SELECTED else B12_STATUS_NOT_RUN,
        assertion_path=B12_ARTIFACT_PATH,
        assertion_sha256=B12_ARTIFACT_SHA,
        source_revision=source_revision,
        source_tree=source_tree,
        issue_revision=B12_ISSUE_REVISION,
        ordered_cases=[case_id for case_id, _, _ in B12_CASES],
        ordered_case_plan=[
            {
                B12Field.CASE_ID: case_id,
                B12Field.ARGV: list(argv),
                B12Field.RETIRED_TYPE: retired_type,
            }
            for case_id, argv, retired_type in B12_CASES
        ],
        prerequisites={},
        baselines={},
        cases=[
            {
                B12Field.CASE_ID: case_id,
                B12Field.RETIRED_TYPE: retired_type,
                B12Field.CLASSIFICATION: B12_CLASS_NOT_RUN,
            }
            for case_id, _, retired_type in B12_CASES
        ],
        carrier={B12Field.FRAMING: B12_FRAMING_NOT_CREATED, B12Field.READ_ERROR: EMPTY},
        duration_seconds=0.0,
        primary_failure=EMPTY,
        evidence_failure=EMPTY,
    )


class Observer:
    """The approved observation primitives O1-O3, each a fresh public CLI process on the owner terminal."""

    def __init__(
        self,
        host: FoundationHost,
        *,
        deadline: float | None = None,
        deadline_detail: str = B12_ERROR_PREFIX + B12_DETAIL_DEADLINE,
    ) -> None:
        self.host = host
        self.deadline = deadline
        self.deadline_detail = deadline_detail

    def run(self, argv: Sequence[str], *, retain: bool = True) -> Outcome:
        timeout: float = CLI_TIMEOUT_SECONDS
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.require_time()
            timeout = min(timeout, remaining)
        return self.host.cli(argv, timeout, retain=retain)

    def require_time(self) -> None:
        """Fail closed once the caller's optional wall-clock budget expires."""
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise binding_failure(self.deadline_detail)

    def wait(self, seconds: float) -> None:
        """Wait only within the optional B12 scenario deadline."""
        if self.deadline is None:
            payload_work.sleep(seconds)
            return
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.require_time()
        payload_work.sleep(min(seconds, remaining))
        if time.monotonic() >= self.deadline:
            self.require_time()

    def show(self, slug: str, *, retain: bool = True) -> Mapping[str, object] | None:
        """O1: the shown payload of an item, or None when the platform says there is no such slug."""
        outcome = self.run((TELEC, TODO, SHOW, slug, INCLUDE_ARTIFACT_CONTENT), retain=retain)
        if outcome.exit_status == 0:
            payload = decode_object(outcome.output)
            if payload is None:
                raise binding_failure(DETAIL_UNDECODABLE.format(what=f"todo show {slug}", output=outcome.output[-300:]))
            return payload
        if NOT_FOUND_PHRASE.format(slug=slug) in outcome.output:
            return None
        raise binding_failure(
            DETAIL_NOT_FOUND_AMBIGUOUS.format(slug=slug, status=outcome.exit_status, output=outcome.output[-300:])
        )

    def slugs(self, *, retain: bool = True) -> set[str]:
        """O2: every slug of every section, icebox, delivered and removed included."""
        outcome = self.run(
            (TELEC, TODO, LIST, JSON_FLAG, INCLUDE_ICEBOX, INCLUDE_DELIVERED, INCLUDE_REMOVED), retain=retain
        )
        payload = decode_object(outcome.output) if outcome.output.strip().startswith(JSON_OBJECT_START) else None
        if outcome.exit_status != 0 or payload is None:
            raise binding_failure(DETAIL_UNDECODABLE.format(what="todo list", output=outcome.output[-300:]))
        return collect_slugs(payload)

    def sessions(self, *, retain: bool = True, evidence: list[EvidenceValue] | None = None) -> SessionView:
        """O3: every session, unattended procedure agents and closed ones included."""
        outcome = self.run((TELEC, SESSIONS, LIST, ALL_FLAG, CLOSED_FLAG), retain=retain)
        if evidence is not None:
            evidence.append(command_evidence((TELEC, SESSIONS, LIST, ALL_FLAG, CLOSED_FLAG), outcome))
        records = decode_array(outcome.output)
        if outcome.exit_status != 0 or records is None:
            raise binding_failure(DETAIL_UNDECODABLE_LIST.format(what="sessions list", output=outcome.output[-300:]))
        ids: set[str] = set()
        closed: set[str] = set()
        working: dict[str, str] = {}
        for record in records:
            if not isinstance(record, Mapping):
                raise binding_failure(DETAIL_SESSION_RECORD.format(record=record))
            session_id = record.get(FIELD_SESSION_ID)
            if not isinstance(session_id, str) or not session_id:
                raise binding_failure(DETAIL_SESSION_RECORD.format(record=record))
            ids.add(session_id)
            if record.get(FIELD_CLOSED_AT) is not None:
                closed.add(session_id)
            slug = record.get(FIELD_WORKING_SLUG)
            if isinstance(slug, str) and slug:
                working[session_id] = slug
        return SessionView(frozenset(ids), working, frozenset(closed))


def require_manual_runner(observer: Observer) -> None:
    """P1: the public configuration readback shows the manual workflow runner."""
    outcome = observer.run((TELEC, CONFIG, COMPUTER, GET, FORMAT_OPTION, JSON_FORMAT))
    payload = decode_object(outcome.output)
    path = f"{FIELD_COMPUTER_SECTION}{DOT}{FIELD_WORKFLOW}{DOT}{FIELD_RUNNER_MODE}"
    found, runner = dig(payload, path) if payload is not None else (False, None)
    if outcome.exit_status != 0 or not found or runner != RUNNER_MANUAL:
        raise binding_failure(DETAIL_RUNNER.format(output=outcome.output[-300:]))


def enter_project(observer: Observer, project: Path) -> None:
    """P2: the owner terminal's directory is the owned project, resolved."""
    changed = observer.run((CHANGE_DIRECTORY, str(project)))
    if changed.exit_status != 0:
        raise binding_failure(
            DETAIL_COMMAND.format(command=CHANGE_DIRECTORY, status=changed.exit_status, output=changed.output)
        )
    printed = observer.run((PRINT_DIRECTORY,))
    lines = [line.strip() for line in printed.output.splitlines() if line.strip()]
    found = lines[-1] if lines else EMPTY
    if printed.exit_status != 0 or not found or Path(found).resolve() != project.resolve():
        raise binding_failure(DETAIL_DIRECTORY.format(found=found, project=str(project)))


def leave_project(observer: Observer, source_root: Path) -> None:
    """Return the owner terminal to the source checkout, as the other journeys do."""
    observer.run((CHANGE_DIRECTORY, str(source_root)))


def create_item(observer: Observer, slug: str, content: str, kind: str, *, approved: bool) -> Outcome:
    argv = [TELEC, TODO, CREATE, slug, content, KIND_OPTION, kind]
    if approved:
        argv.append(APPROVED_FLAG)
    return observer.run(argv)


def require_created(outcome: Outcome, slug: str) -> None:
    if outcome.exit_status != 0 or CREATED_PHRASE.format(slug=slug) not in outcome.output:
        raise platform_failure(
            DETAIL_CREATE.format(slug=slug, status=outcome.exit_status, output=outcome.output[-300:])
        )


def require_value(slug: str, payload: Mapping[str, object], path: str, expected: object) -> None:
    found, value = dig(payload, path)
    if not found:
        raise trace_failure(DETAIL_PATH_ABSENT.format(slug=slug, path=path))
    if value != expected:
        raise platform_failure(DETAIL_VALUE.format(slug=slug, path=path, found=value, expected=expected))


def require_unclaimed(slug: str, payload: Mapping[str, object]) -> None:
    found, runner = dig(payload, f"{FIELD_STATE}{DOT}{FIELD_RUNNER}")
    if not found:
        raise trace_failure(DETAIL_PATH_ABSENT.format(slug=slug, path=f"{FIELD_STATE}{DOT}{FIELD_RUNNER}"))
    if runner not in (None, EMPTY):
        raise platform_failure(
            DETAIL_VALUE.format(slug=slug, path=f"{FIELD_STATE}{DOT}{FIELD_RUNNER}", found=runner, expected=None)
        )


def require_standing_clear(slug: str, payload: Mapping[str, object]) -> None:
    require_value(slug, payload, f"{FIELD_STANDING}{DOT}{FIELD_STANDING_PHASE}", PHASE_PREPARATION)
    _, standing = dig(payload, FIELD_STANDING)
    if not isinstance(standing, Mapping):
        raise trace_failure(DETAIL_PATH_ABSENT.format(slug=slug, path=FIELD_STANDING))
    for key in STANDING_FORBIDDEN_KEYS:
        if key in standing:
            raise platform_failure(DETAIL_STANDING_KEY.format(slug=slug, key=key))


def require_created_item(observer: Observer, slug: str, kind: str, content: str) -> None:
    """R1 step 2: what a plain creation stores, from the contract."""
    payload = observer.show(slug)
    if payload is None:
        raise platform_failure(DETAIL_VALUE.format(slug=slug, path="existence", found="absent", expected="present"))
    require_value(slug, payload, FIELD_SLUG, slug)
    require_value(slug, payload, f"{FIELD_STATE}{DOT}{FIELD_KIND}", kind)
    require_value(slug, payload, f"{FIELD_STATE}{DOT}{FIELD_PHASE}", PHASE_PREPARATION)
    require_value(slug, payload, f"{FIELD_ROADMAP}{DOT}{FIELD_STATUS}", STATUS_ACTIVE)
    require_value(slug, payload, f"{FIELD_STATE}{DOT}{FIELD_HOLD}", False)
    require_unclaimed(slug, payload)
    _, artifacts = dig(payload, FIELD_ARTIFACTS)
    if not isinstance(artifacts, list) or not all(isinstance(name, str) for name in artifacts):
        raise trace_failure(DETAIL_ARTIFACT_SHAPE.format(slug=slug, found=artifacts))
    if INPUT_ARTIFACT not in artifacts:
        raise platform_failure(
            DETAIL_VALUE.format(slug=slug, path=FIELD_ARTIFACTS, found=artifacts, expected=f"contains {INPUT_ARTIFACT}")
        )
    require_value(
        slug,
        payload,
        f"{FIELD_ARTIFACT_CONTENT}{DOT}{INPUT_ARTIFACT}",
        INPUT_BODY.format(slug=slug, content=content),
    )
    require_standing_clear(slug, payload)


def require_sessions_equal(baseline: SessionView, now: SessionView, when: str) -> None:
    if now.ids != baseline.ids:
        raise platform_failure(
            DETAIL_SESSIONS_CHANGED.format(baseline=sorted(baseline.ids), now=sorted(now.ids), when=when)
        )


def absence_window(observer: Observer, baseline: SessionView, slugs: Sequence[str]) -> None:
    """R1 step 5: no session appears in the window, and none works on any of the journey's items."""
    deadline = time.monotonic() + ABSENCE_WINDOW_SECONDS
    while True:
        now = observer.sessions(retain=False)
        require_sessions_equal(baseline, now, "inside the absence window")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        payload_work.sleep(min(ABSENCE_POLL_SECONDS, remaining))
    for session_id, slug in now.working.items():
        if slug in slugs:
            raise platform_failure(DETAIL_SESSION_FOR_SLUG.format(session=session_id, slug=slug))


def run_creation(host: FoundationHost, project: Path, source_root: Path) -> None:
    """Journey R1; raises JourneyFailure leading with its class."""
    observer = Observer(host)
    require_manual_runner(observer)
    enter_project(observer, project)
    try:
        present = observer.slugs()
        journey_slugs = (SLUG_FEATURE, SLUG_CHANGE, SLUG_BUG, SLUG_GATE)
        if present.intersection(journey_slugs):
            raise binding_failure(
                DETAIL_SLUG_PRESENT.format(slug=sorted(present.intersection(journey_slugs)), slugs=present)
            )
        baseline = observer.sessions()
        items = (
            (SLUG_FEATURE, KIND_FEATURE, CONTENT_FEATURE),
            (SLUG_CHANGE, KIND_CHANGE, CONTENT_CHANGE),
            (SLUG_BUG, KIND_BUG, CONTENT_BUG),
        )
        for slug, kind, content in items:
            require_created(create_item(observer, slug, content, kind, approved=True), slug)
        for slug, kind, content in items:
            require_created_item(observer, slug, kind, content)
        _gate_control(observer, baseline)
        twin = create_item(observer, SLUG_GATE, CONTENT_GATE, KIND_FEATURE, approved=True)
        require_created(twin, SLUG_GATE)
        gated = observer.show(SLUG_GATE)
        if gated is None:
            raise platform_failure(
                DETAIL_VALUE.format(slug=SLUG_GATE, path="existence", found="absent", expected="present")
            )
        require_value(SLUG_GATE, gated, f"{FIELD_STATE}{DOT}{FIELD_PHASE}", PHASE_PREPARATION)
        absence_window(observer, baseline, journey_slugs)
    finally:
        leave_project(observer, source_root)


def _gate_control(observer: Observer, baseline: SessionView) -> None:
    """R1 step 3: the creation line without the acknowledgement flag creates nothing."""
    outcome = create_item(observer, SLUG_GATE, CONTENT_GATE, KIND_FEATURE, approved=False)
    if outcome.exit_status != 0:
        raise platform_failure(
            DETAIL_GATE_EXIT.format(flag=APPROVED_FLAG, status=outcome.exit_status, output=outcome.output)
        )
    if not outcome.output.strip():
        raise platform_failure(DETAIL_GATE_SILENT.format(flag=APPROVED_FLAG))
    if CREATED_PREFIX in outcome.output:
        raise platform_failure(DETAIL_GATE_CREATED.format(flag=APPROVED_FLAG, output=outcome.output))
    found = observer.show(SLUG_GATE)
    slugs = observer.slugs()
    if found is not None or SLUG_GATE in slugs:
        raise platform_failure(
            DETAIL_GATE_ITEM.format(flag=APPROVED_FLAG, slug=SLUG_GATE, slugs=sorted(slugs), found=found)
        )
    require_sessions_equal(baseline, observer.sessions(), "after the gate control")


def _stamp(observer: Observer, slug: str, *flags: str) -> Outcome:
    return observer.run((TELEC, TODO, STAMP, slug, *flags))


def _quiescent_item(
    observer: Observer, show_reads: list[Mapping[str, object] | None] | None = None
) -> Mapping[str, object]:
    """P4 and P5: the item sits in the tested table row and two reads, apart, are deeply equal."""
    first = observer.show(SLUG_FEATURE)
    if show_reads is not None:
        show_reads.append(first)
    if first is None:
        raise binding_failure(DETAIL_PRECONDITION.format(slug=SLUG_FEATURE, path="existence", found="absent"))
    for path, expected in (
        (f"{FIELD_STATE}{DOT}{FIELD_PHASE}", PHASE_PREPARATION),
        (f"{FIELD_STATE}{DOT}{FIELD_HOLD}", False),
    ):
        found, value = dig(first, path)
        if not found or value != expected:
            raise binding_failure(DETAIL_PRECONDITION.format(slug=SLUG_FEATURE, path=path, found=value))
    found, runner = dig(first, f"{FIELD_STATE}{DOT}{FIELD_RUNNER}")
    if not found or runner not in (None, EMPTY):
        raise binding_failure(DETAIL_PRECONDITION.format(slug=SLUG_FEATURE, path=FIELD_RUNNER, found=runner))
    try:
        require_standing_clear(SLUG_FEATURE, first)
    except JourneyFailure as failure:
        raise binding_failure(
            DETAIL_PRECONDITION.format(slug=SLUG_FEATURE, path=FIELD_STANDING, found=str(failure))
        ) from failure
    observer.wait(QUIESCENCE_GAP_SECONDS)
    second = observer.show(SLUG_FEATURE)
    if show_reads is not None:
        show_reads.append(second)
    if second is None or differences(first, second):
        paths = differences(first, second) if second is not None else ["absent"]
        raise binding_failure(DETAIL_NOT_QUIESCENT.format(paths=paths))
    return second


def _b12_quiescent_item(
    observer: Observer, show_reads: list[Mapping[str, object] | None] | None = None
) -> Mapping[str, object]:
    """Apply B12's active-feature condition to the existing R4 quiescence witness."""
    payload = _quiescent_item(observer, show_reads)
    for path, expected in (
        (f"{FIELD_STATE}{DOT}{FIELD_KIND}", KIND_FEATURE),
        (f"{FIELD_ROADMAP}{DOT}{FIELD_STATUS}", STATUS_ACTIVE),
    ):
        found, value = dig(payload, path)
        if not found or value != expected:
            raise binding_failure(DETAIL_PRECONDITION.format(slug=SLUG_FEATURE, path=path, found=value))
    return payload


def _control_clearance(observer: Observer) -> None:
    """C0: the owner passes the stamp gate and meets the CLI's own machine-owned refusal, touching nothing."""
    outcome = _stamp(observer, SLUG_FEATURE, BUILD_STARTED_FLAG)
    _require_completed_refusal(outcome, RETIRED_SNAPSHOT_R4_CLEARANCE)
    _require_retired_snapshot(RETIRED_SNAPSHOT_R4_CLEARANCE, RETIRED_SNAPSHOT_R4_CLEARANCE, outcome.output)


def _require_completed_refusal(outcome: Outcome, case: str) -> None:
    """Require a completed nonzero public result without diagnostics or an operation receipt."""
    operation_id, _operation_status = _operation_receipt(outcome.output)
    if outcome.exit_status in (0, None) or outcome.diagnostics or operation_id is not None:
        raise platform_failure(DETAIL_REFUSAL_SHAPE.format(case=case))


def _require_retired_snapshot(case: str, snapshot_id: str, output: str) -> None:
    """Require the complete public output to equal its independently reviewed string snapshot."""
    state = retired_snapshot_state(snapshot_id, output)
    if state is RetiredSnapshotState.MISSING:
        raise trace_failure(DETAIL_SNAPSHOT_MISSING.format(case=case))
    if state is RetiredSnapshotState.MISMATCH:
        raise platform_failure(DETAIL_SNAPSHOT_MISMATCH.format(case=case))


def _require_nothing_written(
    observer: Observer, case: str, before: Mapping[str, object], sessions: SessionView, slugs: set[str]
) -> None:
    """After a refusal: the item, the sessions and the slugs are exactly as before, now and after a pause."""
    for when, pause in (("immediately", 0.0), ("five seconds later", SETTLE_SECONDS)):
        if pause:
            observer.wait(pause)
        after = observer.show(SLUG_FEATURE)
        if after is None:
            raise platform_failure(DETAIL_WRITE_LANDED.format(case=case, when=when, paths=["absent"]))
        changed = differences(before, after)
        if changed:
            raise platform_failure(DETAIL_WRITE_LANDED.format(case=case, when=when, paths=changed))
        require_sessions_equal(sessions, observer.sessions(), when)
    now = observer.slugs()
    if now != slugs:
        raise platform_failure(DETAIL_SLUGS_CHANGED.format(case=case, before=sorted(slugs), after=sorted(now)))


def run_retired_acts(host: FoundationHost, project: Path, source_root: Path) -> None:
    """Journey R4 on the item R1 left unchanged; raises JourneyFailure leading with its class."""
    observer = Observer(host)
    require_manual_runner(observer)
    enter_project(observer, project)
    try:
        _control_clearance(observer)
        cases = (
            (CASE_PRD, (PRD_APPROVED_FLAG,)),
            (CASE_KICKBACK, (KICKBACK_FLAG, REASON_OPTION, KICKBACK_REASON)),
        )
        for case, flags in cases:
            before = _quiescent_item(observer)
            sessions = observer.sessions()
            slugs = observer.slugs()
            outcome = _stamp(observer, SLUG_FEATURE, *flags)
            _require_completed_refusal(outcome, case)
            _require_nothing_written(observer, case, before, sessions, slugs)
            snapshot_id = RETIRED_SNAPSHOT_R4_PRD if case == CASE_PRD else RETIRED_SNAPSHOT_R4_KICKBACK
            _require_retired_snapshot(case, snapshot_id, outcome.output)
    finally:
        leave_project(observer, source_root)


def _evidence_object(value: object) -> EvidenceObject:
    """Copy a public JSON object into the report's recursively typed carrier."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_NOT_OBJECT)
    return decoded


def embedded_b12_evidence_bytes(evidence: RetiredActEvidence) -> bytes:
    """Serialize the sanitized baseline and ordered case observations embedded in report.json."""
    return json.dumps(
        {B12Field.BASELINES: evidence.baselines, B12Field.CASES: evidence.cases},
        ensure_ascii=False,
        sort_keys=True,
        separators=B12_JSON_SEPARATORS,
    ).encode(B12_UTF8)


def _sanitize_evidence(value: object, sanitize_text: Callable[[str], str]) -> EvidenceValue:
    """Sanitize local paths in the upload copy while local attempt bytes remain intact."""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_evidence(item, sanitize_text) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_evidence(item, sanitize_text) for item in value]
    if value is None:
        return value
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        return value
    raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_UNSUPPORTED)


def _sync_json(path: Path, value: EvidenceObject, *, exclusive: bool = False) -> bytes:
    """Write one complete JSON object and fsync it before returning its exact bytes."""
    mode = B12_MODE_EXCLUSIVE if exclusive else B12_MODE_WRITE
    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=B12_JSON_SEPARATORS) + B12_LINE_ENDING
    ).encode(B12_UTF8)
    with path.open(mode, encoding=B12_UTF8, newline="") as handle:
        handle.write(encoded.decode(B12_UTF8))
        handle.flush()
        os.fsync(handle.fileno())
    return encoded


def _append_attempt(path: Path, value: EvidenceObject) -> None:
    """Append one whole JSONL record and fsync the append before the next action."""
    with path.open(B12_MODE_APPEND, encoding=B12_UTF8, newline="") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=B12_JSON_SEPARATORS))
        handle.write(B12_LINE_ENDING)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    """Fsync a directory entry set after durable carrier creation or replacement."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_b12_attempts(raw: bytes, complete: bool) -> list[EvidenceObject]:
    """Require ordered open/result/classification records; malformed tails stay unproven."""
    if raw and not raw.endswith(b"\n"):
        raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_TRAILING_LINE)
    if not raw:
        if complete:
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_EMPTY_COMPLETE)
        return []
    records: list[EvidenceObject] = []
    for line in raw.splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_NOT_OBJECT_LINE)
        records.append(value)
    expected_count = len(B12_CASES) * 3
    if len(records) > expected_count or (complete and len(records) != expected_count):
        raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_EXTRA_RECORDS)
    for case_index, (case_id, expected_argv, _retired_type) in enumerate(B12_CASES):
        offset = case_index * 3
        if offset >= len(records):
            break
        opened = records[offset]
        if (
            opened.get(B12Field.CASE_ID) != case_id
            or opened.get(B12Field.EVENT) != B12_EVENT_OPEN
            or opened.get(B12Field.ARGV) != list(expected_argv)
        ):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_UNORDERED_OPEN.format(case_id=case_id))
        if offset + 1 >= len(records):
            break
        result = records[offset + 1]
        if result.get(B12Field.CASE_ID) != case_id or result.get(B12Field.EVENT) != B12_EVENT_RESULT:
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_UNORDERED_RESULT.format(case_id=case_id))
        if complete and (
            result.get(B12Field.OUTCOME) != B12_OUTCOME_COMPLETED
            or type(result.get(B12Field.EXIT_STATUS)) is not int
            or result.get(B12Field.EXIT_STATUS) == 0
            or result.get(B12Field.REFUSAL_FAILURE) != EMPTY
            or result.get(B12Field.DIFFERENCES) != []
            or result.get(B12Field.OPERATION_ID) is not None
            or result.get(B12Field.OPERATION_STATUS) != B12_OPERATION_NOT_APPLICABLE
        ):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_INVALID_RESULT.format(case_id=case_id))
        result_output = result.get(B12Field.STDOUT)
        if complete and (
            not isinstance(result_output, str)
            or result.get(B12Field.OUTPUT_TRUNCATED) is not False
            or retired_snapshot_state(f"{B12_SNAPSHOT_ID_PREFIX}{case_id}", result_output)
            is not RetiredSnapshotState.MATCH
        ):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_INVALID_RESULT.format(case_id=case_id))
        if offset + 2 >= len(records):
            break
        classified = records[offset + 2]
        if classified.get(B12Field.CASE_ID) != case_id or classified.get(B12Field.EVENT) != B12_EVENT_VERIFIED:
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_UNORDERED_CLASSIFICATION.format(case_id=case_id))
        if complete and classified.get(B12Field.CLASSIFICATION) != B12_CLASS_VERIFIED:
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_NOT_VERIFIED.format(case_id=case_id))
    return records


def _b12_refusal_shape(exit_status: int | None, diagnostics: str, operation_id: str | None) -> str:
    """Require a completed nonzero no-receipt public command before its no-write readbacks."""
    if exit_status in (None, 0):
        return B12_REFUSAL_NO_TERMINAL if exit_status is None else B12_REFUSAL_ZERO_EXIT
    if diagnostics:
        return B12_REFUSAL_DIAGNOSTIC.format(detail=diagnostics)
    if operation_id is not None:
        return B12_REFUSAL_RECEIPT
    return EMPTY


def _b12_snapshot_failure(case_id: str, output: str) -> str:
    """Return the missing or mismatching complete-output snapshot failure for one matrix row."""
    snapshot_id = f"{B12_SNAPSHOT_ID_PREFIX}{case_id}"
    state = retired_snapshot_state(snapshot_id, output)
    if state is RetiredSnapshotState.MISSING:
        return B12_REFUSAL_SNAPSHOT_MISSING.format(case_id=case_id)
    if state is RetiredSnapshotState.MISMATCH:
        return B12_REFUSAL_SNAPSHOT_MISMATCH.format(case_id=case_id)
    return EMPTY


def _operation_receipt(output: str) -> tuple[str | None, str]:
    """Preserve a genuinely decoded unexpected operation receipt and any public status."""
    payload = decode_object(output)
    if payload is None:
        return None, B12_OPERATION_NOT_APPLICABLE

    def find_receipt(value: object) -> tuple[str | None, str]:
        if isinstance(value, Mapping):
            operation_id = value.get(B12Field.OPERATION_ID)
            if isinstance(operation_id, str) and operation_id:
                status = value.get(B12Field.STATE)
                return operation_id, status if isinstance(status, str) and status else B12_OPERATION_UNKNOWN
            for nested in value.values():
                operation_id, status = find_receipt(nested)
                if operation_id is not None:
                    return operation_id, status
        elif isinstance(value, list):
            for nested in value:
                operation_id, status = find_receipt(nested)
                if operation_id is not None:
                    return operation_id, status
        return None, B12_OPERATION_NOT_APPLICABLE

    return find_receipt(payload)


def _record_b12_failure(
    evidence: RetiredActEvidence,
    attempts_path: Path,
    error: BaseException,
    sanitize_text: Callable[[str], str],
    started_at: float,
) -> None:
    """Freeze the last known partial state and local carrier seal without replacing the primary failure."""
    verified_count = sum(case.get(B12Field.CLASSIFICATION) == B12_CLASS_VERIFIED for case in evidence.cases)
    evidence.status = B12_STATUS_PARTIAL if 0 < verified_count < len(B12_CASES) else B12_STATUS_UNPROVEN
    evidence.duration_seconds = max(0.0, time.monotonic() - started_at)
    evidence.primary_failure = sanitize_text(
        evidence.primary_failure or B12_EXCEPTION_DETAIL.format(error_class=type(error).__name__, detail=error)
    )
    evidence.prerequisites = cast(EvidenceObject, _sanitize_evidence(evidence.prerequisites, sanitize_text))
    evidence.baselines = cast(EvidenceObject, _sanitize_evidence(evidence.baselines, sanitize_text))
    evidence.cases = [cast(EvidenceObject, _sanitize_evidence(case, sanitize_text)) for case in evidence.cases]
    completed_path = attempts_path.parent / B12_COMPLETED_FILE
    marker_path = attempts_path.parent / B12_MARKER_FILE
    if not attempts_path.exists():
        marker_path = attempts_path.parent / B12_MARKER_FILE
        if marker_path.exists():
            evidence.carrier[B12Field.FRAMING] = B12_FRAMING_MISSING
            evidence.carrier[B12Field.READ_ERROR] = B12_CARRIER_ERROR_MARKER
            evidence.evidence_failure = evidence.evidence_failure or str(evidence.carrier[B12Field.READ_ERROR])
            try:
                marker_raw = marker_path.read_bytes()
                evidence.carrier.update(
                    {
                        B12Field.MARKER_PATH: sanitize_text(str(marker_path.resolve())),
                        B12Field.MARKER_SHA256: hashlib.sha256(marker_raw).hexdigest(),
                        B12Field.MARKER_BYTE_COUNT: len(marker_raw),
                        B12Field.MARKER_RAW_TEXT: sanitize_text(marker_raw.decode(B12_UTF8, errors=B12_UTF8_REPLACE))[
                            :65536
                        ],
                        B12Field.MARKER_RAW_TEXT_TRUNCATED: len(marker_raw) > 65536,
                    }
                )
            except Exception as marker_error:
                detail = sanitize_text(
                    B12_EXCEPTION_DETAIL.format(error_class=type(marker_error).__name__, detail=marker_error)
                )
                evidence.carrier[B12Field.READ_ERROR] = detail
                evidence.evidence_failure = evidence.evidence_failure or detail
        else:
            evidence.carrier.setdefault(B12Field.FRAMING, B12_FRAMING_NOT_CREATED)
            evidence.carrier.setdefault(B12Field.READ_ERROR, EMPTY)
    else:
        try:
            raw = attempts_path.read_bytes()
            embedded = embedded_b12_evidence_bytes(evidence)
            evidence.carrier.update(
                {
                    B12Field.ATTEMPTS_PATH: sanitize_text(str(attempts_path.resolve())),
                    B12Field.ORIGINAL_SHA256: hashlib.sha256(raw).hexdigest(),
                    B12Field.ORIGINAL_BYTE_COUNT: len(raw),
                    B12Field.FRAMING: B12_FRAMING_COMPLETE if not raw or raw.endswith(b"\n") else B12_FRAMING_PARTIAL,
                    B12Field.RAW_TEXT: sanitize_text(raw.decode(B12_UTF8, errors=B12_UTF8_REPLACE))[:65536],
                    B12Field.RAW_TEXT_TRUNCATED: len(raw) > 65536,
                    B12Field.EMBEDDED_SHA256: hashlib.sha256(embedded).hexdigest(),
                    B12Field.EMBEDDED_BYTE_COUNT: len(embedded),
                    B12Field.EMBEDDED_SCOPE: B12_EMBEDDED_SCOPE,
                    B12Field.READ_ERROR: EMPTY,
                }
            )
            try:
                records = validate_b12_attempts(raw, complete=False)
                evidence.carrier[B12Field.LINE_COUNT] = len(records)
            except Exception as validation_error:
                detail = sanitize_text(
                    B12_EXCEPTION_DETAIL.format(error_class=type(validation_error).__name__, detail=validation_error)
                )
                evidence.carrier[B12Field.READ_ERROR] = detail
                evidence.evidence_failure = evidence.evidence_failure or detail
        except Exception as read_error:
            detail = sanitize_text(
                B12_EXCEPTION_DETAIL.format(error_class=type(read_error).__name__, detail=read_error)
            )
            evidence.carrier[B12Field.READ_ERROR] = detail
            evidence.evidence_failure = evidence.evidence_failure or detail
    if marker_path.exists():
        try:
            marker_raw = marker_path.read_bytes()
            evidence.carrier.update(
                {
                    B12Field.MARKER_PATH: sanitize_text(str(marker_path.resolve())),
                    B12Field.MARKER_SHA256: hashlib.sha256(marker_raw).hexdigest(),
                    B12Field.MARKER_BYTE_COUNT: len(marker_raw),
                }
            )
        except Exception as marker_error:
            detail = sanitize_text(
                B12_EXCEPTION_DETAIL.format(error_class=type(marker_error).__name__, detail=marker_error)
            )
            evidence.carrier[B12Field.READ_ERROR] = detail
            evidence.evidence_failure = evidence.evidence_failure or detail
    elif attempts_path.exists():
        evidence.status = B12_STATUS_UNPROVEN
        evidence.carrier[B12Field.READ_ERROR] = B12_CARRIER_ERROR_MARKER
        evidence.evidence_failure = evidence.evidence_failure or B12_CARRIER_ERROR_MARKER
    if completed_path.exists():
        try:
            completed_raw = completed_path.read_bytes()
            evidence.carrier.update(
                {
                    B12Field.COMPLETED_PATH: sanitize_text(str(completed_path.resolve())),
                    B12Field.COMPLETED_SHA256: hashlib.sha256(completed_raw).hexdigest(),
                    B12Field.COMPLETED_BYTE_COUNT: len(completed_raw),
                    B12Field.COMPLETED_RAW_TEXT: sanitize_text(completed_raw.decode(B12_UTF8, errors=B12_UTF8_REPLACE))[
                        :65536
                    ],
                    B12Field.COMPLETED_RAW_TEXT_TRUNCATED: len(completed_raw) > 65536,
                    B12Field.COMPLETED_READ_ERROR: EMPTY,
                }
            )
        except Exception as completed_error:
            detail = sanitize_text(
                B12_EXCEPTION_DETAIL.format(error_class=type(completed_error).__name__, detail=completed_error)
            )
            evidence.carrier[B12Field.COMPLETED_READ_ERROR] = detail
            evidence.evidence_failure = evidence.evidence_failure or detail


def _b12_readbacks(
    observer: Observer,
    baseline_item: Mapping[str, object],
    baseline_sessions: SessionView,
    baseline_slugs: set[str],
    case_id: str,
    reads: list[EvidenceObject],
) -> tuple[EvidenceObject, list[str]]:
    """Capture immediate and settled public item/session/slug reads and compare each with the frozen baseline."""
    differences_found: list[str] = []
    for when, pause in ((B12_CASE_IMMEDIATE, 0.0), (B12_CASE_SETTLED, B12_SETTLE_SECONDS)):
        if pause:
            observer.wait(pause)
        item = observer.show(SLUG_FEATURE)
        observation = _evidence_object({B12Field.WHEN: when, B12Field.ITEM: item})
        reads.append(observation)
        sessions = observer.sessions()
        observation[B12Field.SESSION_IDS] = cast(list[EvidenceValue], sorted(sessions.ids))
        slugs = observer.slugs()
        observation[B12Field.SLUGS] = cast(list[EvidenceValue], sorted(slugs))
        if item is None:
            differences_found.append(B12_DETAIL_CASE_ABSENT.format(case_id=case_id, when=when))
        else:
            differences_found.extend(differences(baseline_item, item))
        if sessions.ids != baseline_sessions.ids:
            differences_found.append(B12_DETAIL_SESSIONS_CHANGED.format(case_id=case_id, when=when))
        if slugs != baseline_slugs:
            differences_found.append(B12_DETAIL_SLUGS_CHANGED.format(case_id=case_id, when=when))
    return _evidence_object({B12Field.READS: reads}), differences_found


def run_retired_act_matrix(
    host: FoundationHost,
    project: Path,
    source_root: Path,
    temporary_root: Path,
    evidence: RetiredActEvidence,
    retain_reason: Callable[[str], None],
    release_reason: Callable[[str], None],
    sanitize_text: Callable[[str], str],
    started_at: float | None = None,
) -> None:
    """Run the approved B12 matrix once at R4's preparation checkpoint and retain a sealed report."""
    started = started_at if started_at is not None else time.monotonic()
    deadline = started + B12_SCENARIO_SECONDS
    observer = Observer(host, deadline=deadline)
    evidence.selected_amendment = B12_AMENDMENT
    evidence.status = B12_STATUS_PARTIAL
    matrix_root = temporary_root / B12_MATRIX_DIRECTORY
    marker_path = matrix_root / B12_MARKER_FILE
    attempts_path = matrix_root / B12_ATTEMPTS_FILE
    completed_path = matrix_root / B12_COMPLETED_FILE
    returned_to_source = False
    baseline_item: Mapping[str, object] | None = None
    baseline_sessions: SessionView | None = None
    baseline_slugs: set[str] | None = None
    try:
        require_manual_runner(observer)
        enter_project(observer, project)
        _control_clearance(observer)
        baseline_sessions = observer.sessions()
        evidence.baselines[B12Field.B0] = cast(list[EvidenceValue], sorted(baseline_sessions.ids))
        baseline_slugs = observer.slugs()
        evidence.baselines[B12Field.T0] = cast(list[EvidenceValue], sorted(baseline_slugs))
        initial_show_reads: list[Mapping[str, object] | None] = []
        evidence.baselines[B12Field.INITIAL_SHOW_READS] = cast(list[EvidenceValue], initial_show_reads)
        baseline_item = _b12_quiescent_item(observer, initial_show_reads)
        evidence.baselines[B12Field.S0] = _sanitize_evidence(baseline_item, sanitize_text)
        evidence.prerequisites.update(
            _evidence_object(
                {
                    B12Field.MANUAL_RUNNER: True,
                    B12Field.PROJECT_CWD: sanitize_text(str(project.resolve())),
                    B12Field.CLEARANCE: B12_CLEARANCE_EVIDENCE,
                    B12Field.OWNER_IDENTITY_EVIDENCE: B12_OWNER_IDENTITY_EVIDENCE,
                }
            )
        )
        evidence.baselines.update(
            _evidence_object(
                {
                    B12Field.S0: _sanitize_evidence(baseline_item, sanitize_text),
                    B12Field.INITIAL_SHOW_READS: _sanitize_evidence(initial_show_reads, sanitize_text),
                    B12Field.B0: sorted(baseline_sessions.ids),
                    B12Field.T0: sorted(baseline_slugs),
                    B12Field.STABLE_SHOW_READS: 2,
                    B12Field.SEPARATION_SECONDS: B12_INITIAL_STABILITY_SECONDS,
                }
            )
        )
        matrix_root.mkdir()
        _sync_directory(temporary_root)
        marker = _evidence_object(
            {
                B12Field.SCHEMA_VERSION: B12_JSON_SCHEMA,
                B12Field.REASON: B12_REASON,
                B12Field.SOURCE_REVISION: evidence.source_revision,
                B12Field.SOURCE_TREE: evidence.source_tree,
                B12Field.ISSUE_REVISION: evidence.issue_revision,
                B12Field.ASSERTION_PATH: evidence.assertion_path,
                B12Field.ASSERTION_SHA256: evidence.assertion_sha256,
                B12Field.PROJECT_PATH: str(project.resolve()),
                B12Field.CALLER_EVIDENCE: evidence.prerequisites,
                B12Field.S0: baseline_item,
                B12Field.B0: sorted(baseline_sessions.ids),
                B12Field.T0: sorted(baseline_slugs),
                B12Field.ORDERED_CASES: [case_id for case_id, _, _ in B12_CASES],
                B12Field.ORDERED_CASE_PLAN: [
                    {B12Field.CASE_ID: case_id, B12Field.ARGV: list(argv), B12Field.RETIRED_TYPE: retired_type}
                    for case_id, argv, retired_type in B12_CASES
                ],
                B12Field.ATTEMPTS_PATH: str(attempts_path.resolve()),
            }
        )
        marker_bytes = _sync_json(marker_path, marker, exclusive=True)
        if marker_path.read_bytes() != marker_bytes:
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_CARRIER_MISMATCH)
        evidence.carrier.update(
            {
                B12Field.MARKER_PATH: sanitize_text(str(marker_path.resolve())),
                B12Field.MARKER_SHA256: hashlib.sha256(marker_bytes).hexdigest(),
                B12Field.MARKER_BYTE_COUNT: len(marker_bytes),
            }
        )
        with attempts_path.open(B12_MODE_EXCLUSIVE, encoding=B12_UTF8, newline="") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        if attempts_path.read_bytes():
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_CARRIER_MISMATCH)
        _sync_directory(matrix_root)
        retain_reason(B12_RETAIN_REASON.format(path=marker_path))
        evidence.status = B12_STATUS_PARTIAL
        for case_index, (case_id, argv, retired_type) in enumerate(B12_CASES):
            case = evidence.cases[case_index]
            case.update(
                {
                    B12Field.ARGV: list(argv),
                    B12Field.RETIRED_TYPE: retired_type,
                }
            )
            before_show_reads: list[Mapping[str, object] | None] = []
            before = cast(
                EvidenceObject,
                {
                    B12Field.ITEM: {},
                    B12Field.BEFORE_SHOW_READS: cast(list[EvidenceValue], before_show_reads),
                    B12Field.BEFORE_SESSIONS: [],
                    B12Field.BEFORE_SLUGS: [],
                    B12Field.PRECALL_DIFFERENCES: [],
                },
            )
            case[B12Field.BEFORE] = before
            before_item = _b12_quiescent_item(observer, before_show_reads)
            before[B12Field.ITEM] = _sanitize_evidence(before_item, sanitize_text)
            before[B12Field.BEFORE_SHOW_READS] = _sanitize_evidence(before_show_reads, sanitize_text)
            before_sessions = observer.sessions()
            before[B12Field.BEFORE_SESSIONS] = cast(list[EvidenceValue], sorted(before_sessions.ids))
            before_slugs = observer.slugs()
            before[B12Field.BEFORE_SLUGS] = cast(list[EvidenceValue], sorted(before_slugs))
            before_differences = differences(baseline_item, before_item)
            before[B12Field.PRECALL_DIFFERENCES] = cast(list[EvidenceValue], before_differences)
            if before_differences or before_sessions.ids != baseline_sessions.ids or before_slugs != baseline_slugs:
                detail = B12_DETAIL_PRECALL_STATE_CHANGED.format(case_id=case_id, differences=before_differences)
                raise platform_failure(B12_ERROR_PREFIX + detail)
            open_record: EvidenceObject = {
                B12Field.EVENT: B12_EVENT_OPEN,
                B12Field.CASE_ID: case_id,
                B12Field.ARGV: list(argv),
                B12Field.STARTED_MONOTONIC_SECONDS: time.monotonic() - started,
            }
            _append_attempt(attempts_path, open_record)
            case[B12Field.CLASSIFICATION] = B12_CLASS_OPEN
            call_started = time.monotonic()
            outcome = observer.run(argv)
            result_duration = max(outcome.duration_seconds, time.monotonic() - call_started)
            outcome_kind = (
                B12_OUTCOME_COMPLETED
                if outcome.exit_status is not None
                else B12_OUTCOME_TIMEOUT
                if outcome.diagnostics == B12_TIMEOUT_DIAGNOSTIC
                else B12_OUTCOME_TRANSPORT
            )
            operation_id, operation_status = _operation_receipt(outcome.output)
            refusal_failure = _b12_refusal_shape(outcome.exit_status, outcome.diagnostics, operation_id)
            stdout_bytes = outcome.output.encode(B12_UTF8)
            embedded_stdout = sanitize_text(outcome.output).encode(B12_UTF8)
            case.update(
                _evidence_object(
                    {
                        B12Field.DURATION_SECONDS: result_duration,
                        B12Field.OUTCOME: outcome_kind,
                        B12Field.EXIT_STATUS: outcome.exit_status,
                        B12Field.STDOUT: embedded_stdout.decode(B12_UTF8),
                        B12Field.STDOUT_SHA256: hashlib.sha256(stdout_bytes).hexdigest(),
                        B12Field.STDOUT_BYTE_COUNT: len(stdout_bytes),
                        B12Field.EMBEDDED_STDOUT_SHA256: hashlib.sha256(embedded_stdout).hexdigest(),
                        B12Field.EMBEDDED_STDOUT_BYTE_COUNT: len(embedded_stdout),
                        B12Field.STDERR: sanitize_text(outcome.stderr),
                        B12Field.STDERR_CAPTURE: B12_PTY_CAPTURE,
                        B12Field.DIAGNOSTICS: sanitize_text(outcome.diagnostics),
                        B12Field.OUTPUT_TRUNCATED: outcome.diagnostics == B12_OUTPUT_LIMIT_DIAGNOSTIC,
                        B12Field.RETURNED_SUFFIX_DIAGNOSTIC: sanitize_text(normalized(outcome.output)),
                        B12Field.OPERATION_ID: operation_id,
                        B12Field.OPERATION_STATUS: operation_status,
                        B12Field.REFUSAL_FAILURE: refusal_failure,
                    }
                )
            )
            case_reads: list[EvidenceObject] = []
            case[B12Field.READBACKS] = cast(list[EvidenceValue], case_reads)
            after_reads: EvidenceObject = {B12Field.READS: []}
            readback_differences: list[str] = []
            if not refusal_failure:
                after_reads, readback_differences = _b12_readbacks(
                    observer, baseline_item, baseline_sessions, baseline_slugs, case_id, case_reads
                )
                refusal_failure = _b12_snapshot_failure(case_id, outcome.output)
            sanitized_readbacks = _sanitize_evidence(after_reads[B12Field.READS], sanitize_text)
            case.update(
                _evidence_object(
                    {
                        B12Field.READBACKS: sanitized_readbacks,
                        B12Field.DIFFERENCES: readback_differences,
                        B12Field.REFUSAL_FAILURE: refusal_failure,
                    }
                )
            )
            classification = (
                B12_CLASS_VERIFIED if not refusal_failure and not readback_differences else B12_CLASS_UNPROVEN
            )
            case.update(
                _evidence_object(
                    {
                        B12Field.UNCHANGED: classification == B12_CLASS_VERIFIED,
                        B12Field.CLASSIFICATION: classification,
                    }
                )
            )
            result_record = _evidence_object(
                {
                    B12Field.EVENT: B12_EVENT_RESULT,
                    B12Field.CASE_ID: case_id,
                    B12Field.DURATION_SECONDS: result_duration,
                    B12Field.OUTCOME: case[B12Field.OUTCOME],
                    B12Field.EXIT_STATUS: outcome.exit_status,
                    B12Field.STDOUT: outcome.output,
                    B12Field.STDOUT_SHA256: hashlib.sha256(stdout_bytes).hexdigest(),
                    B12Field.STDOUT_BYTE_COUNT: len(stdout_bytes),
                    B12Field.STDERR: outcome.stderr,
                    B12Field.STDERR_CAPTURE: B12_PTY_CAPTURE,
                    B12Field.DIAGNOSTICS: outcome.diagnostics,
                    B12Field.OUTPUT_TRUNCATED: outcome.diagnostics == B12_OUTPUT_LIMIT_DIAGNOSTIC,
                    B12Field.READBACKS: after_reads[B12Field.READS],
                    B12Field.DIFFERENCES: readback_differences,
                    B12Field.OPERATION_ID: operation_id,
                    B12Field.OPERATION_STATUS: operation_status,
                    B12Field.REFUSAL_FAILURE: refusal_failure,
                }
            )
            _append_attempt(attempts_path, result_record)
            _append_attempt(
                attempts_path,
                {
                    B12Field.EVENT: B12_EVENT_VERIFIED,
                    B12Field.CASE_ID: case_id,
                    B12Field.CLASSIFICATION: classification,
                },
            )
            if classification != B12_CLASS_VERIFIED:
                evidence.primary_failure = refusal_failure or repr(readback_differences)
                evidence.status = B12_STATUS_UNPROVEN if case_index == 0 else B12_STATUS_PARTIAL
                raise platform_failure(B12_ERROR_PREFIX + evidence.primary_failure)
            validate_b12_attempts(attempts_path.read_bytes(), complete=False)
        leave_project(observer, source_root)
        returned_to_source = True
        observer.require_time()
        evidence.duration_seconds = time.monotonic() - started
        raw_attempts = attempts_path.read_bytes()
        records = validate_b12_attempts(raw_attempts, complete=True)
        completed = _evidence_object(
            {
                B12Field.SCHEMA_VERSION: B12_JSON_SCHEMA,
                B12Field.STATUS: B12_STATUS_COMPLETE,
                B12Field.ORDERED_RESULTS: evidence.cases,
                B12Field.ATTEMPTS_SHA256: hashlib.sha256(raw_attempts).hexdigest(),
                B12Field.ATTEMPTS_BYTE_COUNT: len(raw_attempts),
                B12Field.ATTEMPTS_LINE_COUNT: len(records),
                B12Field.DURATION_SECONDS: evidence.duration_seconds,
            }
        )
        temporary_completed = completed_path.with_suffix(B12_JSON_SUFFIX)
        _sync_json(temporary_completed, completed)
        temporary_completed.replace(completed_path)
        _sync_directory(matrix_root)
        readback = json.loads(completed_path.read_text(encoding=B12_UTF8))
        if (
            not isinstance(readback, dict)
            or readback.get(B12Field.STATUS) != B12_STATUS_COMPLETE
            or readback.get(B12Field.ATTEMPTS_SHA256) != hashlib.sha256(raw_attempts).hexdigest()
            or readback.get(B12Field.ATTEMPTS_BYTE_COUNT) != len(raw_attempts)
            or readback.get(B12Field.ATTEMPTS_LINE_COUNT) != len(records)
            or readback.get(B12Field.ORDERED_RESULTS) != evidence.cases
            or len(readback.get(B12Field.ORDERED_RESULTS, [])) != len(B12_CASES)
        ):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_COMPLETED_SNAPSHOT)
        observer.require_time()
        evidence.duration_seconds = time.monotonic() - started
        completed[B12Field.DURATION_SECONDS] = evidence.duration_seconds
        _sync_json(temporary_completed, completed)
        temporary_completed.replace(completed_path)
        _sync_directory(matrix_root)
        readback = json.loads(completed_path.read_text(encoding=B12_UTF8))
        if not isinstance(readback, dict) or readback != completed:
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_COMPLETED_SNAPSHOT)
        completed_bytes = completed_path.read_bytes()
        evidence.carrier.update(
            {
                B12Field.ATTEMPTS_PATH: sanitize_text(str(attempts_path.resolve())),
                B12Field.COMPLETED_PATH: sanitize_text(str(completed_path.resolve())),
                B12Field.COMPLETED_SHA256: hashlib.sha256(completed_bytes).hexdigest(),
                B12Field.COMPLETED_BYTE_COUNT: len(completed_bytes),
                B12Field.ORIGINAL_SHA256: hashlib.sha256(raw_attempts).hexdigest(),
                B12Field.ORIGINAL_BYTE_COUNT: len(raw_attempts),
                B12Field.LINE_COUNT: len(records),
                B12Field.FRAMING: B12_FRAMING_COMPLETE,
                B12Field.EMBEDDED_SHA256: hashlib.sha256(embedded_b12_evidence_bytes(evidence)).hexdigest(),
                B12Field.EMBEDDED_BYTE_COUNT: len(embedded_b12_evidence_bytes(evidence)),
                B12Field.EMBEDDED_SCOPE: B12_EMBEDDED_SCOPE,
                B12Field.READ_ERROR: EMPTY,
            }
        )
        evidence.status = B12_STATUS_COMPLETE
        evidence.primary_failure = EMPTY
        if not evidence.cases or any(
            case.get(B12Field.CLASSIFICATION) != B12_CLASS_VERIFIED for case in evidence.cases
        ):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_MEMORY_SNAPSHOT)
        upload_snapshot = asdict(evidence)
        upload_bytes = json.dumps(
            upload_snapshot, ensure_ascii=False, sort_keys=True, separators=B12_JSON_SEPARATORS
        ).encode(B12_UTF8)
        if (
            len(evidence.cases) != len(B12_CASES)
            or upload_snapshot.get(B12Field.STATUS) != B12_STATUS_COMPLETE
            or upload_snapshot.get(B12Field.SELECTED_AMENDMENT) != B12_AMENDMENT
            or evidence.carrier.get(B12Field.EMBEDDED_SHA256)
            != hashlib.sha256(embedded_b12_evidence_bytes(evidence)).hexdigest()
            or json.loads(upload_bytes) != upload_snapshot
        ):
            raise binding_failure(B12_ERROR_PREFIX + B12_DETAIL_UPLOAD_SNAPSHOT)
        observer.require_time()
        release_reason(B12_RETAIN_REASON.format(path=marker_path))
        observer.require_time()
    except Exception as error:
        _record_b12_failure(evidence, attempts_path, error, sanitize_text, started)
        raise
    except KeyboardInterrupt as error:
        _record_b12_failure(evidence, attempts_path, error, sanitize_text, started)
        raise
    finally:
        if not returned_to_source:
            try:
                leave_project(Observer(host), source_root)
            except Exception as return_error:
                detail = sanitize_text(
                    B12_EXCEPTION_DETAIL.format(error_class=type(return_error).__name__, detail=return_error)
                )
                evidence.evidence_failure = evidence.evidence_failure or detail
                if not evidence.primary_failure:
                    evidence.primary_failure = detail
                    evidence.status = B12_STATUS_UNPROVEN
                    raise platform_failure(B12_ERROR_PREFIX + detail) from return_error
