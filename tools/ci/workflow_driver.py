"""The evidence one platform-created preparation driver is held to, shared by the native B journeys.

For one driver session of one item (B1 steps 3, 4, 5 and 8 of the approved draft, amended for step 4's act rows by
`journeys/b1-instruction-act-pairs-amendment-draft.md` and for the title by `journeys/b1-driver-title-amendment-draft.md`,
base 8139046b, A1 d7270641, A2 f9a4d846): the session is the platform\'s and shows a real startup through
the installed hooks of the fixture\'s own launch; the driver\'s own fresh public claim call completes and returns the
instruction naming the item, phase, session, child procedure and each declared ending act with its phase; the item
shows the claim and exactly one claim note; closing the session releases the claim. Every observation is a public
command or one of the fixture\'s strict frames; this controller creates no record, identity or authentication state.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from tools.ci import workflow_creation as creation
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_ledger as ledger
from tools.ci import workflow_publication as publication
from tools.ci.workflow_foundation import FoundationHost

TELEC: Final = "bin/telec"
TODO: Final = "todo"
PREPARE: Final = "prepare"
ROLE: Final = "prepare-orchestrator"
PHASE: Final = "preparation"
CLAIM_FRAME: Final = "cmd_claim"
CLAIM_NAME: Final = "claim"
DRIVER_ID: Final = publication.DRIVER_ID

FIELD_OPERATION: Final = publication.FIELD_OPERATION
FIELD_STATE: Final = publication.FIELD_STATE
FIELD_ERROR: Final = publication.FIELD_ERROR
FIELD_RESULT: Final = publication.FIELD_RESULT
FIELD_ROLE: Final = "role"
FIELD_JOB: Final = "job"
FIELD_STANDING: Final = "standing"
FIELD_HELD_BY: Final = "held_by"
FIELD_HELD_SINCE: Final = "held_since"
FIELD_LOG: Final = "log"
STATE_COMPLETED: Final = publication.STATE_COMPLETED
STATE_FAILED: Final = publication.STATE_FAILED
TERMINAL_STATES: Final = publication.TERMINAL_STATES

DOCS_ROOT: Final = publication.DOCS_ROOT
LIVE_SUFFIX: Final = publication.LIVE_SUFFIX
CLAIM_HEADER_PREFIX: Final = "### "
CLAIM_HEADER_SUFFIX: Final = " · claim"
ACT_ROW: Final = re.compile(
    r"^- `telec todo act (?P<item>\S+) (?P<act>[a-z]+)(?P<arguments>[^`]*)` -> (?P<target>\S+)\s*$"
)
_CHILD_LINE = re.compile(r"^\s+child:\s*(?P<child>\S+)\s*$")
_ACT_LINE = re.compile(r"^\s+-\s+act:\s*(?P<act>\S+)\s*$")
_LEADS_LINE = re.compile(r"^\s+leads_to:\s*(?P<phase>\S+)\s*$")
_ACTS_KEY = re.compile(r"^\s+acts:\s*$")
_ROLE_LINE = re.compile(r"^role:\s*(?P<role>\S+)\s*$")

START_CAP_SECONDS: Final = 900.0
CLAIM_OPERATION_SECONDS: Final = 120.0
RELEASE_SECONDS: Final = 120.0
POLL_SECONDS: Final = 2.0
QUIESCENCE_GAP_SECONDS: Final = 2.0

DETAIL_SESSIONS: Final = "sessions beyond the baseline are {found!r}, not exactly {expected!r}"
DETAIL_RECORD_FIELD: Final = "the driver's record has {field} {found!r}, not {expected!r}"
DETAIL_MAPPING: Final = (
    "driver {session}: the record names native session {recorded!r}, but its pool directory launched {launched!r}"
)
DETAIL_RECORD_START: Final = "the driver's record does not show a completed startup: {record!r}"
DETAIL_FIRST_INPUT: Final = "the fixture's first input does not name {identity}: {text!r}"
DETAIL_CLAIM_FRAME: Final = "the fixture's claim frame is not the planned successful call: {frame!r}"
DETAIL_CLAIM_RECEIPT: Final = (
    "the driver's claim printed no distinct operation receipt: {stdout!r} (not one of {others})"
)
DETAIL_OPERATION_FAILED: Final = "operation {operation} failed: {error!r}"
DETAIL_RESULT_TYPE: Final = "operation {operation} result is not a string: {result!r}"
DETAIL_INSTRUCTION: Final = "the claim instruction does not contain {needle!r}: {text!r}"
DETAIL_ACT_ROW_ABSENT: Final = (
    "the instruction has no parseable row `telec todo act {item} {act}` -> {phase} "
    "(the shape changed, or the act is absent)"
)
DETAIL_ACT_ROW: Final = "the instruction associates `telec todo act {item} {act}` with {rows!r}, not {phase}"
DETAIL_HOLD: Final = "after the claim {path} is {found!r}, not {expected!r}"
DETAIL_PATH_ABSENT: Final = "the shown payload has no {path} (a source-traced path)"
DETAIL_LOG_CLAIMS: Final = "the log holds {count} claim entries, not exactly one: {log!r}"
DETAIL_LOG_ENTRY: Final = "the claim entry does not name {needle!r}: {entry!r}"
DETAIL_LOG_FORBIDDEN: Final = "a claim entry of the log names {session!r}, which holds nothing: {entry!r}"
DETAIL_RELEASE: Final = "the claim was not released within {seconds} seconds: {holder!r}"
DETAIL_TITLE: Final = "the driver's title is {found!r}, not {expected!r} (catalog role, one space, the item){diagnosis}"
DETAIL_TITLE_ABSENT: Final = "the driver's record has no `title` key (a source-traced field): {record!r}"
DETAIL_TITLE_MOVED: Final = "the driver's title changed before its end: first reading {first!r}, then {second!r}"
DETAIL_ROLE_UNREADABLE: Final = "the folded companion {path} declares no readable `role:`"
DIAGNOSIS_HOME_TOKEN: Final = "; the title ends with the activation's home token instead of the item"
DIAGNOSIS_NO_ITEM: Final = "; the title lacks the item"
DETAIL_COMPANION: Final = "the companion {path} has no readable workflow header"
DETAIL_NOT_QUIESCENT: Final = "the item is being written by something else; differing paths: {paths}"

type Json = Mapping[str, object]


def declared_acts(
    path: Path, evidence: list[creation.EvidenceValue] | None = None
) -> tuple[list[tuple[str, str]], str]:
    """The ending acts with their phases, and the child procedure, the folded driver\'s `workflow` header declares.

    The header is the YAML block between the first two `---` lines; only the `workflow:` mapping is read, line by line,
    because the hosted harness runs on the standard library alone.
    """
    source = path.read_text(encoding="utf-8")
    if evidence is not None:
        evidence.append({"kind": "workflow", "path": str(path), "text": source})
    return parse_declared_acts(source, path)


def parse_declared_acts(source: str, path: Path) -> tuple[list[tuple[str, str]], str]:
    """Apply the original workflow header parser to already-read text; path is diagnostic only."""
    parts = source.split("---", 2)
    lines = parts[1].splitlines() if len(parts) >= 3 else []
    start = next((index for index, line in enumerate(lines) if line.rstrip() == "workflow:"), None)
    if start is None:
        raise creation.binding_failure(DETAIL_COMPANION.format(path=path))
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith(" "):
            break
        block.append(line)
    child = next((m.group("child") for m in map(_CHILD_LINE.match, block) if m), None)
    acts_at = next((index for index, line in enumerate(block) if _ACTS_KEY.match(line)), None)
    if child is None or acts_at is None:
        raise creation.binding_failure(DETAIL_COMPANION.format(path=path))
    names: list[str] = []
    phases: list[str] = []
    for line in block[acts_at + 1 :]:
        if (act := _ACT_LINE.match(line)) is not None:
            names.append(act.group("act"))
        elif (leads := _LEADS_LINE.match(line)) is not None:
            phases.append(leads.group("phase"))
        elif line.strip() and not line.lstrip().startswith("-"):
            break
    if not names or len(names) != len(phases):
        raise creation.binding_failure(DETAIL_COMPANION.format(path=path))
    return list(zip(names, phases, strict=True)), child


def declared_role(path: Path, evidence: list[creation.EvidenceValue] | None = None) -> str:
    """The `role:` the folded driver's header declares, read line by line from its first `---` block."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise creation.trace_failure(DETAIL_ROLE_UNREADABLE.format(path=path)) from error
    if evidence is not None:
        evidence.append({"kind": "role", "path": str(path), "text": source})
    return parse_declared_role(source, path)


