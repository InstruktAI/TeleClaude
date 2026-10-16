"""Journey B2 of the workflow acceptance: a start in progress refuses a distinct requester, a race leaves one driver.

The journey\'s assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/b2-start-race-assertion-draft.md`, approved at exact SHA-256
95c7a8e7698bfc45737bb107508bc009e1f2c62520b78f5716b2061f29d6a9b4; it reuses the B1 draft
8139046b04adbf9219f29b472e8bb49e513da9cd7946ee60ddfaf0bb964df1e6 with its act-row amendment
d7270641fcb963b66f58c79201ac936d293358665b967f493a7e625a3eac0728 and its title amendment
f9a4d846c18e44c8d5a65082532a2e0245ab357b4f33254843977e6db81e600f; authority the pending
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and `.../procedure-entry` contracts of issue 128).

On the published installation, a real requester session that holds nothing starts, then the owner starts a driver whose
launch the fixture holds before its SessionStart. While that start is in progress the requester\'s own start of the same
item is refused naming the owner terminal and writes nothing, the owner\'s repeated start attaches, and after the hold
one driver claims. A second item then takes two requesters at once: exactly one start fails and one driver claims.

It proves one racing interleaving and the deterministic start-in-progress refusal, not statistical or exhaustive
concurrency, no model following, no event count and no whole delivery. A negative sample is judged only when the
one-way barrier latch, read last, proves the sample was taken while the start was held; a window that expired is a failed
control (a binding failure), never a verdict about the platform. This controller creates no session record, role,
reservation, identity or authentication state, reads no private store and imports no application module.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, TypedDict

from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_publication as publication
from tools.ci.workflow_foundation import FoundationHost, Outcome

TELEC: Final = "bin/telec"
TODO: Final = "todo"
PREPARE: Final = "prepare"
SESSIONS: Final = "sessions"
SHOW: Final = "show"
FULL_FLAG: Final = "--full"
ITEM_W: Final = "b2-item"
ITEM_R: Final = "b2-race"
CONTENT_W: Final = "b2 start window content"
CONTENT_R: Final = "b2 race content"
CONTROL_NAME: Final = "native-fixture-control-b2"

GO_W: Final = "go_w"
GO_R: Final = "go_r"
FRAME_W: Final = "cmd_w"
FRAME_R: Final = "cmd_r"
HOLD_SECONDS: Final = 40
RESERVE_SECONDS: Final = 3.0
MIN_GUARD_SECONDS: Final = 5.0
COMMAND_BOUND_SECONDS: Final = 10.0
DISCOVER_SECONDS: Final = 120.0
COMPOSER_SECONDS: Final = 30.0
POLL_SECONDS: Final = 2.0
FRAME_POLL_SECONDS: Final = 0.5
ATTACH_RESERVE_SECONDS: Final = 6.0
ATTACH_MINIMUM_SECONDS: Final = 4.0
ATTACH_SPACING_SECONDS: Final = 3.0
STARTER_WINDOW_SECONDS: Final = 100.0
STARTER_SETTLE_SECONDS: Final = 20.0
CLAIM_CAP_SECONDS: Final = 900.0
QUIET_GAP_SECONDS: Final = 2.0
FRAME_READ_SECONDS: Final = 2.0
START_CAP_SECONDS: Final = 900.0

OWNER_REQUESTER: Final = "person at a terminal"
IN_PROGRESS: Final = "in progress"
DENIED: Final = "permission denied"
HEADER_PREFIX: Final = "### "

FIELD_STATE: Final = publication.FIELD_STATE
FIELD_ERROR: Final = publication.FIELD_ERROR
FIELD_RESULT: Final = publication.FIELD_RESULT
STATE_COMPLETED: Final = publication.STATE_COMPLETED
STATE_FAILED: Final = publication.STATE_FAILED
TERMINAL_STATES: Final = publication.TERMINAL_STATES

DETAIL_EXCEEDED: Final = "control window exceeded: {detail}"
DETAIL_LATCH: Final = "the barrier latch was present at the final read, so the sequence was not proven inside the hold"
DETAIL_NO_COMPOSER: Final = "{control} never drew its composer within {seconds} seconds of its launch"
DETAIL_DISCOVER: Final = "no single new session appeared beyond {known!r} within {seconds} seconds: found {found!r}"
DETAIL_EXTRA: Final = "more than one session appeared beyond {known!r}: {found!r}"
DETAIL_POOL: Final = "the pool directories claimed are {found!r}, not the planned {expected!r}"
DETAIL_RECEIPT: Final = "`telec todo prepare {item}` printed no operation receipt: exit {status}, {output!r}"
DETAIL_S2_ROLE: Final = "the requester session holds a role {role!r}; it must hold none"
DETAIL_QUIET: Final = "the item is being written by something else; differing paths: {paths}"
DETAIL_FRAME: Final = "the requester's frame {name} is not a completed public call: {frame!r}"
DETAIL_CLEARANCE: Final = "the requester's prepare was denied by the gate, a clearance failure: {output!r}"
DETAIL_SAME_OPERATION: Final = "the distinct requester's operation {operation} equals the owner's"
DETAIL_STARTED_EARLY: Final = "{what} while the barrier was closed: {found!r}"
DETAIL_NOT_REFUSED: Final = "the distinct requester's operation ended {state!r} ({error!r}), not a refusal"
DETAIL_REFUSAL_TEXT: Final = "the refusal does not contain {needle!r}: {error!r}"
DETAIL_WRITE: Final = "the item read {when} differs from before the loser's call; differing paths: {paths}"
DETAIL_ATTACH: Final = "the owner's operation {operation} was {state!r} while the start was held"
DETAIL_PAIR: Final = "the racing operations read {states!r}, not exactly one failed and one still waiting"
DETAIL_HEADERS: Final = "the log of {item} holds {count} section headers, not exactly one: {log!r}"
DETAIL_STARTER: Final = "the winner's operation result does not contain the session: {result!r}"
DETAIL_RESULT_TYPE: Final = "operation {operation} result is not a string: {result!r}"
DETAIL_OPERATION_FAILED: Final = "operation {operation} failed: {error!r}"
DETAIL_CONTROLS_KEPT: Final = "closure was not proven, so the control directories {control} are kept for diagnosis"
DETAIL_WITNESS_UNREADABLE: Final = (
    "the witness read of driver {session} is unreadable, so the hold is unproven: {output!r}"
)
DETAIL_HEADER_NAMES: Final = "the log of {item} holds a header naming {session!r}, which holds nothing: {header!r}"
DETAIL_SESSIONS_MOVED: Final = "the sessions changed during the hold: {found!r}"
DETAIL_ONE_DRIVER: Final = "the sessions beyond the known set are {found!r}, not exactly one driver"
WHEN_REFUSED: Final = "after the refusal"
WHEN_REPEATED: Final = "after the repeat"
NOT_EVALUATED_STARTER: Final = "starter result not evaluated: {reason}"
NOT_EVALUATED_LABEL: Final = "starter-result-not-evaluated"

type Json = Mapping[str, object]


class WindowExceeded(RuntimeError):
    """The hold ended, or could not be used, before a sequence finished: a failed control, never a verdict."""


class Window:
    """The guarded part of a driver\'s hold: from its composer marker until three seconds before its deadline."""

    def __init__(self, composer_at: float) -> None:
        self.end = composer_at + HOLD_SECONDS - RESERVE_SECONDS

    def guard(self) -> float:
        return self.end - time.monotonic()

    def sleep(self, seconds: float) -> None:
        room = self.guard() - MIN_GUARD_SECONDS
        if room <= 0:
            raise WindowExceeded(f"{self.guard():.1f} seconds left, below the {MIN_GUARD_SECONDS:.0f} needed")
        time.sleep(min(seconds, room))


