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

It proves no event, no stored waited phase, no prepared/work/ready/delivery, no racing decisions and no model
following; the order of the child\'s end and the claim\'s release inside the act is a source-review obligation. This
controller creates no session record, role, reservation, identity or authentication state, reads no private store and
imports no application module. Identity limit: the client carries the session context (same-computer, client-asserted).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_foundation as foundation
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
HEADER_PREFIX: Final = "### "

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


def log_entries(log: str) -> list[tuple[str, str]]:
    """The section headers of a log as (header line, the first non-blank text line after it)."""
    lines = log.replace("\r\n", "\n").split("\n")
    entries: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        if line.startswith(HEADER_PREFIX):
            text = next((later.strip() for later in lines[index + 1 :] if later.strip()), "")
            entries.append((line, text))
    return entries


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
    ) -> None:
        self.host = host
        self.retain = retain
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

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _known(self, *sessions: str) -> frozenset[str]:
        assert self.baseline is not None
        return self.baseline.ids | frozenset(sessions)

    def _journey(self, name: str, index: int) -> foundation.Journey:
        journey = foundation.Journey(self.host, self.setups[index], self.project, self.owner_email)
        self.journeys[name] = journey
        return journey

    def _gate(self, index: int, name: str) -> None:
        (self.setups[index].control / name).write_text("1\n", encoding="utf-8")

    def _late_argv(self, index: int, name: str, argv: list[str]) -> None:
        try:
            (self.setups[index].control / name).write_text(json.dumps(argv), encoding="utf-8")
        except OSError as error:
            raise creation.binding_failure(DETAIL_LATE_ARGV.format(name=name, error=type(error).__name__)) from error

    def _record(self, session: str) -> Json:
        outcome = self.observer.run((TELEC, SESSIONS, foundation.SHOW, session, foundation.FULL_FLAG), retain=False)
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        if record is None:
            raise creation.binding_failure(f"session {session} is unreadable: {outcome.output[-300:]!r}")
        return record

    def _frame(self, journey: foundation.Journey, name: str) -> Json:
        """A completed frame of one actor, with its public call and its output."""
        frame = journey.await_frame(name, time.monotonic() + FRAME_SECONDS)
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
            time.sleep(POLL_SECONDS)
        raise creation.platform_failure(DETAIL_SESSIONS.format(when="discovery", found=found, expected="one"))

    def _startup(self, actor: str, session: str, journey: foundation.Journey, index: int) -> None:
        """F0 startup evidence for a session another actor started: active, observed, the launch\'s native id."""
        journey.session_id = session
        launch = journey.await_json(self.setups[index].control / foundation.LAUNCH_FILE, LAUNCH_SECONDS)
        native = str(launch.get("native_session_id"))
        deadline = time.monotonic() + START_CAP_SECONDS
        record: Json | None = None
        while time.monotonic() < deadline:
            record = journey.record(retain=False)
            if journey.started(record, native):
                return
            recorded = record.get(foundation.FIELD_NATIVE) if record is not None else None
            if isinstance(recorded, str) and recorded and recorded != native:
                raise creation.binding_failure(
                    DETAIL_MAPPING.format(actor=actor, session=session, recorded=recorded, launched=native)
                )
            time.sleep(POLL_SECONDS)
        raise creation.platform_failure(
            DETAIL_NOT_STARTED.format(actor=actor, session=session, seconds=int(START_CAP_SECONDS), record=record)
        )

    def _shown(self) -> Json:
        return driver.shown_with_content(self.observer, ITEM)

    def _log(self) -> str:
        _, log = creation.dig(self._shown(), "artifact_content.log")
        return str(log) if isinstance(log, str) else ""

    def _require_unchanged(self, when: str) -> None:
        changed = creation.differences(self.snapshot, self._shown())
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
        attempt = driver.begin_attempt(self.starts, "session-owner")
        started = journey.start_session()
        owner = journey.session_id
        driver.release_attempt(self.starts, attempt)  # the public answer named the session; settlement closes it
        journey.positive_start(started)
        record = self._record(owner)
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
        created = self.observer.sessions().ids - self._known()
        if created != frozenset({owner}):
            raise creation.platform_failure(
                DETAIL_SESSIONS.format(when="step 1", found=sorted(created), expected=[owner])
            )
        return owner

    def step2_first_driver(self, owner: str) -> tuple[driver.DriverCase, str, str]:
        child_attempt = driver.begin_attempt(self.starts, "session-child")  # the driver\'s plan starts it unsupervised
        outcome, starter = driver.start_call(self.starts, self.observer, (TELEC, TODO, "prepare", ITEM), "start")
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
        frame = self._frame(self.journeys["first"], FRAME_CHILD)
        status, text = self._output(frame)
        started = STARTED_CHILD.search(text)
        if status != 0 or started is None or started.group("procedure") != CHILD_PROCEDURE:
            raise creation.platform_failure(DETAIL_CHILD.format(stdout=text[-300:], procedure=CHILD_PROCEDURE))
        child = started.group("session")
        driver.release_attempt(self.starts, child_attempt)
        child_journey = self._journey("child", 2)
        self._startup("child", child, child_journey, 2)
        record = self._record(child)
        for field, expected in ((FIELD_ROLE, CHILD_ROLE), (FIELD_INITIATOR, first)):
            if record.get(field) != expected:
                raise creation.platform_failure(
                    DETAIL_CHILD_RECORD.format(session=child, field=field, found=record.get(field), expected=expected)
                )
        self._require_pool(3)
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
        )

    def step3_before_waiting(self, first: str, child: str) -> None:
        record = self._record(child)
        if record.get(FIELD_CLOSED_AT) is not None or record.get(foundation.FIELD_LIFECYCLE) != foundation.ACTIVE:
            raise creation.platform_failure(
                DETAIL_LIVE.format(actor="child", session=child, when="before waiting", record=record)
            )
        creation.require_value(ITEM, self._shown(), "state.active_runner", first)

    def step4_wait(self, first: str, child: str) -> None:
        self._gate(1, GATE_WAITING)
        frame = self._frame(self.journeys["first"], FRAME_WAITING)
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
        shown = self._shown()
        for path, expected in (
            ("state.lifecycle_phase", PHASE_WAITING),
            ("standing.phase", PHASE_WAITING),
            ("standing.waiting_on", self.person),
        ):
            creation.require_value(ITEM, shown, path, expected)
        creation.require_unclaimed(ITEM, shown)
        record = self._record(child)
        if record.get(FIELD_CLOSED_AT) is None or record.get(FIELD_LIFECYCLE) != foundation.CLOSED:
            raise creation.platform_failure(
                DETAIL_CLOSED.format(actor="child", session=child, when="after waiting", record=record)
            )
        if self._record(first).get(FIELD_CLOSED_AT) is not None:
            raise creation.binding_failure(
                DETAIL_LIVE.format(actor="first driver", session=first, when="after waiting", record="closed")
            )
        entries = [entry for entry in log_entries(self._log()) if f" · waiting ({self.person})" in entry[0]]
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
        self.snapshot = self._shown()

    def step5_entry_refused(self, owner: str, first: str, child: str) -> None:
        outcome, operation = driver.start_call(
            self.starts, self.observer, (TELEC, TODO, "prepare", ITEM), "refused-start"
        )
        if outcome.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        state = publication.await_terminal(self.observer, operation, OPERATION_SECONDS)
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
        created = self.observer.sessions().ids - self._known()
        if created != frozenset({owner, first, child}):
            raise creation.platform_failure(
                DETAIL_SESSIONS.format(when="step 5", found=sorted(created), expected=[owner, first, child])
            )
        self._require_unchanged("after the refused entry")

    def step6_dispatched(self, owner: str, first: str, child: str) -> str:
        dispatch_attempt = driver.begin_attempt(self.starts, "session-dispatched")
        self._gate(0, GATE_DISPATCH)
        frame = self._frame(self.journeys["owner"], FRAME_DISPATCH)
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
        journey = self._journey("dispatched", 3)
        self._startup("dispatched", dispatched, journey, 3)
        self._require_pool(4)
        record = self._record(dispatched)
        owner_record = self._record(owner)
        facts = {FIELD_INITIATOR: record.get(FIELD_INITIATOR), FIELD_PRINCIPAL: record.get(FIELD_PRINCIPAL)}
        expected = {FIELD_INITIATOR: owner, FIELD_PRINCIPAL: owner_record.get(FIELD_PRINCIPAL)}
        if facts != expected:
            raise creation.binding_failure(
                DETAIL_FACTS.format(actor="dispatched session", session=dispatched, found=facts, expected=expected)
            )
        self._late_argv(
            3, ARGV_REFUSED, ["telec", TODO, "act", ITEM, "decision", "--wait", self.key, ANSWER_DISPATCHED]
        )
        refused_attempt = driver.begin_attempt(self.starts, "decision-dispatched")
        self._gate(3, GATE_REFUSED)
        refusal = self._frame(journey, FRAME_REFUSED)
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
        self._require_unchanged("after the refused decision")
        if any(" · decision (" in header for header, _ in log_entries(self._log())):
            raise creation.platform_failure(
                DETAIL_LOG.format(
                    when="after the refused decision", needle="no decision header", log=self._log()[-600:]
                )
            )
        driver.release_attempt(self.starts, refused_attempt)  # refused, nothing cleared, no driver reserved
        self._gate(3, GATE_NOTE)
        noted = self._frame(journey, FRAME_NOTE)
        status, text = self._output(noted)
        if status != 0 or PERFORMED.format(act="note", item=ITEM) not in text:
            raise creation.platform_failure(DETAIL_FRAME.format(name=FRAME_NOTE, frame=noted))
        entries = log_entries(self._log())
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
        creation.require_value(ITEM, self._shown(), "state.lifecycle_phase", PHASE_WAITING)
        return dispatched

    def step7_end_first(self, case: driver.DriverCase, first: str) -> None:
        case.require_title_stable(first)
        journey = self.journeys["first"]
        journey.session_id = first
        journey.end_session()

    def step8_decide(self, owner: str) -> None:
        self._late_argv(0, ARGV_DECISION, ["telec", TODO, "act", ITEM, "decision", "--wait", self.key, ANSWER])
        self.decision_attempt = driver.begin_attempt(self.starts, "decision-owner")
        self._gate(0, GATE_DECISION)
        frame = self._frame(self.journeys["owner"], FRAME_DECISION)
        status, text = self._output(frame)
        if status != 0 or PERFORMED.format(act="decision", item=ITEM) not in text:
            raise creation.platform_failure(DETAIL_FRAME.format(name=FRAME_DECISION, frame=frame))
        decisions = [entry for entry in log_entries(self._log()) if f" · decision ({self.person})" in entry[0]]
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
        shown = self._shown()
        creation.require_value(ITEM, shown, "state.lifecycle_phase", PHASE_PREPARATION)
        found, standing = creation.dig(shown, "standing")
        if found and isinstance(standing, Mapping) and "waiting_on" in standing:
            raise creation.platform_failure(
                DETAIL_SHOWN.format(
                    when="after the decision", path="standing.waiting_on", found="present", expected="absent"
                )
            )

    def step9_second_driver(self, owner: str, first: str, child: str, dispatched: str) -> tuple[driver.DriverCase, str]:
        second = self._discover(self._known(owner, first, child, dispatched))
        case = self._driver_case("second", 4)
        case.check_startup(second, frozenset({owner, first, child, dispatched, second}))
        self._require_pool(5)
        instruction = case.claim_call([])
        case.check_instruction(second, instruction)
        case.observe_claim(second, holds_nothing=[owner, dispatched], earlier=[first])
        driver.release_attempt(self.starts, self.decision_attempt)  # consumed by the second driver\'s claim
        for session in (owner, child, dispatched):
            role = self._record(session).get(FIELD_ROLE)
            if role == DRIVER_ROLE:
                raise creation.platform_failure(DETAIL_NOT_DRIVER.format(session=session, role=role))
        return case, second

    def step10_close(self, case: driver.DriverCase, second: str, owner: str, dispatched: str) -> None:
        case.close(second)
        for name, session in (("dispatched", dispatched), ("owner", owner)):
            journey = self.journeys[name]
            journey.session_id = session
            journey.end_session()


