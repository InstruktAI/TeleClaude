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

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

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
CREATED_PHRASE: Final = "Created todo: {slug}"
CREATED_PREFIX: Final = "Created todo:"
INPUT_ARTIFACT: Final = "input"
INPUT_BODY: Final = "# {slug} — Input\n\n{content}\n"
NOT_FOUND_PHRASE: Final = "slug '{slug}' not found in todo list"
MACHINE_OWNED_PHRASE: Final = "--build-started is machine-owned"
DOOR_SENTENCE: Final = "none needed: the item is in preparation, which `telec todo prepare {slug}` drives"
REPLACEMENT_MARKER: Final = "The act that replaces it is"
PERFORMER_MARKER: Final = "performed by"
HOLDING_DRIVER: Final = "the holding driver"
GATE_SIGNATURES: Final = (
    "permission denied",
    "login required",
    "unknown command path or missing command authorization",
    "human principal required",
    "cwd required",
    "missing stamp flag",
    "usage:",
    "unknown caller",
    "not found in todo list",
)

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
DETAIL_CONTROL_SIGNATURE: Final = "the clearance control printed a signature of another gate {signature!r}: {output!r}"
DETAIL_CONTROL_TEXT: Final = "the clearance control did not print {phrase!r} and no gate signature: {output!r}"
DETAIL_CONTROL_EXIT: Final = "the clearance control exited {status}, not non-zero: {output!r}"
DETAIL_CASE_EXIT: Final = "{case}: the retired act exited {status}, not non-zero, with output {output!r}"
DETAIL_GATE_REACHED: Final = "{case}: the output carries the gate signature {signature!r}: {output!r}"
DETAIL_CASE_DOOR: Final = "{case}: the refusal does not carry the door sentence {sentence!r}: {output!r}"
DETAIL_CASE_REPLACEMENT: Final = "{case}: the refusal names a replacing act through {marker!r}: {output!r}"
DETAIL_CASE_PERFORMER: Final = "{case}: the refusal does not name {phrase!r}: {output!r}"
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


class Observer:
    """The approved observation primitives O1-O3, each a fresh public CLI process on the owner terminal."""

    def __init__(self, host: FoundationHost) -> None:
        self.host = host

    def run(self, argv: Sequence[str], *, retain: bool = True) -> Outcome:
        return self.host.cli(argv, CLI_TIMEOUT_SECONDS, retain=retain)

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

    def sessions(self, *, retain: bool = True) -> SessionView:
        """O3: every session, unattended procedure agents and closed ones included."""
        outcome = self.run((TELEC, SESSIONS, LIST, ALL_FLAG, CLOSED_FLAG), retain=retain)
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


def _absence_window(observer: Observer, baseline: SessionView, slugs: Sequence[str]) -> None:
    """R1 step 5: no session appears in the window, and none works on any of the journey's items."""
    deadline = time.monotonic() + ABSENCE_WINDOW_SECONDS
    while True:
        now = observer.sessions(retain=False)
        require_sessions_equal(baseline, now, "inside the absence window")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(ABSENCE_POLL_SECONDS, remaining))
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
        _absence_window(observer, baseline, journey_slugs)
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


def _signature_in(output: str) -> str | None:
    lowered = normalized(output).lower()
    return next((signature for signature in GATE_SIGNATURES if signature in lowered), None)


def _quiescent_item(observer: Observer) -> Mapping[str, object]:
    """P4 and P5: the item sits in the tested table row and two reads, apart, are deeply equal."""
    first = observer.show(SLUG_FEATURE)
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
    time.sleep(QUIESCENCE_GAP_SECONDS)
    second = observer.show(SLUG_FEATURE)
    if second is None or differences(first, second):
        paths = differences(first, second) if second is not None else ["absent"]
        raise binding_failure(DETAIL_NOT_QUIESCENT.format(paths=paths))
    return second


def _control_clearance(observer: Observer) -> None:
    """C0: the owner passes the stamp gate and meets the CLI's own machine-owned refusal, touching nothing."""
    outcome = _stamp(observer, SLUG_FEATURE, BUILD_STARTED_FLAG)
    signature = _signature_in(outcome.output)
    if signature is not None:
        raise fail(CLASS_GATE, DETAIL_CONTROL_SIGNATURE.format(signature=signature, output=outcome.output[-300:]))
    if MACHINE_OWNED_PHRASE not in normalized(outcome.output):
        raise trace_failure(DETAIL_CONTROL_TEXT.format(phrase=MACHINE_OWNED_PHRASE, output=outcome.output[-300:]))
    if outcome.exit_status in (0, None):
        raise platform_failure(DETAIL_CONTROL_EXIT.format(status=outcome.exit_status, output=outcome.output[-300:]))


def _check_refusal(case: str, outcome: Outcome, *, performer: bool) -> None:
    text = normalized(outcome.output)
    if outcome.exit_status in (0, None):
        raise platform_failure(
            DETAIL_CASE_EXIT.format(case=case, status=outcome.exit_status, output=outcome.output[-300:])
        )
    signature = _signature_in(outcome.output)
    if signature is not None:
        raise fail(CLASS_GATE, DETAIL_GATE_REACHED.format(case=case, signature=signature, output=outcome.output[-300:]))
    sentence = DOOR_SENTENCE.format(slug=SLUG_FEATURE)
    if sentence not in text:
        raise fail(CLASS_GATE, DETAIL_CASE_DOOR.format(case=case, sentence=sentence, output=outcome.output[-300:]))
    if performer:
        if HOLDING_DRIVER not in text:
            raise platform_failure(
                DETAIL_CASE_PERFORMER.format(case=case, phrase=HOLDING_DRIVER, output=outcome.output[-300:])
            )
        return
    for marker in (REPLACEMENT_MARKER, PERFORMER_MARKER):
        if marker in text:
            raise platform_failure(
                DETAIL_CASE_REPLACEMENT.format(case=case, marker=marker, output=outcome.output[-300:])
            )


def _require_nothing_written(
    observer: Observer, case: str, before: Mapping[str, object], sessions: SessionView, slugs: set[str]
) -> None:
    """After a refusal: the item, the sessions and the slugs are exactly as before, now and after a pause."""
    for when, pause in (("immediately", 0.0), ("five seconds later", SETTLE_SECONDS)):
        if pause:
            time.sleep(pause)
        after = observer.show(SLUG_FEATURE)
        if after is None:
            raise platform_failure(DETAIL_WRITE_LANDED.format(case=case, when=when, paths=["absent"]))
        changed = differences(before, after)
        if changed:
            raise platform_failure(DETAIL_WRITE_LANDED.format(case=case, when=when, paths=changed))
        require_sessions_equal(sessions, observer.sessions(retain=False), when)
    now = observer.slugs(retain=False)
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
            (CASE_PRD, (PRD_APPROVED_FLAG,), False),
            (CASE_KICKBACK, (KICKBACK_FLAG, REASON_OPTION, KICKBACK_REASON), True),
        )
        for case, flags, performer in cases:
            before = _quiescent_item(observer)
            sessions = observer.sessions()
            slugs = observer.slugs()
            _check_refusal(case, _stamp(observer, SLUG_FEATURE, *flags), performer=performer)
            _require_nothing_written(observer, case, before, sessions, slugs)
    finally:
        leave_project(observer, source_root)