class _GuardedHost:
    """A host whose every public command starts only with at least five seconds left and is bounded by what is left."""

    def __init__(self, host: FoundationHost, window: Window) -> None:
        self.host = host
        self.window = window

    @property
    def environment(self) -> Mapping[str, str]:
        return self.host.environment

    def cli(self, argv: Sequence[str], timeout_seconds: float, *, retain: bool = True) -> Outcome:
        remaining = self.window.guard()
        if remaining < MIN_GUARD_SECONDS:
            raise WindowExceeded(f"{remaining:.1f} seconds left before `{' '.join(argv[1:3])}`")
        bound = min(COMMAND_BOUND_SECONDS, remaining, timeout_seconds)
        outcome = self.host.cli(argv, bound, retain=retain)
        if outcome.exit_status is None:
            raise WindowExceeded(f"`{' '.join(argv[1:3])}` did not finish within {bound:.0f} seconds")
        return outcome

    def process(
        self, argv: Sequence[str], cwd: Path, environment: Mapping[str, str], timeout_seconds: float
    ) -> Outcome:
        return self.host.process(argv, cwd, environment, timeout_seconds)

    def note(self, argv: Sequence[str], outcome: Outcome, diagnostics: str) -> None:
        self.host.note(argv, outcome, diagnostics)