def parse_declared_role(source: str, path: Path) -> str:
    """Apply the original role header parser to already-read text; path is diagnostic only."""
    parts = source.split("---", 2)
    lines = parts[1].splitlines() if len(parts) >= 3 else []
    role = next((m.group("role") for m in map(_ROLE_LINE.match, lines) if m), None)
    if role is None:
        raise creation.trace_failure(DETAIL_ROLE_UNREADABLE.format(path=path))
    return role


def claim_entries(log: str) -> list[tuple[str, str]]:
    """The claim entries of a log as (header line, the body line after one blank line)."""
    lines = log.replace("\r\n", "\n").split("\n")
    entries: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        if line.startswith(CLAIM_HEADER_PREFIX) and (
            line.rstrip().endswith(CLAIM_HEADER_SUFFIX) or f"{CLAIM_HEADER_SUFFIX} (" in line
        ):
            body = lines[index + 2] if index + 2 < len(lines) and not lines[index + 1].strip() else ""
            entries.append((line, body))
    return entries


def shown_with_content(observer: creation.Observer, item: str) -> Json:
    """The shown payload of the item with its artifact content; an absent item is a platform failure."""
    shown = observer.show(item)
    if shown is None:
        raise creation.platform_failure(f"{item} is absent")
    return shown


def fresh_snapshot(observer: creation.Observer, item: str) -> Json:
    """Two reads of the item at least two seconds apart, deeply equal: nothing else is writing it."""
    first = shown_with_content(observer, item)
    time.sleep(QUIESCENCE_GAP_SECONDS)
    second = shown_with_content(observer, item)
    changed = creation.differences(first, second)
    if changed:
        raise creation.binding_failure(DETAIL_NOT_QUIESCENT.format(paths=changed))
    return second


