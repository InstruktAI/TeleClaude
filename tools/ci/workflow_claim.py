"""Journey B1 of the workflow acceptance: an explicit prepare starts the real driver, which claims with its reservation.

The journey's assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/b1-claim-assertion-draft.md`, approved at exact SHA-256
8139046b04adbf9219f29b472e8bb49e513da9cd7946ee60ddfaf0bb964df1e6, amended for step 4's act rows by
`journeys/b1-instruction-act-pairs-amendment-draft.md` at exact SHA-256
d7270641fcb963b66f58c79201ac936d293358665b967f493a7e625a3eac0728, and for the driver\'s title by
`journeys/b1-driver-title-amendment-draft.md` at exact SHA-256
f9a4d846c18e44c8d5a65082532a2e0245ab357b4f33254843977e6db81e600f; authority the pending
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and `.../procedure-entry` contracts of issue 128).
It proves, on a disposable installation whose published drivers are the four folded procedures, that the public
`telec todo prepare` starts one platform-created driver session, that the driver's own fresh public `telec todo prepare`
claim is accepted with its reservation and renders the instruction, that exactly one claim note exists, that a second
caller is refused naming the holder without any write, and that ending the session releases the claim.

The driver\'s title (catalog role, one space, the item, stable before the end) is asserted by amendment A2.

It proves no racing start, no start-in-progress refusal, no model following of procedures, no event count, no whole
delivery and no starter-result coverage when step 6 is not evaluated. The driver runs as the inert external executable of
journey F0 with a reviewed command plan of public `telec` argv only; this controller creates no session record, role,
reservation, identity or authentication state, reads no private store and imports no application module.

The evidence of the driver session itself lives in `workflow_driver`, the publication in `workflow_publication` and the
control directories in `workflow_controls`, shared with the later journeys of the same family.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from tools.ci import acceptance_work as payload_work
from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_publication as publication
from tools.ci.workflow_foundation import FoundationHost, Outcome

TELEC: Final = "bin/telec"
TODO: Final = "todo"
PREPARE: Final = "prepare"
ITEM: Final = "b1-item"
CONTENT: Final = "b1 driver content"
CONTROL_NAME: Final = "native-fixture-control-b1"
LOG_TERMS: Final = ("preparation_requested", "subscri", "activat", "procedure", "driver", "launch", "workflow")

FIELD_STATE: Final = publication.FIELD_STATE
FIELD_ERROR: Final = publication.FIELD_ERROR
FIELD_RESULT: Final = publication.FIELD_RESULT
STATE_COMPLETED: Final = publication.STATE_COMPLETED
STATE_FAILED: Final = publication.STATE_FAILED
TERMINAL_STATES: Final = publication.TERMINAL_STATES

START_CAP_SECONDS: Final = 900.0
POLL_SECONDS: Final = 2.0
STARTER_WINDOW_SECONDS: Final = 100.0
STARTER_SETTLE_SECONDS: Final = 20.0
COMPETITOR_SECONDS: Final = 60.0
SETTLE_SECONDS: Final = 5.0

DETAIL_RECEIPT: Final = "`telec todo prepare` printed no operation receipt: exit {status}, {output!r}"
DETAIL_OPERATION_FAILED: Final = "operation {operation} failed: {error!r}"
DETAIL_DRIVER_UNPUBLISHED: Final = (
    "the driver lookup refused after publication (the publication did not take effect): {error!r}"
)
DETAIL_START_TIMEOUT: Final = "no session claimed {item} within {seconds} seconds"
DETAIL_RESULT_TYPE: Final = "operation {operation} result is not a string: {result!r}"
DETAIL_STARTER: Final = "the starter's operation result does not contain the session: {result!r}"
DETAIL_COMPETITOR_STATE: Final = "the competing prepare ended {state!r} ({error!r}), not a refusal naming the holder"
DETAIL_COMPETITOR_TEXT: Final = "the refusal does not name {needle!r}: {error!r}"
DETAIL_WRITE: Final = "the item shown {when} differs from before the competing prepare; differing paths: {paths}"
DETAIL_CONTROLS_KEPT: Final = (
    "closure was not proven, so the control directory {control} and the sidecar are kept for diagnosis"
)
NOT_EVALUATED_STARTER: Final = "step 6 not evaluated: {reason}"
NOT_EVALUATED_LABEL: Final = "step-6-not-evaluated"

type Json = Mapping[str, object]


class _Claim:
    """One run of journey B1."""

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
        self.baseline: creation.SessionView | None = None
        self.starts: dict[str, str] = {}
        self.source_root = source_root
        self.project = project.resolve()
        self.owner_email = owner_email
        self.journey: foundation.Journey | None = None


def _require_item_unclaimed(shown: Json) -> None:
    creation.require_value(ITEM, shown, "state.lifecycle_phase", driver.PHASE)
    creation.require_value(ITEM, shown, "state.hold", False)
    creation.require_unclaimed(ITEM, shown)
    creation.require_standing_clear(ITEM, shown)


def run_claim(
    host: FoundationHost,
    setup: foundation.FixtureSetup,
    project: Path,
    source_root: Path,
    owner_email: str,
    register_company: Callable[[], None],
    retain: Callable[[str], None],
) -> None:
    """Journey B1; raises JourneyFailure leading with its class.

    ``register_company`` registers, through the public command, the synthetic company the candidate checkout's project
    declaration names: a documentation read run from that checkout needs it, exactly as the closure journey does.
    """
    claim = _Claim(host, setup, project, source_root, owner_email, register_company, retain)
    observer = claim.observer
    failure: BaseException | None = None
    try:
        creation.require_manual_runner(observer)
        claim.publication.begin()
        creation.enter_project(observer, project)
        baseline = observer.sessions()
        claim.baseline = baseline
        launch_setup = claim.controls.single(
            {"commands": [{"name": driver.CLAIM_NAME, "argv": ["telec", TODO, PREPARE, ITEM]}]}
        )
        journey = foundation.Journey(host, launch_setup, project, owner_email)
        claim.journey = journey
        creation.require_created(creation.create_item(observer, ITEM, CONTENT, "feature", approved=True), ITEM)
        before = driver.shown_with_content(observer, ITEM)
        _require_item_unclaimed(before)
        clone = claim.publication.prepare()
        creation.enter_project(observer, project)
        publication.negative_control(observer, ITEM, baseline, before, claim.starts)
        claim.publication.publish()
        claim.publication.verify_parity()
        creation.enter_project(observer, project)
        quiet = driver.fresh_snapshot(observer, ITEM)
        if creation.differences(before, quiet):
            raise creation.binding_failure(
                DETAIL_WRITE.format(when="after publication", paths=creation.differences(before, quiet))
            )
        _Steps(claim, journey, baseline, launch_setup, clone).run()
    except BaseException as error:
        failure = error
        raise
    finally:
        _cleanup(claim, failure)


class _Steps:
    """The eight steps of journey B1 on the published installation."""

    def __init__(
        self,
        claim: _Claim,
        journey: foundation.Journey,
        baseline: creation.SessionView,
        launch_setup: foundation.FixtureSetup,
        clone: Path,
    ) -> None:
        self.claim = claim
        self.observer = claim.observer
        self.host = claim.host
        self.journey = journey
        self.evidence = driver.DriverCase(
            host=claim.host,
            observer=claim.observer,
            journey=journey,
            item=ITEM,
            launch_setup=launch_setup,
            clone=clone,
            baseline=baseline,
        )
        self.started_at = 0.0
        self.starter = ""
        self.session = ""
        self.claim_seen = 0.0

    def run(self) -> None:
        self.start()
        self.await_claim()
        self.evidence.check_startup(self.session, frozenset({self.session}))
        instruction = self.evidence.claim_call([self.starter])
        self.evidence.check_instruction(self.session, instruction)
        self.evidence.observe_claim(self.session)
        self.starter_result()
        self.competitor()
        self.evidence.close(self.session)

    def start(self) -> None:
        """Step 1: the public start returns a receipt."""
        self.started_at = time.monotonic()
        start, starter = driver.start_call(self.claim.starts, self.observer, (TELEC, TODO, PREPARE, ITEM), "start")
        if start.exit_status != 0 or starter is None:
            raise creation.platform_failure(DETAIL_RECEIPT.format(status=start.exit_status, output=start.output[-300:]))
        self.starter = starter

    def await_claim(self) -> None:
        """Step 2: a real session is created and claims; a failed or unreadable starter ends the wait at once."""
        deadline = self.started_at + START_CAP_SECONDS
        while time.monotonic() < deadline:
            state = publication.operation_state(self.observer, self.starter)
            if state.get(FIELD_STATE) in TERMINAL_STATES - {STATE_COMPLETED}:
                error = str(state.get(FIELD_ERROR))
                if publication.NO_DRIVER_PHRASE in error:
                    raise creation.binding_failure(DETAIL_DRIVER_UNPUBLISHED.format(error=error))
                raise creation.platform_failure(DETAIL_OPERATION_FAILED.format(operation=self.starter, error=error))
            shown = self.observer.show(ITEM, retain=False)
            holder = creation.dig(shown, "state.active_runner")[1] if shown is not None else None
            if isinstance(holder, str) and holder:
                self.session = holder
                self.claim.starts[self.starter] = publication.START_CLAIMED
                self.claim_seen = time.monotonic()
                self.journey.session_id = holder
                return
            payload_work.sleep(POLL_SECONDS)
        starter = publication.operation_state(self.observer, self.starter, retain=True)
        logs = publication.log_evidence(self.host, LOG_TERMS)
        raise creation.platform_failure(
            DETAIL_START_TIMEOUT.format(item=ITEM, seconds=int(START_CAP_SECONDS))
            + f" (the starter reads {dict(starter)!r}; logs: {logs})"
        )

    def starter_result(self) -> None:
        """Step 6: the starter's own result names the session, evaluated only inside the attach window.

        The starter's status is always read: a failed or unreadable operation fails the case whenever it is read; only a
        valid, still-pending operation (or the optional content clause past its window) is left uncredited.
        """
        deadline = time.monotonic() + STARTER_SETTLE_SECONDS
        state = publication.operation_state(self.observer, self.starter, retain=True)
        while state.get(FIELD_STATE) not in TERMINAL_STATES and time.monotonic() < deadline:
            payload_work.sleep(POLL_SECONDS)
            state = publication.operation_state(self.observer, self.starter)
        if state.get(FIELD_STATE) in TERMINAL_STATES - {STATE_COMPLETED}:
            raise creation.platform_failure(
                DETAIL_OPERATION_FAILED.format(operation=self.starter, error=state.get(FIELD_ERROR))
            )
        if self.claim_seen - self.started_at > STARTER_WINDOW_SECONDS:
            self._not_evaluated("the claim was observed after the attach window")
            return
        if state.get(FIELD_STATE) != STATE_COMPLETED:
            self._not_evaluated("the starter was not terminal")
            return
        result = state.get(FIELD_RESULT)
        if not isinstance(result, str):
            raise creation.platform_failure(DETAIL_RESULT_TYPE.format(operation=self.starter, result=result))
        if self.session not in result:
            raise creation.platform_failure(DETAIL_STARTER.format(result=result))

    def _not_evaluated(self, reason: str) -> None:
        text = NOT_EVALUATED_STARTER.format(reason=reason)
        self.host.note((NOT_EVALUATED_LABEL, text), Outcome(None, text), "")

    def competitor(self) -> None:
        """Step 7: a second entry call is refused naming the holder, and nothing is written."""
        observer = self.observer
        snapshot = driver.fresh_snapshot(observer, ITEM)
        held_sessions = observer.sessions()
        competitor, operation = driver.start_call(
            self.claim.starts, observer, (TELEC, TODO, PREPARE, ITEM), "competitor"
        )
        if competitor.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(status=competitor.exit_status, output=competitor.output[-300:])
            )
        refused = publication.await_terminal(observer, operation, COMPETITOR_SECONDS)
        error = refused.get(FIELD_ERROR)
        if refused.get(FIELD_STATE) != STATE_FAILED or not isinstance(error, str):
            raise creation.platform_failure(DETAIL_COMPETITOR_STATE.format(state=refused.get(FIELD_STATE), error=error))
        for needle in (ITEM, self.session):
            if needle not in error:
                raise creation.platform_failure(DETAIL_COMPETITOR_TEXT.format(needle=needle, error=error))
        self.claim.starts[operation] = publication.START_REFUSED
        for when, pause in (("immediately", 0.0), ("five seconds later", SETTLE_SECONDS)):
            if pause:
                payload_work.sleep(pause)
            changed = creation.differences(snapshot, driver.shown_with_content(observer, ITEM))
            if changed:
                raise creation.platform_failure(DETAIL_WRITE.format(when=when, paths=changed))
            creation.require_sessions_equal(held_sessions, observer.sessions(retain=False), when)


def _cleanup(claim: _Claim, failure: BaseException | None) -> None:
    """Settle the sessions the journey owns, restore the candidate publication and the sidecar, report every failure."""
    settlement = publication.settle_sessions(claim.observer, claim.baseline, claim.starts, claim.controls.directories)
    problems = list(settlement.problems)
    problems.extend(claim.publication.restore())
    if settlement.proven:
        problems.extend(claim.controls.restore())
    else:
        kept = DETAIL_CONTROLS_KEPT.format(control=claim.controls.root)
        problems.append(kept)
        claim.retain(kept)
    try:
        creation.leave_project(claim.observer, claim.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    problems.extend(claim.publication.candidate_unchanged())
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        claim.publication.note("cleanup-problems", "; ".join(problems))