@contextmanager
def held(control: Path) -> Iterator[None]:
    """The hold ends on every path: the controller\'s release is written whatever happened inside."""
    try:
        yield
    finally:
        (control / foundation.RELEASE_FILE).write_text("1\n", encoding="utf-8")


@dataclass
class Witness:
    """The W-end reading of one hold: the driver\'s record, the item\'s holder, and the latch, read last."""

    record: Json | None = None
    holder: object = None
    latch_present: bool = False


@dataclass
class Sample:
    """What one hold collected; judged only after the latch proved the hold."""

    exceeded: str = ""
    witness: Witness = field(default_factory=Witness)


@dataclass
class StartSample(Sample):
    """Phase W: the distinct requester\'s refusal, the owner\'s attach and the item read around them."""

    s_b: Json = field(default_factory=dict)
    b_w: frozenset[str] = frozenset()
    loser: str = ""
    loser_state: Json = field(default_factory=dict)
    s_1: Json = field(default_factory=dict)
    sessions_1: frozenset[str] = frozenset()
    attach: str = ""
    attach_reads: list[tuple[object, object]] = field(default_factory=list)
    s_f: Json = field(default_factory=dict)
    sessions_f: frozenset[str] = frozenset()


@dataclass
class RaceSample(Sample):
    """Phase R: the two racing operations read to a conclusive pair, and the item and sessions around them."""

    s_r0: Json = field(default_factory=dict)
    sessions_0: frozenset[str] = frozenset()
    requester_operation: str = ""
    owner_state: Json = field(default_factory=dict)
    requester_state: Json = field(default_factory=dict)
    s_r1: Json = field(default_factory=dict)
    sessions_1: frozenset[str] = frozenset()


class _Command(TypedDict, total=False):
    name: str
    argv: list[str]
    wait_for: str


class _Plan(TypedDict, total=False):
    commands: list[_Command]
    barrier_hold_seconds: int


def _plan(commands: Sequence[_Command], hold: int | None = None) -> _Plan:
    plan = _Plan(commands=list(commands))
    if hold is not None:
        plan["barrier_hold_seconds"] = hold
    return plan