receipt_operation = publication.receipt_operation


begin_attempt = publication.begin_attempt
settle_attempt = publication.settle_attempt
start_call = publication.start_call
release_attempt = publication.release_attempt


def driver_inputs(
    accounting: creation.EvidenceObject | None, name: str, slot: int, procedure: str, verb: str, phase: str
) -> ledger.JsonObject | None:
    """Retain the existing early driver's actual startup and claim inputs, without another invocation."""
    if accounting is None:
        return None
    record: ledger.JsonObject = {
        "name": name,
        "slot": slot,
        "procedure": procedure,
        "verb": verb,
        "phase": phase,
        "startup": {
            "started_ns": None,
            "observed_ns": None,
            "session_id": None,
            "expected_new": [],
            "list": [],
            "launch": None,
            "owned_executable": None,
            "hooks": [],
            "record": None,
            "declared_role": None,
            "inputs": None,
        },
        "instruction": None,
        "claim_context": None,
        "declarations": [],
        "claim": {
            "started_ns": None,
            "returned_ns": None,
            "observed_ns": None,
            "frame": None,
            "terminal": None,
            "held": None,
            "distinct_from": None,
        },
    }
    cast(list[creation.EvidenceValue], accounting["drivers"]).append(record)
    return record


def effect_inputs(
    accounting: creation.EvidenceObject | None, name: str, actor: str | None
) -> creation.EvidenceObject | None:
    """Retain original effect observations in the admitted early case."""
    if accounting is None:
        return None
    packet: creation.EvidenceObject = {
        "name": name,
        "actor": actor,
        "started_ns": time.monotonic_ns(),
        "finished_ns": None,
        "frames": [],
        "shown": [],
        "session_reads": [],
    }
    cast(list[creation.EvidenceValue], accounting["effects"]).append(packet)
    return packet


def actor_inputs(accounting: creation.EvidenceObject | None, name: str, slot: int) -> ledger.JsonObject | None:
    """Retain the original non-driver actor's specific start and identity observations."""
    if accounting is None:
        return None
    record: ledger.JsonObject = {
        "name": name,
        "slot": slot,
        "started_ns": time.monotonic_ns(),
        "finished_ns": None,
        "session_id": None,
        "message": None,
        "parent_actor": None,
        "expected_principal": None,
        "launch": None,
        "hooks": [],
        "inputs": None,
        "startup_record": None,
        "fact_record": None,
        "parent_record": None,
        "start_command": None,
        "start_frame": None,
        "positive_start": [],
        "lists": [],
    }
    cast(list[creation.EvidenceValue], accounting["actors"]).append(record)
    return record