def run_waiting(
    host: FoundationHost,
    setup: foundation.FixtureSetup,
    project: Path,
    source_root: Path,
    owner_email: str,
    owner_slug: str,
    register_company: Callable[[], None],
    retain: Callable[[str], None],
) -> None:
    """Journey B3; raises JourneyFailure leading with its class."""
    waiting = _Waiting(host, setup, project, source_root, owner_email, owner_slug, register_company, retain)
    observer = waiting.observer
    failure: BaseException | None = None
    try:
        creation.require_manual_runner(observer)
        waiting.publication.begin(own_generation=True)
        creation.enter_project(observer, project)
        waiting.baseline = observer.sessions()
        waiting.verify_owner()
        waiting.setup_pool()
        creation.require_created(creation.create_item(observer, ITEM, CONTENT, "feature", approved=True), ITEM)
        before = driver.shown_with_content(observer, ITEM)
        creation.require_value(ITEM, before, "state.lifecycle_phase", PHASE_PREPARATION)
        creation.require_unclaimed(ITEM, before)
        creation.require_standing_clear(ITEM, before)
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
        waiting.step5_entry_refused(owner, first, child)
        dispatched = waiting.step6_dispatched(owner, first, child)
        waiting.step7_end_first(first_case, first)
        waiting.step8_decide(owner)
        second_case, second = waiting.step9_second_driver(owner, first, child, dispatched)
        waiting.step10_close(second_case, second, owner, dispatched)
    except BaseException as error:
        failure = error
        raise
    finally:
        _cleanup(waiting, failure)


def _cleanup(waiting: _Waiting, failure: BaseException | None) -> None:
    """Settle the sessions the journey owns, restore the candidate publication and the sidecar, report every failure."""
    settlement = publication.settle_sessions(
        waiting.observer, waiting.baseline, waiting.starts, waiting.controls.directories
    )
    problems = list(settlement.problems)
    problems.extend(waiting.publication.restore())
    if settlement.proven:
        problems.extend(waiting.controls.restore())
    else:
        kept = DETAIL_CONTROLS_KEPT.format(control=waiting.controls.root)
        problems.append(kept)
        waiting.retain(kept)
    try:
        creation.leave_project(waiting.observer, waiting.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    problems.extend(waiting.publication.candidate_unchanged())
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        waiting.publication.note("cleanup-problems", "; ".join(problems))