class _Race:
    """One run of journey B2."""

    def __init__(
        self,
        host: FoundationHost,
        setup: foundation.FixtureSetup,
        project: Path,
        source_root: Path,
        owner_email: str,
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
        self.baseline: creation.SessionView | None = None
        self.starts: dict[str, str] = {}
        self.setups: list[foundation.FixtureSetup] = []
        self.clone: Path = source_root
        self.requester = ""
        self.requester_journey: foundation.Journey | None = None
        self.cases: list[driver.DriverCase] = []
        self.driver_w = ""
        self.driver_r = ""

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _known(self, *sessions: str) -> frozenset[str]:
        assert self.baseline is not None
        return self.baseline.ids | frozenset(sessions)

    def _receipt(self, observer: creation.Observer, item: str, label: str) -> str:
        outcome, operation = driver.start_call(self.starts, observer, (TELEC, TODO, PREPARE, item), label)
        if outcome.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(item=item, status=outcome.exit_status, output=outcome.output[-300:])
            )
        return operation

    def _discover(self, known: frozenset[str]) -> str:
        deadline = time.monotonic() + DISCOVER_SECONDS
        found: list[str] = []
        while time.monotonic() < deadline:
            found = sorted(self.observer.sessions(retain=False).ids - known)
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise creation.platform_failure(DETAIL_EXTRA.format(known=sorted(known), found=found))
            time.sleep(POLL_SECONDS)
        raise creation.platform_failure(
            DETAIL_DISCOVER.format(known=sorted(known), seconds=int(DISCOVER_SECONDS), found=found)
        )

    def _composer(self, control: Path, claimed: Sequence[int]) -> float:
        deadline = time.monotonic() + COMPOSER_SECONDS
        path = control / foundation.COMPOSER_FILE
        while time.monotonic() < deadline:
            try:
                return float(path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                time.sleep(foundation.POLL_SECONDS)
        self._require_pool(claimed)
        raise creation.binding_failure(DETAIL_NO_COMPOSER.format(control=control.name, seconds=int(COMPOSER_SECONDS)))

    def _require_pool(self, claimed: Sequence[int]) -> None:
        expected = [self.setups[index].control for index in claimed]
        found = self.controls.claimed()
        if found != expected:
            raise creation.binding_failure(
                DETAIL_POOL.format(found=[p.name for p in found], expected=[p.name for p in expected])
            )

    def _frame(self, window: Window, name: str, attempt: str) -> Json:
        """A completed frame of the requester, awaited under the guard of the hold.

        The attempt it stands for was owned before its gate opened; a parsed receipt replaces it even when the frame
        reports a failure, and a frame that never completes leaves the attempt open.
        """
        assert self.requester_journey is not None
        marker = self.setups[0].control / foundation.FRAMES_DIRECTORY / f"{name}{foundation.FRAME_COMPLETE_SUFFIX}"
        while not marker.exists():
            window.sleep(FRAME_POLL_SECONDS)
        frame = self.requester_journey.await_frame(name, time.monotonic() + FRAME_READ_SECONDS)
        run = frame.get("run")
        stdout = run.get("stdout") if isinstance(run, dict) else None
        driver.settle_attempt(
            self.starts, attempt, driver.receipt_operation(stdout) if isinstance(stdout, str) else None
        )
        if not isinstance(run, dict) or run.get("exit_status") != 0 or run.get("timed_out") is True:
            text = f"{run.get('stdout', '')}{run.get('stderr', '')}" if isinstance(run, dict) else ""
            if DENIED in text.lower():
                raise creation.binding_failure(DETAIL_CLEARANCE.format(output=text[-300:]))
            raise creation.platform_failure(DETAIL_FRAME.format(name=name, frame=frame))
        return frame

    def _frame_operation(self, frame: Json) -> str:
        run = frame.get("run")
        stdout = run.get("stdout") if isinstance(run, dict) else None
        operation = driver.receipt_operation(stdout) if isinstance(stdout, str) else None
        if operation is None:
            raise creation.platform_failure(DETAIL_FRAME.format(name="receipt", frame=frame))
        return operation

    def _witness(self, guarded: creation.Observer, session: str, item: str, control: Path) -> Witness:
        """The W-end witness: state reads first, the one-way latch read last."""
        outcome = guarded.run((TELEC, SESSIONS, SHOW, session, FULL_FLAG))
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        if record is None:
            raise creation.binding_failure(
                DETAIL_WITNESS_UNREADABLE.format(session=session, output=outcome.output[-300:])
            )
        shown = driver.shown_with_content(guarded, item)
        witness = Witness(record=record, holder=creation.dig(shown, "state.active_runner")[1])
        witness.latch_present = (control / foundation.BARRIER_FILE).exists()
        return witness

    def _judge_hold(self, sample: Sample, driver_session: str) -> None:
        """No verdict unless the latch proved the hold; then the driver must not have started or claimed."""
        if sample.exceeded:
            raise creation.binding_failure(DETAIL_EXCEEDED.format(detail=sample.exceeded))
        witness = sample.witness
        if witness.latch_present:
            raise creation.binding_failure(DETAIL_EXCEEDED.format(detail=DETAIL_LATCH))
        record = witness.record or {}
        started = (
            record.get(foundation.FIELD_LIFECYCLE) != foundation.INITIALIZING
            or record.get(foundation.FIELD_OBSERVED) is not False
            or record.get(foundation.FIELD_CLOSED_AT) is not None
        )
        if started:
            raise creation.platform_failure(
                DETAIL_STARTED_EARLY.format(what=f"driver {driver_session} had started", found=record)
            )
        if witness.holder not in (None, ""):
            raise creation.platform_failure(
                DETAIL_STARTED_EARLY.format(what="the item was claimed", found=witness.holder)
            )

    # -- setup -----------------------------------------------------------------------------------------------------
    def setup_pool(self) -> None:
        claim_w = _Command(name=driver.CLAIM_NAME, argv=["telec", TODO, PREPARE, ITEM_W])
        claim_r = _Command(name=driver.CLAIM_NAME, argv=["telec", TODO, PREPARE, ITEM_R])
        requester = _plan(
            [
                _Command(name="w", argv=["telec", TODO, PREPARE, ITEM_W], wait_for=GO_W),
                _Command(name="r", argv=["telec", TODO, PREPARE, ITEM_R], wait_for=GO_R),
            ]
        )
        self.setups = self.controls.pool(
            [requester, _plan([claim_w], HOLD_SECONDS), _plan([claim_r], HOLD_SECONDS), _plan([])]
        )

    def start_requester(self) -> None:
        """Phase 0: a platform-created session that holds nothing, started as F0 starts one."""
        journey = foundation.Journey(self.host, self.setups[0], self.project, self.owner_email)
        self.requester_journey = journey
        started = journey.start_session()
        self.requester = journey.session_id
        journey.positive_start(started)
        record = journey.record()
        if record is None or record.get("role"):
            raise creation.platform_failure(DETAIL_S2_ROLE.format(role=(record or {}).get("role")))
        created = self.observer.sessions().ids - self._known()
        if created != frozenset({self.requester}):
            raise creation.platform_failure(f"sessions beyond the baseline are {sorted(created)!r}, not the requester")

    def driver_case(self, index: int, item: str) -> driver.DriverCase:
        journey = foundation.Journey(self.host, self.setups[index], self.project, self.owner_email)
        assert self.baseline is not None
        case = driver.DriverCase(
            host=self.host,
            observer=self.observer,
            journey=journey,
            item=item,
            launch_setup=self.setups[index],
            clone=self.clone,
            baseline=self.baseline,
        )
        self.cases.append(case)
        return case

    # -- the evidence both phases share -----------------------------------------------------------------------------
    def await_holder(self, item: str, session: str) -> float:
        """The moment the item shows the session as its holder."""
        deadline = time.monotonic() + CLAIM_CAP_SECONDS
        while time.monotonic() < deadline:
            shown = self.observer.show(item, retain=False)
            holder = creation.dig(shown, "state.active_runner")[1] if shown is not None else None
            if holder == session:
                return time.monotonic()
            time.sleep(POLL_SECONDS)
        raise creation.platform_failure(f"{session} did not claim {item} within {int(CLAIM_CAP_SECONDS)} seconds")

    def driver_evidence(
        self, case: driver.DriverCase, session: str, expected_new: frozenset[str], distinct: Sequence[str]
    ) -> float:
        """The B1 driver evidence for one released driver, with the claim moment returned."""
        seen = self.await_holder(case.item, session)
        case.check_startup(session, expected_new)
        instruction = case.claim_call(distinct)
        case.check_instruction(session, instruction)
        case.observe_claim(session, holds_nothing=[self.requester])
        for operation in distinct:
            if self.starts.get(operation) == publication.START_OPEN:
                self.starts[operation] = publication.START_CLAIMED
        return seen

    def starter_result(self, operation: str, session: str, started_at: float, seen: float) -> None:
        """The winner\'s starter result names the session, evaluated only inside the attach window."""
        deadline = time.monotonic() + STARTER_SETTLE_SECONDS
        state = publication.operation_state(self.observer, operation, retain=True)
        while state.get(FIELD_STATE) not in TERMINAL_STATES and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
            state = publication.operation_state(self.observer, operation)
        if state.get(FIELD_STATE) in TERMINAL_STATES - {STATE_COMPLETED}:
            raise creation.platform_failure(
                DETAIL_OPERATION_FAILED.format(operation=operation, error=state.get(FIELD_ERROR))
            )
        reason = ""
        if seen - started_at > STARTER_WINDOW_SECONDS:
            reason = "the claim was observed after the attach window"
        elif state.get(FIELD_STATE) != STATE_COMPLETED:
            reason = "the starter was not terminal"
        if reason:
            text = NOT_EVALUATED_STARTER.format(reason=reason)
            self.host.note((NOT_EVALUATED_LABEL, operation, text), Outcome(None, text), "")
            return
        result = state.get(FIELD_RESULT)
        if not isinstance(result, str):
            raise creation.platform_failure(DETAIL_RESULT_TYPE.format(operation=operation, result=result))
        if session not in result:
            raise creation.platform_failure(DETAIL_STARTER.format(result=result))

    # -- phase W ---------------------------------------------------------------------------------------------------
    def phase_w(self) -> None:
        owner_operation = self._receipt(self.observer, ITEM_W, "owner-w")
        started_at = time.monotonic()
        held_driver = self._discover(self._known(self.requester))
        control = self.setups[1].control
        window = Window(self._composer(control, (0, 1)))
        self._require_pool((0, 1))
        guarded = creation.Observer(_GuardedHost(self.host, window))
        sample = StartSample()
        with held(control):
            try:
                self._collect_w(guarded, window, sample, owner_operation)
                sample.witness = self._witness(guarded, held_driver, ITEM_W, control)
            except WindowExceeded as error:
                sample.exceeded = str(error)
        self._judge_hold(sample, held_driver)
        self._judge_w(sample, owner_operation)
        case = self.driver_case(1, ITEM_W)
        distinct = [operation for operation in dict.fromkeys([owner_operation, str(sample.attach)])]
        seen = self.driver_evidence(
            case, held_driver, frozenset({self.requester, held_driver}), [*distinct, str(sample.loser)]
        )
        self._require_requester_unnamed(ITEM_W, self._headers(ITEM_W))
        for operation in distinct:
            self.starter_result(operation, held_driver, started_at, seen)
        self.driver_w = held_driver

    def _collect_w(self, guarded: creation.Observer, window: Window, sample: StartSample, owner_operation: str) -> None:
        first = driver.shown_with_content(guarded, ITEM_W)
        window.sleep(QUIET_GAP_SECONDS)
        second = driver.shown_with_content(guarded, ITEM_W)
        changed = creation.differences(first, second)
        if changed:
            raise creation.binding_failure(DETAIL_QUIET.format(paths=changed))
        sample.s_b = second
        sample.b_w = guarded.sessions().ids
        attempt = driver.begin_attempt(self.starts, "requester-w")
        (self.setups[0].control / GO_W).write_text("1\n", encoding="utf-8")
        loser = self._frame_operation(self._frame(window, FRAME_W, attempt))
        if loser == owner_operation:
            raise creation.platform_failure(DETAIL_SAME_OPERATION.format(operation=loser))
        sample.loser = loser
        state = publication.operation_state(guarded, loser)
        while state.get(FIELD_STATE) not in TERMINAL_STATES:
            window.sleep(POLL_SECONDS)
            state = publication.operation_state(guarded, loser)
        sample.loser_state = state
        sample.s_1 = driver.shown_with_content(guarded, ITEM_W)
        sample.sessions_1 = guarded.sessions().ids
        again, attach = driver.start_call(self.starts, guarded, (TELEC, TODO, PREPARE, ITEM_W), "attach")
        if again.exit_status != 0 or attach is None:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(item=ITEM_W, status=again.exit_status, output=again.output[-300:])
            )
        sample.attach = attach
        length = min(COMMAND_BOUND_SECONDS, window.guard() - ATTACH_RESERVE_SECONDS)
        if length < ATTACH_MINIMUM_SECONDS:
            raise WindowExceeded("too little of the hold remained to observe the attach")
        reads: list[tuple[object, object]] = []
        stop = time.monotonic() + length
        while True:
            reads.append(
                (
                    publication.operation_state(guarded, owner_operation).get(FIELD_STATE),
                    publication.operation_state(guarded, attach).get(FIELD_STATE),
                )
            )
            if time.monotonic() + ATTACH_SPACING_SECONDS >= stop:
                break
            window.sleep(ATTACH_SPACING_SECONDS)
        sample.attach_reads = reads
        sample.s_f = driver.shown_with_content(guarded, ITEM_W)
        sample.sessions_f = guarded.sessions().ids

    def _judge_w(self, sample: StartSample, owner_operation: str) -> None:
        state = sample.loser_state
        error = state.get(FIELD_ERROR)
        if state.get(FIELD_STATE) != STATE_FAILED or not isinstance(error, str):
            raise creation.platform_failure(DETAIL_NOT_REFUSED.format(state=state.get(FIELD_STATE), error=error))
        lowered = error.lower()
        for needle in (ITEM_W, IN_PROGRESS, OWNER_REQUESTER):
            if needle.lower() not in lowered:
                raise creation.platform_failure(DETAIL_REFUSAL_TEXT.format(needle=needle, error=error))
        self.starts[str(sample.loser)] = publication.START_REFUSED
        before = sample.s_b
        for when, after in ((WHEN_REFUSED, sample.s_1), (WHEN_REPEATED, sample.s_f)):
            changed = creation.differences(before, after)
            if changed:
                raise creation.platform_failure(DETAIL_WRITE.format(when=when, paths=changed))
        for found in (sample.sessions_1, sample.sessions_f):
            if found != sample.b_w:
                raise creation.platform_failure(DETAIL_SESSIONS_MOVED.format(found=sorted(found)))
        for read in sample.attach_reads:
            for operation, observed in zip((owner_operation, sample.attach), read, strict=True):
                if observed in TERMINAL_STATES:
                    raise creation.platform_failure(DETAIL_ATTACH.format(operation=operation, state=observed))

    # -- phase R ---------------------------------------------------------------------------------------------------
    def phase_r(self) -> None:
        assert self.requester_journey is not None
        attempt = driver.begin_attempt(self.starts, "requester-r")
        (self.setups[0].control / GO_R).write_text("1\n", encoding="utf-8")
        owner_operation = self._receipt(self.observer, ITEM_R, "owner-r")
        fired = time.monotonic()
        held_driver = self._discover(self._known(self.requester, self.driver_w))
        control = self.setups[2].control
        window = Window(self._composer(control, (0, 1, 2)))
        self._require_pool((0, 1, 2))
        guarded = creation.Observer(_GuardedHost(self.host, window))
        sample = RaceSample()
        with held(control):
            try:
                self._collect_r(guarded, window, sample, owner_operation, attempt)
                sample.witness = self._witness(guarded, held_driver, ITEM_R, control)
            except WindowExceeded as error:
                sample.exceeded = str(error)
        self._judge_hold(sample, held_driver)
        winner = self._judge_r(sample, owner_operation, held_driver)
        case = self.driver_case(2, ITEM_R)
        seen = self.driver_evidence(
            case,
            held_driver,
            frozenset({self.requester, self.driver_w, held_driver}),
            [owner_operation, str(sample.requester_operation)],
        )
        headers = self._headers(ITEM_R)
        if len(headers) != 1:
            raise creation.platform_failure(DETAIL_HEADERS.format(item=ITEM_R, count=len(headers), log=headers))
        self._require_requester_unnamed(ITEM_R, headers)
        self.starter_result(winner, held_driver, fired, seen)
        self.driver_r = held_driver

    def _headers(self, item: str) -> list[str]:
        """Every section header line of the item\'s log, in order."""
        shown = driver.shown_with_content(self.observer, item)
        log = creation.dig(shown, "artifact_content.log")[1]
        return [line for line in str(log).replace("\r\n", "\n").split("\n") if line.startswith(HEADER_PREFIX)]

    def _require_requester_unnamed(self, item: str, headers: Sequence[str]) -> None:
        """No header line of the log names the requester, which held nothing."""
        for header in headers:
            if self.requester in header:
                raise creation.platform_failure(
                    DETAIL_HEADER_NAMES.format(item=item, session=self.requester, header=header)
                )

    def _collect_r(
        self, guarded: creation.Observer, window: Window, sample: RaceSample, owner_operation: str, attempt: str
    ) -> None:
        sample.s_r0 = driver.shown_with_content(guarded, ITEM_R)
        sample.sessions_0 = guarded.sessions().ids
        requester_operation = self._frame_operation(self._frame(window, FRAME_R, attempt))
        sample.requester_operation = requester_operation
        while True:
            owner_state = publication.operation_state(guarded, owner_operation)
            requester_state = publication.operation_state(guarded, requester_operation)
            if owner_state.get(FIELD_STATE) in TERMINAL_STATES or requester_state.get(FIELD_STATE) in TERMINAL_STATES:
                break
            window.sleep(POLL_SECONDS)
        sample.owner_state = owner_state
        sample.requester_state = requester_state
        sample.s_r1 = driver.shown_with_content(guarded, ITEM_R)
        sample.sessions_1 = guarded.sessions().ids

    def _judge_r(self, sample: RaceSample, owner_operation: str, held_driver: str) -> str:
        owner_state, requester_state = sample.owner_state, sample.requester_state
        pair = (owner_state.get(FIELD_STATE), requester_state.get(FIELD_STATE))
        failed = [state == STATE_FAILED for state in pair]
        waiting = [state not in TERMINAL_STATES for state in pair]
        if sum(failed) != 1 or sum(waiting) != 1:
            raise creation.platform_failure(DETAIL_PAIR.format(states=pair))
        requester_operation = str(sample.requester_operation)
        if failed[0]:
            loser_state, loser_operation, winner, token = (
                owner_state,
                owner_operation,
                requester_operation,
                self.requester,
            )
        else:
            loser_state, loser_operation, winner, token = (
                requester_state,
                requester_operation,
                owner_operation,
                OWNER_REQUESTER,
            )
        error = loser_state.get(FIELD_ERROR)
        if not isinstance(error, str):
            raise creation.platform_failure(DETAIL_NOT_REFUSED.format(state=loser_state.get(FIELD_STATE), error=error))
        for needle in (ITEM_R, IN_PROGRESS, token):
            if needle.lower() not in error.lower():
                raise creation.platform_failure(DETAIL_REFUSAL_TEXT.format(needle=needle, error=error))
        self.starts[loser_operation] = publication.START_REFUSED
        changed = creation.differences(sample.s_r0, sample.s_r1)
        if changed:
            raise creation.platform_failure(DETAIL_WRITE.format(when="after the race", paths=changed))
        expected = self._known(self.requester, self.driver_w)
        for found in (sample.sessions_0, sample.sessions_1):
            extra = found - expected
            if extra != frozenset({held_driver}):
                raise creation.platform_failure(DETAIL_ONE_DRIVER.format(found=sorted(extra)))
        return winner

    def close(self) -> None:
        """Step 12: the drivers and the requester end; the claims are released and the items return unheld."""
        for case, session in zip(self.cases, (self.driver_w, self.driver_r), strict=True):
            case.close(session)
        assert self.requester_journey is not None
        self.requester_journey.session_id = self.requester
        self.requester_journey.end_session()