def assert_instruction(
    item: str, phase: str, session: str, instruction: str, acts: Sequence[tuple[str, str]], child: str
) -> None:
    """Apply the original instruction/ending-act predicates to already captured inputs, without a doc read."""
    for needle in (item, phase, session, child):
        if needle not in instruction:
            raise creation.platform_failure(DETAIL_INSTRUCTION.format(needle=needle, text=instruction[-600:]))
    rows = [match for match in map(ACT_ROW.match, instruction.split("\n")) if match is not None]
    for act, phase in acts:
        targets = [row.group("target") for row in rows if row.group("item") == item and row.group("act") == act]
        if not targets:
            raise creation.trace_failure(DETAIL_ACT_ROW_ABSENT.format(item=item, act=act, phase=phase))
        if any(target != phase for target in targets):
            raise creation.platform_failure(
                DETAIL_ACT_ROW.format(item=item, act=act, phase=phase, rows=sorted(set(targets)))
            )


def assert_claim_observation(
    item: str,
    phase: str,
    session: str,
    held: Json,
    holds_nothing: Sequence[str],
    earlier: Sequence[str],
    known_entries: int,
) -> None:
    """Apply the original public claim/log predicates to already captured inputs, without a public read."""
    creation.require_value(item, held, "state.active_runner", session)
    creation.require_value(item, held, f"{FIELD_STANDING}.{FIELD_HELD_BY}", session)
    found, since = creation.dig(held, f"{FIELD_STANDING}.{FIELD_HELD_SINCE}")
    if not found:
        raise creation.trace_failure(DETAIL_PATH_ABSENT.format(path=f"{FIELD_STANDING}.{FIELD_HELD_SINCE}"))
    if not isinstance(since, str) or not since:
        raise creation.platform_failure(
            DETAIL_HOLD.format(path="standing.held_since", found=since, expected="non-empty")
        )
    creation.require_value(item, held, "state.lifecycle_phase", phase)
    creation.require_value(item, held, f"{FIELD_STANDING}.phase", phase)
    creation.require_value(item, held, "state.hold", False)
    _, log = creation.dig(held, f"artifact_content.{FIELD_LOG}")
    if not isinstance(log, str):
        raise creation.trace_failure(DETAIL_PATH_ABSENT.format(path=f"artifact_content.{FIELD_LOG}"))
    entries = claim_entries(log)
    if len(entries) != known_entries + len(earlier) + 1:
        raise creation.platform_failure(DETAIL_LOG_CLAIMS.format(count=len(entries), log=log[-600:]))
    for previous, (earlier_header, _) in zip(earlier, entries, strict=False):
        if previous not in earlier_header:
            raise creation.platform_failure(DETAIL_LOG_ENTRY.format(needle=previous, entry=earlier_header))
    header, body = entries[-1]
    if session not in header:
        raise creation.platform_failure(DETAIL_LOG_ENTRY.format(needle=session, entry=header))
    for needle in (item, session):
        if needle not in body:
            raise creation.platform_failure(DETAIL_LOG_ENTRY.format(needle=needle, entry=body))
    for other in holds_nothing:
        if any(other in held_header or other in held_body for held_header, held_body in entries):
            raise creation.platform_failure(DETAIL_LOG_FORBIDDEN.format(session=other, entry=header))


