"""Journey B1 of the workflow acceptance: an explicit prepare starts the real driver, which claims with its reservation.

The journey's assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/b1-claim-assertion-draft.md`, approved at exact SHA-256
8139046b04adbf9219f29b472e8bb49e513da9cd7946ee60ddfaf0bb964df1e6; authority the pending
`local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and `.../procedure-entry` contracts of issue 128).
It proves, on a disposable installation whose published drivers are the four folded procedures, that the public
`telec todo prepare` starts one platform-created driver session, that the driver's own fresh public `telec todo prepare`
claim is accepted with its reservation and renders the instruction, that exactly one claim note exists, that a second
caller is refused naming the holder without any write, and that ending the session releases the claim.

It proves no racing start, no start-in-progress refusal, no model following of procedures, no event count, no whole
delivery and no starter-result coverage when step 6 is not evaluated. The driver runs as the inert external executable of
journey F0 with a reviewed command plan of public `telec` argv only; this controller creates no session record, role,
reservation, identity or authentication state, reads no private store and imports no application module.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_foundation as foundation
from tools.ci.workflow_foundation import FoundationHost, Outcome

TELEC: Final = "bin/telec"
GIT: Final = "git"
UV: Final = "uv"
DOCS: Final = "docs"
GET: Final = "get"
TARGET_OPTION: Final = "--target"
PENDING_TARGET: Final = "issue-128"
OPERATIONS: Final = "operations"
TODO: Final = "todo"
PREPARE: Final = "prepare"
SESSIONS: Final = "sessions"
SHOW: Final = "show"
FULL_FLAG: Final = "--full"
CODE: Final = "code"
LINT: Final = "lint"
ALL_FLAG: Final = "--all"
INSTALL_MODULE: Final = "teleclaude.entrypoints.install_publication"
CLONE_NAME: Final = "b1-publication-fixture"
CONTROL_NAME: Final = "native-fixture-control-b1"
GIT_AUTHOR: Final = "Runtime Acceptance Fixture"
GIT_EMAIL: Final = "runtime-acceptance@example.invalid"
ENVIRONMENT_DIRECTORY: Final = Path(".venv")
DOCS_ROOT: Final = Path("docs") / "global"
COMPANION_SUFFIX: Final = ".issue-128.md"
LIVE_SUFFIX: Final = ".md"

ITEM: Final = "b1-item"
CONTENT: Final = "b1 driver content"
DRIVER_ID: Final = "sdlc/procedure/lifecycle/prepare/overview-v2"
FOLD_IDS: Final = (
    DRIVER_ID,
    "sdlc/procedure/lifecycle/prepare/intake-v2",
    "sdlc/procedure/lifecycle/work/overview-v2",
    "sdlc/procedure/lifecycle/work/build-v2",
)
ROLE: Final = "prepare-orchestrator"
PHASE: Final = "preparation"
CLAIM_NAME: Final = "claim"
CLAIM_FRAME: Final = "cmd_claim"
CLAIM_ARGV: Final = ("telec", TODO, PREPARE, ITEM)
PLAN_FILE: Final = "plan.json"
NO_DRIVER_PHRASE: Final = "no published procedure drives preparation"
NOT_ACTIVATED_PHRASE: Final = "is not activated yet"
CLAIM_HEADER_SUFFIX: Final = " · claim"
CLAIM_HEADER_PREFIX: Final = "### "

FIELD_OPERATION: Final = "operation_id"
FIELD_STATE: Final = "state"
FIELD_ERROR: Final = "error"
FIELD_RESULT: Final = "result"
FIELD_ROLE: Final = "role"
FIELD_JOB: Final = "job"
FIELD_STANDING: Final = "standing"
FIELD_HELD_BY: Final = "held_by"
FIELD_HELD_SINCE: Final = "held_since"
FIELD_LOG: Final = "log"
STATE_COMPLETED: Final = "completed"
STATE_FAILED: Final = "failed"
TERMINAL_STATES: Final = frozenset({"completed", "failed", "stale", "cancelled"})

CLI_TIMEOUT_SECONDS: Final = 60
CLONE_TIMEOUT_SECONDS: Final = 60
LINT_TIMEOUT_SECONDS: Final = 180
PUBLISH_TIMEOUT_SECONDS: Final = 120
ACTIVATION_WAIT_SECONDS: Final = 180.0
ACTIVATION_POLL_SECONDS: Final = 20.0
START_CAP_SECONDS: Final = 900.0
POLL_SECONDS: Final = 2.0
CLAIM_OPERATION_SECONDS: Final = 120.0
STARTER_WINDOW_SECONDS: Final = 100.0
STARTER_SETTLE_SECONDS: Final = 20.0
COMPETITOR_SECONDS: Final = 60.0
RELEASE_SECONDS: Final = 120.0
QUIESCENCE_GAP_SECONDS: Final = 2.0
SETTLE_SECONDS: Final = 5.0

DETAIL_COMMAND: Final = "`{command}` exited {status}: {output!r}"
DETAIL_IDENTITY_MOVED: Final = "the candidate checkout changed during the journey: {before!r} became {after!r}"
DETAIL_FOLD_PATHS: Final = (
    "the fold changed {found!r}, not exactly the four live files modified and four companions deleted"
)
DETAIL_FOLD_DIRTY: Final = "the fixture clone is not clean after the fold commit: {status!r}"
DETAIL_NO_BODY: Final = "`telec docs get {identity}` printed no snippet body: {output!r}"
DETAIL_BODY_MISMATCH: Final = "the published body of {identity} differs from the {expected}"
DETAIL_ACTIVATION: Final = (
    "the store was not activated and the drivers still unpublished within {seconds} seconds: {last!r}"
)
DETAIL_NEGATIVE_STATE: Final = (
    "the pre-publication prepare ended {state!r} with {error!r}, not the driver-lookup refusal"
)
DETAIL_NEGATIVE_WRITE: Final = "the pre-publication prepare changed the item or the sessions: {detail}"
DETAIL_RECEIPT: Final = "`telec todo prepare` printed no operation receipt: exit {status}, {output!r}"
DETAIL_OPERATION_FAILED: Final = "operation {operation} failed: {error!r}"
DETAIL_DRIVER_UNPUBLISHED: Final = (
    "the driver lookup refused after publication (the publication did not take effect): {error!r}"
)
DETAIL_START_TIMEOUT: Final = "no session claimed {item} within {seconds} seconds"
DETAIL_SESSIONS: Final = "sessions after the start minus the baseline are {found!r}, not exactly the claiming session"
DETAIL_RECORD_FIELD: Final = "the claiming session's record has {field} {found!r}, not {expected!r}"
DETAIL_RECORD_START: Final = "the claiming session's record does not show a completed startup: {record!r}"
DETAIL_FIRST_INPUT: Final = "the fixture's first input does not name {identity}: {text!r}"
DETAIL_CLAIM_FRAME: Final = "the fixture's claim frame is not the planned successful call: {frame!r}"
DETAIL_CLAIM_RECEIPT: Final = "the driver's claim printed no distinct operation receipt: {stdout!r} (starter {starter})"
DETAIL_OPERATION_TIMEOUT: Final = "operation {operation} did not complete within {seconds} seconds: {last!r}"
DETAIL_RESULT_TYPE: Final = "operation {operation} result is not a string: {result!r}"
DETAIL_INSTRUCTION: Final = "the claim instruction does not contain {needle!r}: {text!r}"
DETAIL_HOLD: Final = "after the claim {path} is {found!r}, not {expected!r}"
DETAIL_PATH_ABSENT: Final = "the shown payload has no {path} (a source-traced path)"
DETAIL_LOG_CLAIMS: Final = "the log holds {count} claim entries, not exactly one: {log!r}"
DETAIL_LOG_ENTRY: Final = "the claim entry does not name {needle!r}: {entry!r}"
DETAIL_STARTER: Final = "the starter's operation result does not contain the session: {result!r}"
DETAIL_COMPETITOR_STATE: Final = "the competing prepare ended {state!r} ({error!r}), not a refusal naming the holder"
DETAIL_COMPETITOR_TEXT: Final = "the refusal does not name {needle!r}: {error!r}"
DETAIL_WRITE: Final = "the item shown {when} differs from before the competing prepare; differing paths: {paths}"
DETAIL_RELEASE: Final = "the claim was not released within {seconds} seconds: {holder!r}"
DETAIL_PHASE_AFTER: Final = "after the close the item reads {found!r}, not {expected!r}"
DETAIL_COMPANION: Final = "the companion {path} has no readable workflow header"
NOT_EVALUATED_STARTER: Final = "step 6 not evaluated: {reason}"
NOT_EVALUATED_LABEL: Final = "step-6-not-evaluated"

type Json = Mapping[str, object]


def _text(output: str) -> str:
    return output.replace("\r\n", "\n")


def docs_body(output: str) -> str | None:
    """The snippet body of a `telec docs get` response: everything after its metadata block, line ends normalized."""
    lines = _text(output).split("\n")
    dividers = [index for index, line in enumerate(lines) if line.strip() == "---"]
    if len(dividers) < 2:
        return None
    return "\n".join(lines[dividers[1] + 1 :]).strip()


_CHILD_LINE = re.compile(r"^\s+child:\s*(?P<child>\S+)\s*$")
_ACT_LINE = re.compile(r"^\s+-\s+act:\s*(?P<act>\S+)\s*$")
_LEADS_LINE = re.compile(r"^\s+leads_to:\s*(?P<phase>\S+)\s*$")
_ACTS_KEY = re.compile(r"^\s+acts:\s*$")


def declared_acts(path: Path) -> tuple[list[tuple[str, str]], str]:
    """The ending acts with their phases, and the child procedure, the folded driver's `workflow` header declares.

    The header is the YAML block between the first two `---` lines; only the `workflow:` mapping is read, line by line,
    because the hosted harness runs on the standard library alone.
    """
    parts = path.read_text(encoding="utf-8").split("---", 2)
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


class _Claim:
    """One run of journey B1."""

    def __init__(
        self, host: FoundationHost, setup: foundation.FixtureSetup, project: Path, source_root: Path, owner_email: str
    ) -> None:
        self.host = host
        self.observer = creation.Observer(host)
        self.setup = setup
        self.project = project.resolve()
        self.source_root = source_root
        self.owner_email = owner_email
        self.control = setup.control.parent / CONTROL_NAME
        self.clone: Path | None = None
        self.published = False
        self.original_configuration = setup.configuration.read_text(encoding="utf-8")
        self.live_bodies: dict[str, str] = {}
        self.journey: foundation.Journey | None = None

    # -- process helpers -------------------------------------------------------------------------------------------
    def _run(self, argv: Sequence[str], cwd: Path, timeout: float, *, what: str) -> Outcome:
        outcome = self.host.process(argv, cwd, self.host.environment, timeout)
        if outcome.exit_status != 0:
            raise creation.binding_failure(
                DETAIL_COMMAND.format(command=what, status=outcome.exit_status, output=outcome.output[-400:])
            )
        return outcome

    def _identity(self) -> str:
        head = self._run((GIT, "rev-parse", "HEAD"), self.source_root, CLONE_TIMEOUT_SECONDS, what="git rev-parse HEAD")
        tree = self._run(
            (GIT, "rev-parse", "HEAD^{tree}"), self.source_root, CLONE_TIMEOUT_SECONDS, what="git rev-parse tree"
        )
        return f"commit {head.output.strip()} tree {tree.output.strip()}"

    def _note(self, label: str, text: str) -> None:
        self.host.note((label,), Outcome(0, text), "")

    # -- documentation reads ---------------------------------------------------------------------------------------
    def _body_of(self, identity: str, *, pending: bool, cwd: Path) -> str:
        self.observer.run(("cd", str(cwd)))
        argv = [TELEC, DOCS, GET, identity]
        if pending:
            argv.extend((TARGET_OPTION, PENDING_TARGET))
        outcome = self.observer.run(argv, retain=False)
        body = docs_body(outcome.output) if outcome.exit_status == 0 else None
        if not body:
            raise creation.binding_failure(DETAIL_NO_BODY.format(identity=identity, output=outcome.output[-300:]))
        return body

    # -- section 0: disposable publication -------------------------------------------------------------------------
    def prepare_clone(self) -> Path:
        temporary = self.setup.control.parent
        clone = temporary / CLONE_NAME
        shutil.rmtree(clone, ignore_errors=True)
        self._run(
            (GIT, "clone", "--quiet", "--shared", str(self.source_root), str(clone)),
            temporary,
            CLONE_TIMEOUT_SECONDS,
            what="git clone --shared",
        )
        environment = self.source_root / ENVIRONMENT_DIRECTORY
        if not (environment / "bin" / "python").is_file():
            raise creation.binding_failure("the dependency environment of the source checkout is missing")
        (clone / ENVIRONMENT_DIRECTORY).symlink_to(environment, target_is_directory=True)
        self._run((GIT, "config", "user.name", GIT_AUTHOR), clone, CLONE_TIMEOUT_SECONDS, what="git config user.name")
        self._run((GIT, "config", "user.email", GIT_EMAIL), clone, CLONE_TIMEOUT_SECONDS, what="git config user.email")
        self.clone = clone
        return clone

    def fold(self, clone: Path) -> None:
        """B-P2: each companion's bytes over its live file, the companions removed, one commit of exactly eight paths."""
        for identity in FOLD_IDS:
            live = clone / DOCS_ROOT / f"{identity}{LIVE_SUFFIX}"
            companion = clone / DOCS_ROOT / f"{identity}{COMPANION_SUFFIX}"
            live.write_bytes(companion.read_bytes())
            self._run(
                (GIT, "rm", "--quiet", str(companion.relative_to(clone))),
                clone,
                CLONE_TIMEOUT_SECONDS,
                what="git rm",
            )
            self._run((GIT, "add", str(live.relative_to(clone))), clone, CLONE_TIMEOUT_SECONDS, what="git add")
        self._run(
            (GIT, "commit", "--quiet", "-m", "fold the four driver procedures"),
            clone,
            CLONE_TIMEOUT_SECONDS,
            what="git commit",
        )
        status = self._run((GIT, "status", "--porcelain"), clone, CLONE_TIMEOUT_SECONDS, what="git status")
        if status.output.strip():
            raise creation.binding_failure(DETAIL_FOLD_DIRTY.format(status=status.output.strip()))
        changed = self._run(
            (GIT, "diff", "--name-status", "HEAD~1", "HEAD"), clone, CLONE_TIMEOUT_SECONDS, what="git diff"
        )
        found = sorted(line.split() for line in changed.output.strip().splitlines() if line.strip())
        expected = sorted(
            [
                *(["M", f"{DOCS_ROOT / identity}{LIVE_SUFFIX}"] for identity in FOLD_IDS),
                *(["D", f"{DOCS_ROOT / identity}{COMPANION_SUFFIX}"] for identity in FOLD_IDS),
            ]
        )
        if found != expected:
            raise creation.binding_failure(DETAIL_FOLD_PATHS.format(found=found))
        sha = self._run((GIT, "rev-parse", "HEAD"), clone, CLONE_TIMEOUT_SECONDS, what="git rev-parse HEAD")
        self._note("fixture-publication-sha", sha.output.strip())

    def lint(self, clone: Path) -> None:
        """B-P3: the public documentation validation passes on the fold before it is published."""
        self._run(
            (str(self.source_root / TELEC), CODE, LINT, ALL_FLAG),
            clone,
            LINT_TIMEOUT_SECONDS,
            what="telec code lint --all",
        )

    def publish(self, checkout: Path) -> None:
        """Run the supported installation publication entry point for one committed checkout."""
        self._run(
            (UV, "--project", str(self.source_root), "--no-sync", "python", "-m", INSTALL_MODULE),
            checkout,
            PUBLISH_TIMEOUT_SECONDS,
            what="install_publication",
        )

    def _prepared_item(self) -> Json:
        shown = self.observer.show(ITEM)
        if shown is None:
            raise creation.platform_failure(f"{ITEM} is absent")
        return shown

    def negative_control(self, baseline: creation.SessionView, before: Json) -> None:
        """B-P5: the unpublished installation is refused at the driver lookup, writing nothing; the store is activated."""
        deadline = time.monotonic() + ACTIVATION_WAIT_SECONDS
        last = ""
        while True:
            outcome = self.observer.run((TELEC, TODO, PREPARE, ITEM))
            receipt = foundation.json_object(outcome.output)
            operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
            if outcome.exit_status == 0 and isinstance(operation, str) and operation:
                state = self._await_terminal(operation, 60.0)
                error = state.get(FIELD_ERROR)
                if state.get(FIELD_STATE) == STATE_FAILED and isinstance(error, str) and NO_DRIVER_PHRASE in error:
                    break
                if not (
                    state.get(FIELD_STATE) == STATE_FAILED and isinstance(error, str) and NOT_ACTIVATED_PHRASE in error
                ):
                    raise creation.binding_failure(
                        DETAIL_NEGATIVE_STATE.format(state=state.get(FIELD_STATE), error=error)
                    )
                last = str(error)
            elif NOT_ACTIVATED_PHRASE in outcome.output:
                last = outcome.output[-200:]
            else:
                raise creation.binding_failure(
                    DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
                )
            if time.monotonic() >= deadline:
                raise creation.binding_failure(
                    DETAIL_ACTIVATION.format(seconds=int(ACTIVATION_WAIT_SECONDS), last=last)
                )
            time.sleep(ACTIVATION_POLL_SECONDS)
        after = self._prepared_item()
        changed = creation.differences(before, after)
        sessions = self.observer.sessions()
        if changed or sessions.ids != baseline.ids:
            raise creation.binding_failure(DETAIL_NEGATIVE_WRITE.format(detail=changed or sorted(sessions.ids)))

    def _await_terminal(self, operation: str, seconds: float) -> Json:
        deadline = time.monotonic() + seconds
        last: Json = {}
        while time.monotonic() < deadline:
            outcome = self.observer.run((TELEC, OPERATIONS, GET, operation), retain=False)
            state = foundation.json_object(outcome.output)
            if outcome.exit_status == 0 and state is not None:
                last = state
                if state.get(FIELD_STATE) in TERMINAL_STATES:
                    self.observer.run((TELEC, OPERATIONS, GET, operation))
                    return state
            time.sleep(POLL_SECONDS)
        raise creation.platform_failure(
            DETAIL_OPERATION_TIMEOUT.format(operation=operation, seconds=int(seconds), last=last)
        )

    # -- per-launch control ----------------------------------------------------------------------------------------
    def install_control(self) -> foundation.FixtureSetup:
        """B-S2: a fresh control directory for this launch, with the reviewed command plan, and the sidecar pointed at it."""
        shutil.rmtree(self.control, ignore_errors=True)
        self.control.mkdir(parents=True)
        plan = {"commands": [{"name": CLAIM_NAME, "argv": list(CLAIM_ARGV)}]}
        (self.control / PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
        configuration = json.loads(self.original_configuration)
        configuration[foundation.CONFIG_CONTROL_DIRECTORY] = str(self.control)
        self.setup.configuration.write_text(json.dumps(configuration), encoding="utf-8")
        return foundation.FixtureSetup(self.setup.executable, self.setup.configuration, self.control)

    def restore_control(self) -> list[str]:
        failures: list[str] = []
        try:
            self.setup.configuration.write_text(self.original_configuration, encoding="utf-8")
        except OSError as error:
            failures.append(f"sidecar configuration: {type(error).__name__}")
        shutil.rmtree(self.control, ignore_errors=True)
        return failures


def _require_item_unclaimed(shown: Json) -> None:
    creation.require_value(ITEM, shown, "state.lifecycle_phase", PHASE)
    creation.require_value(ITEM, shown, "state.hold", False)
    creation.require_unclaimed(ITEM, shown)
    creation.require_standing_clear(ITEM, shown)


def _fresh_snapshot(observer: creation.Observer) -> Json:
    first = observer.show(ITEM)
    if first is None:
        raise creation.binding_failure(f"{ITEM} is absent before the competing call")
    time.sleep(QUIESCENCE_GAP_SECONDS)
    second = observer.show(ITEM)
    if second is None or creation.differences(first, second):
        raise creation.binding_failure(
            DETAIL_WRITE.format(when="between two reads", paths=creation.differences(first, second or {}))
        )
    return second


def _shown_with_content(observer: creation.Observer) -> Json:
    shown = observer.show(ITEM)
    if shown is None:
        raise creation.platform_failure(f"{ITEM} is absent")
    return shown


def _claim_entries(log: str) -> list[tuple[str, str]]:
    """The claim entries of a log as (header line, the body line after one blank line)."""
    lines = _text(log).split("\n")
    entries: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        if line.startswith(CLAIM_HEADER_PREFIX) and line.rstrip().endswith(CLAIM_HEADER_SUFFIX):
            body = lines[index + 2] if index + 2 < len(lines) and not lines[index + 1].strip() else ""
            entries.append((line, body))
    return entries


def run_claim(
    host: FoundationHost, setup: foundation.FixtureSetup, project: Path, source_root: Path, owner_email: str
) -> None:
    """Journey B1; raises JourneyFailure leading with its class."""
    claim = _Claim(host, setup, project, source_root, owner_email)
    observer = claim.observer
    candidate = claim._identity()
    claim._note("candidate-identity", candidate)
    failure: BaseException | None = None
    journey: foundation.Journey | None = None
    live_ids: dict[str, str] = {}
    try:
        creation.require_manual_runner(observer)
        creation.enter_project(observer, project)
        baseline = observer.sessions()
        launch_setup = claim.install_control()
        journey = foundation.Journey(host, launch_setup, project, owner_email)
        claim.journey = journey
        creation.require_created(creation.create_item(observer, ITEM, CONTENT, "feature", approved=True), ITEM)
        before = _shown_with_content(observer)
        _require_item_unclaimed(before)
        live_ids.update({identity: claim._body_of(identity, pending=False, cwd=source_root) for identity in FOLD_IDS})
        clone = claim.prepare_clone()
        claim.fold(clone)
        claim.lint(clone)
        pending = {identity: claim._body_of(identity, pending=True, cwd=source_root) for identity in FOLD_IDS}
        creation.enter_project(observer, project)
        claim.negative_control(baseline, before)
        claim.publish(clone)
        claim.published = True
        for identity in FOLD_IDS:
            published = claim._body_of(identity, pending=False, cwd=source_root)
            if published != pending[identity]:
                raise creation.binding_failure(
                    DETAIL_BODY_MISMATCH.format(identity=identity, expected="pending body captured before publication")
                )
        creation.enter_project(observer, project)
        quiet = _fresh_snapshot(observer)
        if creation.differences(before, quiet):
            raise creation.binding_failure(
                DETAIL_WRITE.format(when="after publication", paths=creation.differences(before, quiet))
            )
        _Steps(claim, journey, baseline, launch_setup, clone).run()
    except BaseException as error:
        failure = error
        raise
    finally:
        _cleanup(claim, journey, candidate, failure, live_ids)


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
        self.baseline = baseline
        self.launch_setup = launch_setup
        self.clone = clone
        self.started_at = 0.0
        self.starter = ""
        self.session = ""
        self.claim_seen = 0.0

    def run(self) -> None:
        self.start()
        self.await_claim()
        native = self.check_startup()
        del native
        instruction = self.driver_claim()
        self.check_instruction(instruction)
        self.observe_claim()
        self.starter_result()
        self.competitor()
        self.close()

    def start(self) -> None:
        """Step 1: the public start returns a receipt."""
        self.started_at = time.monotonic()
        start = self.observer.run((TELEC, TODO, PREPARE, ITEM))
        receipt = foundation.json_object(start.output)
        starter = receipt.get(FIELD_OPERATION) if receipt is not None else None
        if start.exit_status != 0 or not isinstance(starter, str) or not starter:
            raise creation.platform_failure(DETAIL_RECEIPT.format(status=start.exit_status, output=start.output[-300:]))
        self.starter = starter

    def await_claim(self) -> None:
        """Step 2: a real session is created and claims; a failed starter ends the wait at once."""
        deadline = self.started_at + START_CAP_SECONDS
        while time.monotonic() < deadline:
            shown = self.observer.show(ITEM, retain=False)
            holder = creation.dig(shown, "state.active_runner")[1] if shown is not None else None
            if isinstance(holder, str) and holder:
                self.session = holder
                self.claim_seen = time.monotonic()
                self.journey.session_id = holder
                return
            state = (
                foundation.json_object(self.observer.run((TELEC, OPERATIONS, GET, self.starter), retain=False).output)
                or {}
            )
            if state.get(FIELD_STATE) == STATE_FAILED:
                error = str(state.get(FIELD_ERROR))
                if NO_DRIVER_PHRASE in error:
                    raise creation.binding_failure(DETAIL_DRIVER_UNPUBLISHED.format(error=error))
                raise creation.platform_failure(DETAIL_OPERATION_FAILED.format(operation=self.starter, error=error))
            time.sleep(POLL_SECONDS)
        raise creation.platform_failure(DETAIL_START_TIMEOUT.format(item=ITEM, seconds=int(START_CAP_SECONDS)))

    def check_startup(self) -> str:
        """Step 3: the session is the platform's, with a real startup through the installed hooks."""
        created = self.observer.sessions().ids - self.baseline.ids
        if created != frozenset({self.session}):
            raise creation.platform_failure(DETAIL_SESSIONS.format(found=sorted(created)))
        journey = self.journey
        launch = journey.await_json(self.launch_setup.control / foundation.LAUNCH_FILE, foundation.POLL_SECONDS * 30)
        owned = str(self.launch_setup.executable.resolve())
        found = (Path(str(launch.get("executable"))).resolve(), Path(str(launch.get("resolved_command"))).resolve())
        if found != (Path(owned), Path(owned)):
            raise creation.binding_failure(foundation.DETAIL_EXECUTABLE.format(found=launch, owned=owned))
        native = str(launch.get("native_session_id"))
        frames_deadline = time.monotonic() + START_CAP_SECONDS
        for name in (foundation.FRAME_SESSION_START, foundation.FRAME_PROMPT_SUBMIT):
            journey.require_hook(name, journey.await_frame(name, frames_deadline))
        record = journey.record()
        if record is None or not journey.started(record, native):
            raise creation.platform_failure(DETAIL_RECORD_START.format(record=record))
        for field, expected in ((FIELD_ROLE, ROLE), (FIELD_JOB, DRIVER_ID)):
            if record.get(field) != expected:
                raise creation.platform_failure(
                    DETAIL_RECORD_FIELD.format(field=field, found=record.get(field), expected=expected)
                )
        inputs = journey.inputs()
        first = inputs[0].get("text") if inputs else None
        if not isinstance(first, str) or DRIVER_ID not in first:
            raise creation.platform_failure(DETAIL_FIRST_INPUT.format(identity=DRIVER_ID, text=first))
        return native

    def driver_claim(self) -> str:
        """Step 4: the driver's own claim, run in its pane, completes and returns the instruction text."""
        frame = self.journey.await_frame(CLAIM_FRAME, time.monotonic() + CLAIM_OPERATION_SECONDS)
        run = frame.get("run")
        argv = frame.get("argv")
        stdout = run.get("stdout") if isinstance(run, dict) else None
        receipt = foundation.json_object(stdout) if isinstance(stdout, str) else None
        operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
        if (
            not isinstance(run, dict)
            or run.get("exit_status") != 0
            or run.get("timed_out") is True
            or not isinstance(argv, list)
            or tuple(argv) != CLAIM_ARGV
        ):
            raise creation.platform_failure(DETAIL_CLAIM_FRAME.format(frame=frame))
        if not isinstance(operation, str) or not operation or operation == self.starter:
            raise creation.platform_failure(DETAIL_CLAIM_RECEIPT.format(stdout=stdout, starter=self.starter))
        claimed = self.claim._await_terminal(operation, CLAIM_OPERATION_SECONDS)
        if claimed.get(FIELD_STATE) != STATE_COMPLETED:
            raise creation.platform_failure(
                DETAIL_OPERATION_FAILED.format(operation=operation, error=claimed.get(FIELD_ERROR))
            )
        instruction = claimed.get(FIELD_RESULT)
        if not isinstance(instruction, str):
            raise creation.platform_failure(DETAIL_RESULT_TYPE.format(operation=operation, result=instruction))
        return instruction

    def check_instruction(self, instruction: str) -> None:
        """Step 4, content: the item, phase, session, every ending act with its phase, and the child procedure."""
        acts, child = declared_acts(self.clone / DOCS_ROOT / f"{DRIVER_ID}{LIVE_SUFFIX}")
        for needle in (ITEM, PHASE, self.session, child, *(name for pair in acts for name in pair)):
            if needle not in instruction:
                raise creation.platform_failure(DETAIL_INSTRUCTION.format(needle=needle, text=instruction[-600:]))

    def observe_claim(self) -> None:
        """Step 5: the item shows the holder, the phase, and exactly one claim note naming the session."""
        held = _shown_with_content(self.observer)
        session = self.session
        creation.require_value(ITEM, held, "state.active_runner", session)
        creation.require_value(ITEM, held, f"{FIELD_STANDING}.{FIELD_HELD_BY}", session)
        found, since = creation.dig(held, f"{FIELD_STANDING}.{FIELD_HELD_SINCE}")
        if not found:
            raise creation.trace_failure(DETAIL_PATH_ABSENT.format(path=f"{FIELD_STANDING}.{FIELD_HELD_SINCE}"))
        if not isinstance(since, str) or not since:
            raise creation.platform_failure(
                DETAIL_HOLD.format(path="standing.held_since", found=since, expected="non-empty")
            )
        creation.require_value(ITEM, held, "state.lifecycle_phase", PHASE)
        creation.require_value(ITEM, held, f"{FIELD_STANDING}.phase", PHASE)
        creation.require_value(ITEM, held, "state.hold", False)
        _, log = creation.dig(held, f"artifact_content.{FIELD_LOG}")
        if not isinstance(log, str):
            raise creation.trace_failure(DETAIL_PATH_ABSENT.format(path=f"artifact_content.{FIELD_LOG}"))
        entries = _claim_entries(log)
        if len(entries) != 1:
            raise creation.platform_failure(DETAIL_LOG_CLAIMS.format(count=len(entries), log=log[-600:]))
        header, body = entries[0]
        if session not in header:
            raise creation.platform_failure(DETAIL_LOG_ENTRY.format(needle=session, entry=header))
        for needle in (ITEM, session):
            if needle not in body:
                raise creation.platform_failure(DETAIL_LOG_ENTRY.format(needle=needle, entry=body))

    def starter_result(self) -> None:
        """Step 6: the starter's own result names the session, evaluated only inside the attach window."""
        if self.claim_seen - self.started_at > STARTER_WINDOW_SECONDS:
            self._not_evaluated("the claim was observed after the attach window")
            return
        state = _terminal_within(self.claim, self.starter, STARTER_SETTLE_SECONDS)
        if state is None:
            self._not_evaluated("the starter was not terminal")
            return
        if state.get(FIELD_STATE) != STATE_COMPLETED:
            raise creation.platform_failure(
                DETAIL_OPERATION_FAILED.format(operation=self.starter, error=state.get(FIELD_ERROR))
            )
        result = state.get(FIELD_RESULT)
        if not isinstance(result, str):
            raise creation.platform_failure(DETAIL_RESULT_TYPE.format(operation=self.starter, result=result))
        if self.session not in result:
            raise creation.platform_failure(DETAIL_STARTER.format(result=result))

    def _not_evaluated(self, reason: str) -> None:
        text = NOT_EVALUATED_STARTER.format(reason=reason)
        self.host.note((NOT_EVALUATED_LABEL,), Outcome(None, text), "")

    def competitor(self) -> None:
        """Step 7: a second entry call is refused naming the holder, and nothing is written."""
        observer = self.observer
        snapshot = _fresh_snapshot(observer)
        held_sessions = observer.sessions()
        competitor = observer.run((TELEC, TODO, PREPARE, ITEM))
        receipt = foundation.json_object(competitor.output)
        operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
        if competitor.exit_status != 0 or not isinstance(operation, str) or not operation:
            raise creation.platform_failure(
                DETAIL_RECEIPT.format(status=competitor.exit_status, output=competitor.output[-300:])
            )
        refused = self.claim._await_terminal(operation, COMPETITOR_SECONDS)
        error = refused.get(FIELD_ERROR)
        if refused.get(FIELD_STATE) != STATE_FAILED or not isinstance(error, str):
            raise creation.platform_failure(DETAIL_COMPETITOR_STATE.format(state=refused.get(FIELD_STATE), error=error))
        for needle in (ITEM, self.session):
            if needle not in error:
                raise creation.platform_failure(DETAIL_COMPETITOR_TEXT.format(needle=needle, error=error))
        for when, pause in (("immediately", 0.0), ("five seconds later", SETTLE_SECONDS)):
            if pause:
                time.sleep(pause)
            changed = creation.differences(snapshot, _shown_with_content(observer))
            if changed:
                raise creation.platform_failure(DETAIL_WRITE.format(when=when, paths=changed))
            creation.require_sessions_equal(held_sessions, observer.sessions(retain=False), when)

    def close(self) -> None:
        """Step 8: ending the session releases the claim and leaves the phase unchanged."""
        self.journey.end_session()
        deadline = time.monotonic() + RELEASE_SECONDS
        holder: object = self.session
        while time.monotonic() < deadline:
            released = self.observer.show(ITEM, retain=False)
            holder = creation.dig(released, "state.active_runner")[1] if released is not None else holder
            if holder in (None, ""):
                break
            time.sleep(POLL_SECONDS)
        else:
            raise creation.platform_failure(DETAIL_RELEASE.format(seconds=int(RELEASE_SECONDS), holder=holder))
        creation.require_value(ITEM, _shown_with_content(self.observer), "state.lifecycle_phase", PHASE)


def _terminal_within(claim: _Claim, operation: str, seconds: float) -> Json | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = foundation.json_object(claim.observer.run((TELEC, OPERATIONS, GET, operation), retain=False).output)
        if state is not None and state.get(FIELD_STATE) in TERMINAL_STATES:
            claim.observer.run((TELEC, OPERATIONS, GET, operation))
            return state
        time.sleep(POLL_SECONDS)
    return None


def _cleanup(
    claim: _Claim,
    journey: foundation.Journey | None,
    candidate: str,
    failure: BaseException | None,
    live_bodies: dict[str, str],
) -> None:
    """Close what the journey left open, restore the candidate publication and the sidecar, report every failure."""
    problems: list[str] = []
    if journey is not None:
        journey.release_session()
    if claim.published:
        try:
            claim.publish(claim.source_root)
            for identity, body in live_bodies.items():
                restored = claim._body_of(identity, pending=False, cwd=claim.source_root)
                if restored != body:
                    problems.append(DETAIL_BODY_MISMATCH.format(identity=identity, expected="candidate's live body"))
        except BaseException as error:  # the restore must report, not hide, the journey's own failure
            problems.append(f"restoring the candidate publication failed: {error}")
    problems.extend(claim.restore_control())
    if claim.clone is not None:
        shutil.rmtree(claim.clone, ignore_errors=True)
    try:
        creation.leave_project(claim.observer, claim.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    try:
        after = claim._identity()
        if after != candidate:
            problems.append(DETAIL_IDENTITY_MOVED.format(before=candidate, after=after))
    except BaseException as error:
        problems.append(f"re-reading the candidate identity failed: {error}")
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        claim._note("cleanup-problems", "; ".join(problems))