def run_race(
    host: FoundationHost,
    setup: foundation.FixtureSetup,
    project: Path,
    source_root: Path,
    owner_email: str,
    register_company: Callable[[], None],
    retain: Callable[[str], None],
) -> None:
    """Journey B2; raises JourneyFailure leading with its class."""
    race = _Race(host, setup, project, source_root, owner_email, register_company, retain)
    observer = race.observer
    failure: BaseException | None = None
    try:
        creation.require_manual_runner(observer)
        race.publication.begin()
        creation.enter_project(observer, project)
        race.baseline = observer.sessions()
        race.setup_pool()
        for item, content in ((ITEM_W, CONTENT_W), (ITEM_R, CONTENT_R)):
            creation.require_created(creation.create_item(observer, item, content, "feature", approved=True), item)
        before = driver.shown_with_content(observer, ITEM_W)
        _require_unclaimed(ITEM_W, before)
        _require_unclaimed(ITEM_R, driver.shown_with_content(observer, ITEM_R))
        race.clone = race.publication.prepare()
        creation.enter_project(observer, project)
        publication.negative_control(observer, ITEM_W, race.baseline, before, race.starts)
        race.publication.publish()
        race.publication.verify_parity()
        creation.enter_project(observer, project)
        race.start_requester()
        race.phase_w()
        race.phase_r()
        race.close()
    except BaseException as error:
        failure = error
        raise
    finally:
        _cleanup(race, failure)


def _require_unclaimed(item: str, shown: Json) -> None:
    creation.require_value(item, shown, "state.lifecycle_phase", driver.PHASE)
    creation.require_value(item, shown, "state.hold", False)
    creation.require_unclaimed(item, shown)
    creation.require_standing_clear(item, shown)


def _cleanup(race: _Race, failure: BaseException | None) -> None:
    """Settle the sessions the journey owns, restore the candidate publication and the sidecar, report every failure."""
    settlement = publication.settle_sessions(race.observer, race.baseline, race.starts, race.controls.directories)
    problems = list(settlement.problems)
    problems.extend(race.publication.restore())
    if settlement.proven:
        problems.extend(race.controls.restore())
    else:
        kept = DETAIL_CONTROLS_KEPT.format(control=race.controls.root)
        problems.append(kept)
        race.retain(kept)
    try:
        creation.leave_project(race.observer, race.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    problems.extend(race.publication.candidate_unchanged())
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        race.publication.note("cleanup-problems", "; ".join(problems))