class DriverCase:
    """The evidence of one driver session of one item."""

    def __init__(
        self,
        *,
        host: FoundationHost,
        observer: creation.Observer,
        journey: foundation.Journey,
        item: str,
        launch_setup: foundation.FixtureSetup,
        clone: Path,
        baseline: creation.SessionView,
        driver_id: str = DRIVER_ID,
        verb: str = PREPARE,
        phase: str = PHASE,
        claim_evidence: ledger.JsonObject | None = None,
        case_evidence: ledger.JsonObject | None = None,
    ) -> None:
        self.driver_id = driver_id
        self.phase = phase
        self.host = host
        self.observer = observer
        self.journey = journey
        self.item = item
        self.launch_setup = launch_setup
        self.clone = clone
        self.baseline = baseline
        self.claim_argv = ("telec", TODO, verb, item)
        self.titles: dict[str, str] = {}
        self.case_evidence = case_evidence
        self.claim_evidence = (
            claim_evidence
            if claim_evidence is not None
            else (cast(ledger.JsonObject, case_evidence["claim"]) if case_evidence is not None else None)
        )

    def check_startup(self, session: str, expected_new: frozenset[str]) -> str:
        """The sessions beyond the baseline are exactly those expected; the driver\'s startup is real; returns its native id."""
        evidence = cast(ledger.JsonObject, self.case_evidence["startup"]) if self.case_evidence is not None else None
        if evidence is not None:
            evidence.update(
                {"started_ns": time.monotonic_ns(), "session_id": session, "expected_new": list(sorted(expected_new))}
            )
        created = (
            self.observer.sessions(
                evidence=cast(list[creation.EvidenceValue], evidence["list"]) if evidence is not None else None
            ).ids
            - self.baseline.ids
        )
        if created != expected_new:
            raise creation.platform_failure(
                DETAIL_SESSIONS.format(found=sorted(created), expected=sorted(expected_new))
            )
        journey = self.journey
        journey.session_id = session
        launch = journey.await_json(self.launch_setup.control / foundation.LAUNCH_FILE, foundation.POLL_SECONDS * 30)
        owned = str(self.launch_setup.executable.resolve())
        if evidence is not None:
            evidence["launch"] = cast(ledger.JsonValue, dict(launch))
            evidence["owned_executable"] = owned
        found = (Path(str(launch.get("executable"))).resolve(), Path(str(launch.get("resolved_command"))).resolve())
        if found != (Path(owned), Path(owned)):
            raise creation.binding_failure(foundation.DETAIL_EXECUTABLE.format(found=launch, owned=owned))
        native = str(launch.get("native_session_id"))
        frames_deadline = time.monotonic() + START_CAP_SECONDS
        for name in (foundation.FRAME_SESSION_START, foundation.FRAME_PROMPT_SUBMIT):
            frame = journey.await_frame(name, frames_deadline)
            if evidence is not None:
                cast(list[ledger.JsonValue], evidence["hooks"]).append(
                    {"name": name, "frame": cast(ledger.JsonValue, dict(frame))}
                )
            journey.require_hook(name, frame)
        record = journey.record()
        if evidence is not None:
            evidence["record"] = cast(ledger.JsonValue, dict(record)) if record is not None else None
        recorded = record.get(foundation.FIELD_NATIVE) if record is not None else None
        if isinstance(recorded, str) and recorded and recorded != native:
            raise creation.binding_failure(DETAIL_MAPPING.format(session=session, recorded=recorded, launched=native))
        if record is None or not journey.started(record, native):
            raise creation.platform_failure(DETAIL_RECORD_START.format(record=record))
        role = declared_role(
            self.clone / DOCS_ROOT / f"{self.driver_id}{LIVE_SUFFIX}",
            cast(list[creation.EvidenceValue], self.case_evidence["declarations"]) if self.case_evidence else None,
        )
        if evidence is not None:
            evidence["declared_role"] = role
        for field, expected in ((FIELD_ROLE, role), (FIELD_JOB, self.driver_id)):
            if record.get(field) != expected:
                raise creation.platform_failure(
                    DETAIL_RECORD_FIELD.format(field=field, found=record.get(field), expected=expected)
                )
        self.titles[session] = self.require_title(record, role)
        inputs = journey.inputs()
        if evidence is not None:
            evidence["inputs"] = cast(ledger.JsonValue, inputs)
        first = inputs[0].get("text") if inputs else None
        if not isinstance(first, str) or self.driver_id not in first:
            raise creation.platform_failure(DETAIL_FIRST_INPUT.format(identity=self.driver_id, text=first))
        if evidence is not None:
            evidence["observed_ns"] = time.monotonic_ns()
        return native

    def require_title(self, record: Json, role: str) -> str:
        """Amendment A2: the title is the folded catalog role, one ASCII space and the item, byte for byte."""
        if "title" not in record:
            raise creation.trace_failure(DETAIL_TITLE_ABSENT.format(record=dict(record)))
        title = record["title"]
        expected = f"{role} {self.item}"
        if title != expected:
            diagnosis = ""
            if isinstance(title, str) and self.item not in title:
                diagnosis = DIAGNOSIS_HOME_TOKEN if title.startswith(f"{role} ") else DIAGNOSIS_NO_ITEM
            raise creation.platform_failure(DETAIL_TITLE.format(found=title, expected=expected, diagnosis=diagnosis))
        return expected

    def require_title_stable(self, session: str) -> None:
        """A2-2: read again just before the driver ends; the title equals the first reading."""
        first = self.titles.get(session)
        record = self.journey.record()
        if first is None or record is None or "title" not in record:
            raise creation.trace_failure(DETAIL_TITLE_ABSENT.format(record=record))
        if record["title"] != first:
            raise creation.platform_failure(DETAIL_TITLE_MOVED.format(first=first, second=record["title"]))

    def claim_call(self, distinct_from: Sequence[str]) -> str:
        """The driver\'s own claim, run in its pane, completes and returns the instruction text."""
        if self.claim_evidence is not None:
            self.claim_evidence["started_ns"] = time.monotonic_ns()
            if self.case_evidence is not None:
                self.claim_evidence["distinct_from"] = list(distinct_from)
        frame = self.journey.await_frame(CLAIM_FRAME, time.monotonic() + CLAIM_OPERATION_SECONDS)
        if self.claim_evidence is not None:
            self.claim_evidence["frame"] = cast(ledger.JsonValue, dict(frame))
        run = frame.get("run")
        argv = frame.get("argv")
        stdout = run.get("stdout") if isinstance(run, dict) else None
        operation = receipt_operation(stdout) if isinstance(stdout, str) else None
        if (
            not isinstance(run, dict)
            or run.get("exit_status") != 0
            or run.get("timed_out") is True
            or not isinstance(argv, list)
            or tuple(argv) != self.claim_argv
        ):
            raise creation.platform_failure(DETAIL_CLAIM_FRAME.format(frame=frame))
        if operation is None or operation in distinct_from:
            raise creation.platform_failure(DETAIL_CLAIM_RECEIPT.format(stdout=stdout, others=list(distinct_from)))
        claimed = publication.await_terminal(self.observer, operation, CLAIM_OPERATION_SECONDS)
        if self.claim_evidence is not None:
            self.claim_evidence["terminal"] = cast(ledger.JsonValue, dict(claimed))
            self.claim_evidence["returned_ns"] = time.monotonic_ns()
        if claimed.get(FIELD_STATE) != STATE_COMPLETED:
            raise creation.platform_failure(
                DETAIL_OPERATION_FAILED.format(operation=operation, error=claimed.get(FIELD_ERROR))
            )
        instruction = claimed.get(FIELD_RESULT)
        if not isinstance(instruction, str):
            raise creation.platform_failure(DETAIL_RESULT_TYPE.format(operation=operation, result=instruction))
        return instruction

    def check_instruction(self, session: str, instruction: str) -> None:
        """The item, phase, session, child procedure and each declared ending act with its phase (amendment A1)."""
        acts, child = declared_acts(
            self.clone / DOCS_ROOT / f"{self.driver_id}{LIVE_SUFFIX}",
            cast(list[creation.EvidenceValue], self.case_evidence["declarations"]) if self.case_evidence else None,
        )
        if self.case_evidence is not None:
            self.case_evidence["instruction"] = {
                "session_id": session,
                "text": instruction,
                "child": child,
                "acts": [list[ledger.JsonValue](row) for row in acts],
            }
        assert_instruction(self.item, self.phase, session, instruction, acts, child)

    def observe_claim(
        self,
        session: str,
        holds_nothing: Sequence[str] = (),
        earlier: Sequence[str] = (),
        known_entries: int = 0,
    ) -> None:
        """The item shows the holder, the phase and one claim note per claim, the last naming the session and no other.

        ``earlier`` names the sessions of the item\'s earlier claims in order; each owns exactly one claim note before.
        """
        item = self.item
        held = shown_with_content(self.observer, item)
        if self.claim_evidence is not None:
            self.claim_evidence["held"] = cast(ledger.JsonValue, dict(held))
            self.claim_evidence["observed_ns"] = time.monotonic_ns()
        if self.case_evidence is not None:
            self.case_evidence["claim_context"] = {
                "session_id": session,
                "known_entries": known_entries,
                "earlier": list(earlier),
                "holds_nothing": list(holds_nothing),
            }
        assert_claim_observation(item, self.phase, session, held, holds_nothing, earlier, known_entries)

    def close(self, session: str) -> None:
        """Ending the session releases the claim and leaves the phase unchanged."""
        self.journey.session_id = session
        self.require_title_stable(session)
        self.journey.end_session()
        deadline = time.monotonic() + RELEASE_SECONDS
        holder: object = session
        while time.monotonic() < deadline:
            released = self.observer.show(self.item, retain=False)
            holder = creation.dig(released, "state.active_runner")[1] if released is not None else holder
            if holder in (None, ""):
                break
            time.sleep(POLL_SECONDS)
        else:
            raise creation.platform_failure(DETAIL_RELEASE.format(seconds=int(RELEASE_SECONDS), holder=holder))
        creation.require_value(
            self.item, shown_with_content(self.observer, self.item), "state.lifecycle_phase", self.phase
        )
