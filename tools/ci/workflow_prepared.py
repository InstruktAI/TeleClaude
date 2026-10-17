"""Journey B4 of the workflow acceptance: prepared names the judged body, a moved body refuses, the work driver claims.

The journey\'s assertions are the independently reviewed ones recorded in the shared handoff workspace
(`journeys/b4-prepared-work-assertion-draft.md`, approved at exact SHA-256
468714c024b576157001c2a1563b9cb32a1abb74dd0dc1969c8bb435ac2bde89; it reuses the B1 draft
8139046b04adbf9219f29b472e8bb49e513da9cd7946ee60ddfaf0bb964df1e6 with its act-row amendment
d7270641fcb963b66f58c79201ac936d293358665b967f493a7e625a3eac0728 and title amendment
f9a4d846c18e44c8d5a65082532a2e0245ab357b4f33254843977e6db81e600f, the B2 pool, and the B3 late-bound argument lists;
the fixture preparation of amendment B4G, `journeys/b4g-docs-capability-fixture-amendment-draft.md` at exact SHA-256
781033c73aab429302e5716df959c089b8e34ccbcb871212f93097ac1af02d2b (the owned project declares the docs capability, with
code and agents disabled, committed and published before the item branch opens);
authority the pending `local/projects/teleclaude/spec/feature/workflow/item-lifecycle` and `.../procedure-entry`
contracts of issue 128).

It continues the item journey B3 left in preparation. A new preparation driver and its live author hold the claim; the
owner moves the body; `prepared` at the old digest is refused and writes nothing; `prepared` at the current digest
closes the live author and releases the claim; after the owner ends the driver, a body moved again refuses `work`
naming both digests and starts nothing; the exact prepared body is restored; and one real work driver claims, with its
worktree and opening commit read by real `git`.

Its close follows amendment A4, `journeys/b2-b3-b4-close-hold-handover-amendment-rev2-draft.md` at exact SHA-256
6871ce0dae59a98e6c24f3de945b3f2e2cb51c74daf847a2ee96820f8f522b21 (see `workflow_handover`): the owner\'s manual end of
a holding driver sets the session-close hold, which the case classifies and releases explicitly before it ends.

It proves no event, no stamp, ready or delivery, no builder child, no model following and no intermediate sweep order.
The Git base, main branch and owned bare origin are controller-owned fixture preparation by the real `git`
executable. This controller creates no session record, role, reservation, identity or authentication state, reads no
private store and imports no application module.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from tools.ci import acceptance_work as payload_work
from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_events as events
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_handover as handover
from tools.ci import workflow_items as items
from tools.ci import workflow_ledger as start_ledger
from tools.ci import workflow_publication as publication
from tools.ci import workflow_waiting as waiting
from tools.ci.workflow_foundation import FoundationHost

TELEC: Final = "bin/telec"
NATIVE_TELEC_COMMAND: Final = "telec"
GIT: Final = "git"
CONFIG: Final = "config"
PROJECT: Final = "project"
GET: Final = "get"
FORMAT_OPTION: Final = "--format"
JSON_FORMAT: Final = "json"
REVISION_OPTION: Final = "--revision"
YAML_OPTION: Final = "--yaml"
PROJECT_SECTION: Final = "project"
REVISION_FIELD: Final = "revision"
CAPABILITY_DOCS: Final = "docs"
CAPABILITY_CODE: Final = "code"
CAPABILITY_AGENTS: Final = "agents"
CAPABILITY_NOTE: Final = "docs-capability"
HOOK_NAMES: Final = ("pre-commit", "post-commit", "post-merge")
TODO: Final = "todo"
ITEM: Final = waiting.ITEM
CONTROL_NAME: Final = "native-fixture-control-b4"
ORIGIN_NAME: Final = "b4-origin.git"
RETAINED_NAME: Final = "RETAINED.json"
B4_ATTEMPT_LEDGER: Final = "b4-attempts.jsonl"
B4_CASE: Final = "B4"
B9_BODY_C: Final = "b4 body zero"
B9_S_P_MESSAGE: Final = "b9 outsider parent"
B9_X_MESSAGE: Final = "b9 outsider actor"
B9_X_INPUT: Final = "B9 outsider attempt"
B9_PREPARED_TEXT: Final = "B9 wrong performer"
B9_WAITING_TEXT: Final = "B9 waiting probe"
GATE_X_START: Final = "go_x_start"
GATE_X_INPUT: Final = "go_x_input"
GATE_C2_INPUT: Final = "go_c2_input"
GATE_C2_PREPARED: Final = "go_c2_prepared"
GATE_C2_WAITING: Final = "go_c2_waiting"
ARGV_X_START: Final = "x_start.argv"
ARGV_X_INPUT: Final = "x_input.argv"
ARGV_C2_INPUT: Final = "c2_input.argv"
ARGV_C2_PREPARED: Final = "c2_prepared.argv"
ARGV_C2_WAITING: Final = "c2_waiting.argv"
SESSION_S_P: Final = "session-S_P-start"
SESSION_X: Final = "session-X-start"
EFFECT_C2_INPUT: Final = "effect-C2-input"
EFFECT_X_INPUT: Final = "effect-X-input"
EFFECT_C2_PREPARED: Final = "effect-C2-prepared"
EFFECT_C2_WAITING: Final = "effect-C2-waiting"
END_X: Final = "session-X-end"
END_S_P: Final = "session-S_P-end"
FIELD_DELIVERED: Final = "delivered"
BODY_A: Final = "b4 body one"
BODY_B: Final = "b4 body two"
INPUT: Final = creation.INPUT_ARTIFACT
COMPLETE_ENDING: Final = re.compile(r"^Performed prepared on b3-item.*, complete\s*$", re.MULTILINE)
B9_CALLER_IDENTITY_OPENING_RE: Final = re.compile(
    r"\[(?:Orchestrator|Integrator|System|Worker|Tasker|Job Runner|Agent)(?: - [^\]\n]+)? \([^\]\n]+\) on [^\]\n]+(?: · [^\]\n]+)?\]"
)
B9_RENDERER_SEPARATOR: Final = "\n\n"
B9_CALLER_CLOSING_TEMPLATE: Final = "[/{header}]"
B9_STARTUP_INPUT_MISMATCH: Final = "the startup input does not match its declared message and caller envelope"
WORK_DRIVER_ID: Final = "sdlc/procedure/lifecycle/work/overview-v2"
WORK_PHASE: Final = "work"
PREPARED_PHASE: Final = "prepared"
PREPARATION_PHASE: Final = "preparation"
GIT_NAME: Final = "Runtime Acceptance Fixture"
GIT_EMAIL: Final = "runtime-acceptance@example.invalid"
MAIN: Final = "main"
ORIGIN: Final = "origin"
BASE_FILE: Final = "teleclaude.yml"

GATE_OLD: Final = "go_old"
GATE_NEW: Final = "go_new"
ARGV_OLD: Final = "preparedold.argv"
ARGV_NEW: Final = "preparednew.argv"
FRAME_OLD: Final = "cmd_preparedold"
FRAME_NEW: Final = "cmd_preparednew"
OWNER_WRITE_PATHS: Final = ("artifact_content.input", "artifact_state.input", items.ROADMAP_UPDATED_AT)
UPDATED_AT: Final = items.ROADMAP_UPDATED_AT
UPDATED_BY: Final = "artifact_state.input.updated_by"
WROTE_PHRASE: Final = "Wrote input for b3-item"
OPENING_SUBJECT: Final = "chore(worktree): open b3-item"

GIT_TIMEOUT_SECONDS: Final = 60
OBSERVATION_SECONDS: Final = 30.0
WORKTREE_SECONDS: Final = 60.0
OPERATION_SECONDS: Final = 60.0
POLL_SECONDS: Final = 2.0
FRAME_SECONDS: Final = 60.0

DETAIL_PROJECT_READ: Final = (
    "`telec config project get` did not return a project view and revision: exit {status}, {output!r}"
)
DETAIL_PROJECT_PATCH: Final = "the public project patch enabling docs failed: exit {status}, {output!r}"
DETAIL_CAPABILITY: Final = "{where} does not carry docs enabled with code and agents disabled: {found!r}"
DETAIL_HOOK: Final = (
    "the owned project has a git hook or hook path ({what}); the fixture never removes hooks or relaxes a floor"
)
DETAIL_BRANCH_NOTE: Final = "the work claim note does not state {note!r}: {entry!r}"
DETAIL_GIT: Final = "git {step} failed: {args!r} exit {status}: {output!r}"
DETAIL_ORIGIN: Final = "git read-back {what}: {found!r}, not {expected!r}"
DETAIL_PRECONDITION: Final = "{item}: {path} is {found!r}, not {expected!r} at the start of B4"
DETAIL_WRITE: Final = "`telec todo artifacts write` exited {status} without {phrase!r}: {output!r}"
DETAIL_BODY: Final = "the stored input reads {found!r}, not {expected!r}"
DETAIL_DIGEST_SAME: Final = "the digest of the moved body equals the digest it replaced: {digest}"
DETAIL_UPDATED_BY: Final = "artifact_state.input.updated_by is {found!r}; an owner-terminal write records no session"
DETAIL_UPDATED_SESSION: Final = "artifact_state.input.updated_by names the session {found!r}, but the owner wrote it"
DETAIL_CLOCK: Final = "roadmap.updated_at moved backwards from {before!r} to {after!r}"
DETAIL_REFUSAL: Final = "{case}: {problem}: exit {status}, {output!r}"
DETAIL_CHANGED: Final = "{when}: the item differs from the snapshot at {paths}"
DETAIL_LOG_HEADERS: Final = "{when}: the log headers changed: {before!r} became {after!r}"
DETAIL_LOG_ADDED: Final = "{when}: the log gained {added!r}, not exactly one header ending {suffix!r} naming {session}"
DETAIL_LIVE: Final = "{actor} {session} {problem}: {record!r}"
DETAIL_WORK_REFUSED: Final = (
    "the work entry on a moved body ended {state!r} ({error!r}), not a refusal naming {needles!r}"
)
DETAIL_WORKTREE: Final = "{what}: {found!r}, not {expected!r}"
DETAIL_INSTRUCTION: Final = "the work instruction lacks {needle!r}: {text!r}"
DETAIL_ROLE_COUNT: Final = "{count} sessions beyond the baseline hold the work role, not exactly one: {found!r}"
DETAIL_CONTROLS_KEPT: Final = "closure was not proven, so the control directories {control} are kept for diagnosis"
DETAIL_NOT_PRESENT: Final = "{what} is not available through the supported git read-backs"
DETAIL_B9_REFUSAL: Final = "B9 {act} refusal is {status!r} and lacks {expected!r}: {output!r}"
DETAIL_B9_SESSION: Final = "B9 session {label} is not bound to its first-free control: {record!r}"
DETAIL_B9_ATTEMPT: Final = "the B4 B9 attempt ledger is unresolved: {detail}"
DETAIL_B9_RETAINED: Final = "B4 retained the full runtime because B9 evidence is unresolved at {path}"
DETAIL_B9_END: Final = "B9 session {session} end did not complete and close its retained record: {record!r}"

B4_B9_ACTIONS: Final = (
    {"label": SESSION_S_P, "kind": start_ledger.RECORD_SESSION},
    {"label": SESSION_X, "kind": start_ledger.RECORD_SESSION, "parent": SESSION_S_P},
    {"label": EFFECT_C2_INPUT, "kind": start_ledger.RECORD_EFFECT},
    {"label": EFFECT_X_INPUT, "kind": start_ledger.RECORD_EFFECT},
    {"label": EFFECT_C2_PREPARED, "kind": start_ledger.RECORD_EFFECT},
    {"label": EFFECT_C2_WAITING, "kind": start_ledger.RECORD_EFFECT},
    {"label": END_X, "kind": start_ledger.RECORD_OPERATION},
    {"label": END_S_P, "kind": start_ledger.RECORD_OPERATION},
)

type Json = Mapping[str, object]


def digest(text: str) -> str:
    """The SHA-256 hex of the text encoded as UTF-8: the definition the platform compares."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capability_enabled(view: Mapping[str, object], name: str) -> bool:
    """Whether a public project view declares the named capability enabled."""
    block = view.get(name)
    return isinstance(block, Mapping) and block.get("enabled") is True


def text_capability_enabled(text: str, name: str) -> bool:
    """Whether a committed declaration enables the capability, in block or flow form, by plain text."""
    lines = text.replace("\r\n", "\n").split("\n")
    for index, line in enumerate(lines):
        if not line.startswith(f"{name}:"):
            continue
        rest = line.partition(":")[2].strip()
        if rest.startswith("{"):
            return re.search(r"enabled:\s*true\b", rest) is not None
        for following in lines[index + 1 :]:
            if following.strip() and not following.startswith((" ", "\t")):
                break
            if re.match(r"^\s+enabled:\s*true\b", following):
                return True
    return False


def caller_startup_body(startup_input: str, expected_body: str) -> bool:
    """Apply the original complete caller-envelope/body predicate to the captured first input."""
    opening_match = B9_CALLER_IDENTITY_OPENING_RE.match(startup_input)
    if opening_match is None:
        return False
    opening = opening_match.group(0)
    opening_framing = opening + B9_RENDERER_SEPARATOR
    closing_framing = B9_RENDERER_SEPARATOR + B9_CALLER_CLOSING_TEMPLATE.format(header=opening[1:-1])
    if not startup_input.startswith(opening_framing) or not startup_input.endswith(closing_framing):
        return False
    body_start = len(opening_framing)
    body_end = len(startup_input) - len(closing_framing)
    return startup_input[body_start:body_end] == expected_body


class _Prepared:
    """One run of journey B4."""

    def __init__(
        self,
        host: FoundationHost,
        setup: foundation.FixtureSetup,
        project: Path,
        source_root: Path,
        owner_email: str,
        owner_slug: str,
        report_path: Path,
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
        self.temporary_root = setup.control.parent
        self.source_root = source_root
        self.project = project.resolve()
        self.owner_email = owner_email
        self.owner_slug = owner_slug
        self.report_path = report_path.resolve()
        self.baseline: creation.SessionView | None = None
        self.starts: dict[str, str] = {}
        self.setups: list[foundation.FixtureSetup] = []
        self.journeys: dict[str, foundation.Journey] = {}
        self.clone: Path = source_root
        self.initial_headers: list[str] = []
        self.known_claims = 0
        self.known_sessions: list[str] = []
        self.b4_ledger: start_ledger.StartLedger | None = None
        self.outsider_sessions: dict[str, str] = {}
        self.b4_retained = False
        self.handover = handover.Handover(self.observer, host, worktree=self._worktree_block)
        self.accounting: creation.EvidenceObject | None = None

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _known(self, *sessions: str) -> frozenset[str]:
        assert self.baseline is not None
        return self.baseline.ids | frozenset(self.known_sessions) | frozenset(sessions)

    def _journey(self, name: str, index: int, message: str | None = None) -> foundation.Journey:
        journey = foundation.Journey(self.host, self.setups[index], self.project, self.owner_email, message=message)
        self.journeys[name] = journey
        return journey

    def _shown(self) -> Json:
        return driver.shown_with_content(self.observer, ITEM)

    def _input(self) -> str:
        found, text = creation.dig(self._shown(), f"artifact_content.{INPUT}")
        if not found or not isinstance(text, str):
            raise creation.trace_failure(
                creation.DETAIL_PATH_ABSENT.format(slug=ITEM, path=f"artifact_content.{INPUT}")
            )
        return text

    def _headers(self) -> list[str]:
        _, log = creation.dig(self._shown(), "artifact_content.log")
        return [header for header, _ in waiting.log_entries(str(log))]

    def _git(self, step: str, *args: str) -> str:
        outcome = self.host.process((GIT, *args), self.project, self.host.environment, GIT_TIMEOUT_SECONDS)
        if outcome.exit_status != 0:
            raise creation.binding_failure(
                DETAIL_GIT.format(step=step, args=list(args), status=outcome.exit_status, output=outcome.output[-300:])
            )
        return outcome.output.strip()

    def _git_ok(self, *args: str) -> bool:
        outcome = self.host.process((GIT, *args), self.project, self.host.environment, GIT_TIMEOUT_SECONDS)
        return outcome.exit_status == 0

    def _late(self, index: int, name: str, argv: list[str]) -> None:
        (self.setups[index].control / name).write_text(json.dumps(argv), encoding="utf-8")

    def _gate(self, index: int, name: str) -> None:
        (self.setups[index].control / name).write_text("1\n", encoding="utf-8")

    def _b4_begin(self, label: str, kind: str, parent: str | None = None) -> str:
        if self.b4_ledger is None:
            raise creation.binding_failure(
                DETAIL_B9_ATTEMPT.format(detail="the ledger was not created before B9 calls")
            )
        try:
            return self.b4_ledger.begin(B4_CASE, label, kind, parent=parent)
        except ValueError as error:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail=str(error))) from error

    def _b4_discharge(self, attempt: str, evidence: str) -> None:
        if self.b4_ledger is None:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail="the ledger is missing"))
        try:
            self.b4_ledger.discharge(attempt, evidence)
        except ValueError as error:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail=str(error))) from error

    def _slot_session(self, index: int) -> str:
        """Map a first-free pool slot to its public session through the launch's native id."""
        launch_path = self.setups[index].control / foundation.LAUNCH_FILE
        deadline = time.monotonic() + waiting.START_CAP_SECONDS
        while time.monotonic() < deadline:
            try:
                launch_value = json.loads(launch_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload_work.sleep(POLL_SECONDS)
                continue
            launch = launch_value if isinstance(launch_value, Mapping) else {}
            native = launch.get(foundation.FIELD_NATIVE)
            if isinstance(native, str) and native:
                for session in self.observer.sessions(retain=False).ids:
                    record = self._record(session)
                    if record.get(foundation.FIELD_NATIVE) == native:
                        return session
            payload_work.sleep(POLL_SECONDS)
        raise creation.binding_failure(DETAIL_B9_SESSION.format(label=f"d{index}", record="no native launch mapping"))

    def _roleless_startup(
        self, session: str, index: int, message: str, evidence: creation.EvidenceObject | None = None
    ) -> None:
        journey = self._journey("S_P" if index == 0 else "X", index, message)
        journey.session_id = session
        launch = journey.await_json(self.setups[index].control / foundation.LAUNCH_FILE, waiting.LAUNCH_SECONDS)
        if evidence is not None:
            evidence["launch"] = cast(creation.EvidenceValue, dict(launch))
        native = launch.get(foundation.FIELD_NATIVE)
        if not isinstance(native, str) or not native:
            raise creation.binding_failure(DETAIL_B9_SESSION.format(label=session, record=launch))
        deadline = time.monotonic() + waiting.START_CAP_SECONDS
        for hook in (foundation.FRAME_SESSION_START, foundation.FRAME_PROMPT_SUBMIT):
            frame = journey.await_frame(hook, deadline)
            if evidence is not None:
                cast(list[creation.EvidenceValue], evidence["hooks"]).append(
                    {"name": hook, "frame": cast(creation.EvidenceValue, dict(frame))}
                )
            journey.require_hook(hook, frame)
        record = self._record(session)
        if evidence is not None:
            evidence["startup_record"] = cast(creation.EvidenceValue, dict(record))
        if (
            record.get(foundation.FIELD_NATIVE) != native
            or not journey.started(record, native)
            or record.get(waiting.FIELD_ROLE) is not None
            or record.get(waiting.FIELD_JOB) is not None
        ):
            raise creation.platform_failure(DETAIL_B9_SESSION.format(label=session, record=record))
        inputs = journey.inputs()
        if evidence is not None:
            evidence["inputs"] = cast(creation.EvidenceValue, inputs)
        first = inputs[0].get("text") if inputs else None
        if index == 0:
            input_matches = first == message
        else:
            input_matches = isinstance(first, str) and self._caller_startup_body(first, message)
        if not input_matches:
            raise creation.platform_failure(
                DETAIL_B9_SESSION.format(
                    label=session,
                    record={
                        "detail": B9_STARTUP_INPUT_MISMATCH,
                        "input_length": len(first) if isinstance(first, str) else None,
                    },
                )
            )

    @staticmethod
    def _caller_startup_body(startup_input: str, expected_body: str) -> bool:
        """Recognize the complete registered caller envelope and compare its exact body."""
        return caller_startup_body(startup_input, expected_body)

    def _public_log_entries(self, payload: Json) -> list[tuple[str, str]]:
        found, log = creation.dig(payload, "artifact_content.log")
        if not found or not isinstance(log, str):
            raise creation.trace_failure(creation.DETAIL_PATH_ABSENT.format(slug=ITEM, path="artifact_content.log"))
        return waiting.log_entries(log)

    def _record(self, session: str) -> Json:
        outcome = self.observer.run((TELEC, "sessions", "show", session, foundation.FULL_FLAG), retain=False)
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        if record is None:
            raise creation.binding_failure(f"session {session} is unreadable: {outcome.output[-300:]!r}")
        return record

    def _frame_output(
        self, journey: foundation.Journey, name: str, evidence: creation.EvidenceObject | None = None
    ) -> tuple[int | None, str]:
        frame = journey.await_frame(name, time.monotonic() + FRAME_SECONDS)
        if evidence is not None:
            evidence["start_frame"] = cast(creation.EvidenceValue, dict(frame))
        run = frame.get("run")
        if not isinstance(run, dict):
            raise creation.platform_failure(f"the frame {name} is not a completed public call: {frame!r}")
        if run.get("error") == waiting.LATE_ARGV_UNREADABLE:
            raise creation.binding_failure(waiting.DETAIL_LATE_UNREADABLE.format(name=name, frame=frame))
        status = run.get("exit_status")
        return (status if isinstance(status, int) else None), f"{run.get('stdout', '')}{run.get('stderr', '')}"

    def _discover(self, known: frozenset[str]) -> str:
        deadline = time.monotonic() + waiting.START_CAP_SECONDS
        found: list[str] = []
        while time.monotonic() < deadline:
            found = sorted(self.observer.sessions(retain=False).ids - known)
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise creation.platform_failure(
                    waiting.DETAIL_SESSIONS.format(when="discovery", found=found, expected="one")
                )
            payload_work.sleep(POLL_SECONDS)
        raise creation.platform_failure(waiting.DETAIL_SESSIONS.format(when="discovery", found=found, expected="one"))

    def _require_pool(self, claimed: int) -> None:
        expected = [self.setups[index].control for index in range(claimed)]
        found = self.controls.claimed()
        if found != expected:
            raise creation.binding_failure(
                waiting.DETAIL_POOL.format(found=[p.name for p in found], expected=[p.name for p in expected])
            )

    # -- setup -----------------------------------------------------------------------------------------------------
    def declare_docs_capability(self, project_slug: str) -> None:
        """G0 (amendment B4G): the owned project declares docs, with code and agents disabled, before any base commit.

        The revision-checked public patch writes the declaration only; the base commit (or one extra owner commit when a
        base already exists) carries it to `origin/main`, so the slug worktree opens with it.
        """
        got = self.observer.run((TELEC, CONFIG, PROJECT, GET, project_slug, FORMAT_OPTION, JSON_FORMAT))
        payload = foundation.json_object(got.output)
        view = payload.get(PROJECT_SECTION) if payload is not None else None
        revision = payload.get(REVISION_FIELD) if payload is not None else None
        if got.exit_status != 0 or not isinstance(view, Mapping) or not isinstance(revision, str) or not revision:
            raise creation.binding_failure(DETAIL_PROJECT_READ.format(status=got.exit_status, output=got.output[-300:]))
        if capability_enabled(view, CAPABILITY_DOCS):
            self.host.note((CAPABILITY_NOTE, "docs already enabled"), foundation.Outcome(0, ""), "")
        else:
            patch = self.observer.run(
                (
                    TELEC,
                    CONFIG,
                    PROJECT,
                    "patch",
                    project_slug,
                    REVISION_OPTION,
                    revision,
                    YAML_OPTION,
                    json.dumps({CAPABILITY_DOCS: {"enabled": True}}),
                )
            )
            if patch.exit_status != 0:
                raise creation.binding_failure(
                    DETAIL_PROJECT_PATCH.format(status=patch.exit_status, output=patch.output[-300:])
                )
        read_back = self.observer.run((TELEC, CONFIG, PROJECT, GET, project_slug, FORMAT_OPTION, JSON_FORMAT))
        if read_back.exit_status != 0:
            raise creation.binding_failure(
                DETAIL_PROJECT_READ.format(status=read_back.exit_status, output=read_back.output[-300:])
            )
        again = foundation.json_object(read_back.output)
        after = again.get(PROJECT_SECTION) if again is not None else None
        if (
            not isinstance(after, Mapping)
            or not capability_enabled(after, CAPABILITY_DOCS)
            or any(capability_enabled(after, name) for name in (CAPABILITY_CODE, CAPABILITY_AGENTS))
        ):
            raise creation.binding_failure(DETAIL_CAPABILITY.format(where="the public project view", found=after))

    def require_declared(self, where: str, text: str) -> None:
        """A committed declaration carries docs enabled and neither code nor agents."""
        if not text_capability_enabled(text, CAPABILITY_DOCS) or any(
            text_capability_enabled(text, name) for name in (CAPABILITY_CODE, CAPABILITY_AGENTS)
        ):
            raise creation.binding_failure(DETAIL_CAPABILITY.format(where=where, found=text[-400:]))

    def hook_preflight(self) -> None:
        """No hook path and no executable hook: a present hook is a binding failure, never a reason to relax a floor."""
        if self._git_ok("config", "--get", "core.hooksPath"):
            raise creation.binding_failure(DETAIL_HOOK.format(what="core.hooksPath is set"))
        hooks = Path(self._git("hooks directory", "rev-parse", "--git-path", "hooks"))
        directory = hooks if hooks.is_absolute() else self.project / hooks
        for name in HOOK_NAMES:
            candidate = directory / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                raise creation.binding_failure(DETAIL_HOOK.format(what=str(candidate)))

    def git_fixture(self) -> None:
        """G1 to G5: a committer identity, a main branch with a base commit, an owned bare origin, read back."""
        self._git("G1 name", "config", "user.name", GIT_NAME)
        self._git("G1 email", "config", "user.email", GIT_EMAIL)
        has_commit = self._git_ok("rev-parse", "--verify", "HEAD")
        if has_commit:
            if not self._git_ok("diff", "--quiet", "HEAD", "--", BASE_FILE):
                self._git("G0 add", "add", "--", BASE_FILE)
                self._git("G0 commit", "commit", "-m", "chore(fixture): declare docs capability")
            self._git("G2", "branch", "-M", MAIN)
        else:
            self._git("G2", "symbolic-ref", "HEAD", f"refs/heads/{MAIN}")
            self._git("G3 add", "add", "--", BASE_FILE)
            self._git("G3 commit", "commit", "-m", "fixture base")
        origin = self.temporary_root / ORIGIN_NAME
        if not origin.exists():
            created = self.host.process(
                (GIT, "init", "--bare", "-q", str(origin)),
                self.temporary_root,
                self.host.environment,
                GIT_TIMEOUT_SECONDS,
            )
            if created.exit_status != 0:
                raise creation.binding_failure(
                    DETAIL_GIT.format(
                        step="G4 init",
                        args=["init", "--bare"],
                        status=created.exit_status,
                        output=created.output[-300:],
                    )
                )
        if self._git_ok("remote", "get-url", ORIGIN):
            self._git("G4 remote", "remote", "set-url", ORIGIN, str(origin))
        else:
            self._git("G4 remote", "remote", "add", ORIGIN, str(origin))
        self._git("G4 push", "push", ORIGIN, MAIN)
        self._git("G5 fetch", "fetch", ORIGIN, MAIN)
        main, remote = self._git("G5 main", "rev-parse", MAIN), self._git("G5 origin", "rev-parse", f"{ORIGIN}/{MAIN}")
        url = self._git("G5 url", "remote", "get-url", ORIGIN)
        if main != remote:
            raise creation.binding_failure(
                DETAIL_ORIGIN.format(what="origin/main equals main", found=remote, expected=main)
            )
        if Path(url).resolve() != origin.resolve():
            raise creation.binding_failure(DETAIL_ORIGIN.format(what="origin url", found=url, expected=str(origin)))
        self.require_declared("origin/main", self._git("origin declaration", "show", f"{ORIGIN}/{MAIN}:{BASE_FILE}"))
        self.hook_preflight()

    def setup_pool(self) -> None:
        prepare = ["telec", TODO, "prepare", ITEM]
        child = ["telec", TODO, "child", ITEM]
        outsider_parent = [controls.late("startx", ARGV_X_START, GATE_X_START)]
        outsider_child = [controls.late("inputforeign", ARGV_X_INPUT, GATE_X_INPUT)]
        preparation_driver = [
            controls.command("claim", prepare),
            controls.command("child", child),
            controls.late("preparedold", ARGV_OLD, GATE_OLD),
            controls.late("preparednew", ARGV_NEW, GATE_NEW),
        ]
        intaker = [
            controls.late("inputc", ARGV_C2_INPUT, GATE_C2_INPUT),
            controls.late("preparedwrong", ARGV_C2_PREPARED, GATE_C2_PREPARED),
            controls.late("waitingwrong", ARGV_C2_WAITING, GATE_C2_WAITING),
        ]
        work = [controls.command("claim", ["telec", TODO, "work", ITEM])]
        plans = [
            controls.PlanFile(commands=commands)
            for commands in (outsider_parent, outsider_child, preparation_driver, intaker, work)
        ]
        self.setups = self.controls.pool(plans)
        self.b4_ledger = start_ledger.StartLedger.create(self.controls.root / B4_ATTEMPT_LEDGER)
        try:
            self.b4_ledger.declare_case(B4_CASE, B4_B9_ACTIONS)
        except ValueError as error:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail=str(error))) from error

    def preconditions(self) -> None:
        shown = self._shown()
        # The derived handoff of amendment A4: B3 released the close hold of its last driver, so the item starts unheld
        # with an empty audit; a failure here is a binding failure of the chain.
        self.handover.assert_start_unheld(ITEM, "B4 start")
        for path, expected in (("state.lifecycle_phase", PREPARATION_PHASE),):
            found, value = creation.dig(shown, path)
            if not found or value != expected:
                raise creation.binding_failure(
                    DETAIL_PRECONDITION.format(item=ITEM, path=path, found=value, expected=expected)
                )
        creation.require_unclaimed(ITEM, shown)
        _, standing = creation.dig(shown, "standing")
        if isinstance(standing, Mapping) and "held_by" in standing:
            raise creation.binding_failure(
                DETAIL_PRECONDITION.format(item=ITEM, path="standing.held_by", found="present", expected="absent")
            )
        self.initial_headers = self._headers()
        self.known_claims = sum(
            1 for header in self.initial_headers if f" {driver.CLAIM_HEADER_SUFFIX.strip()}" in header
        )

    def start_b9_outsiders(self) -> tuple[str, str]:
        """The approved B9 parent/outsider launch order occupies d0 and d1 before D2 starts."""
        if self.baseline is None:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail="B0 was not captured"))
        start_s_p = self._b4_begin(SESSION_S_P, start_ledger.RECORD_SESSION)
        parent_evidence = driver.actor_inputs(self.accounting, "S_P", 0)
        if parent_evidence is not None:
            parent_evidence["message"] = B9_S_P_MESSAGE
        parent_journey = self._journey("S_P", 0, B9_S_P_MESSAGE)
        try:
            parent_journey.start_session(case_start_file=False)
        finally:
            if parent_evidence is not None and parent_journey.start_evidence is not None:
                parent_evidence["start_command"] = creation.command_evidence(*parent_journey.start_evidence)
        session_parent = parent_journey.session_id
        if parent_evidence is not None:
            parent_evidence["session_id"] = session_parent
        if not session_parent:
            self.b4_ledger.unknown(start_s_p)
            raise creation.binding_failure(DETAIL_B9_SESSION.format(label="S_P", record="missing public session id"))
        self.b4_ledger.record_session(start_s_p, session_parent)
        self.outsider_sessions["S_P"] = session_parent
        self.known_sessions.append(session_parent)
        if self._slot_session(0) != session_parent:
            raise creation.binding_failure(DETAIL_B9_SESSION.format(label="S_P", record=self._record(session_parent)))
        self._roleless_startup(session_parent, 0, B9_S_P_MESSAGE, parent_evidence)
        record_parent = self._record(session_parent)
        if parent_evidence is not None:
            parent_evidence["fact_record"] = cast(creation.EvidenceValue, dict(record_parent))
        if record_parent.get(waiting.FIELD_INITIATOR) not in (None, ""):
            raise creation.platform_failure(DETAIL_B9_SESSION.format(label="S_P", record=record_parent))
        self._require_pool(1)
        if parent_evidence is not None:
            parent_evidence["finished_ns"] = time.monotonic_ns()

        start_x = self._b4_begin(SESSION_X, start_ledger.RECORD_SESSION, parent=SESSION_S_P)
        x_evidence = driver.actor_inputs(self.accounting, "X", 1)
        if x_evidence is not None:
            x_evidence["message"] = B9_X_MESSAGE
            x_evidence["parent_actor"] = session_parent
        self._late(
            0,
            ARGV_X_START,
            [
                NATIVE_TELEC_COMMAND,
                "sessions",
                "start",
                "--path",
                str(self.project),
                "--agent",
                "claude",
                "--mode",
                "fast",
                "--message",
                B9_X_MESSAGE,
            ],
        )
        self._gate(0, GATE_X_START)
        status, output = self._frame_output(parent_journey, "cmd_startx", x_evidence)
        result = foundation.json_object(output)
        session_from_start = result.get("session_id") if result is not None else None
        if status != 0 or not isinstance(session_from_start, str) or not session_from_start:
            self.b4_ledger.unknown(start_x)
            raise creation.platform_failure(
                DETAIL_B9_REFUSAL.format(
                    act="X start", status=status, expected="a successful public session id", output=output[-400:]
                )
            )
        self.b4_ledger.record_session(start_x, session_from_start)
        self.outsider_sessions["X"] = session_from_start
        if x_evidence is not None:
            x_evidence["session_id"] = session_from_start
        self.known_sessions.append(session_from_start)
        session_x = self._slot_session(1)
        if session_x != session_from_start:
            raise creation.binding_failure(DETAIL_B9_SESSION.format(label="X", record=self._record(session_x)))
        self._roleless_startup(session_x, 1, B9_X_MESSAGE, x_evidence)
        record_x = self._record(session_x)
        if x_evidence is not None:
            x_evidence["fact_record"] = cast(creation.EvidenceValue, dict(record_x))
        if record_x.get(waiting.FIELD_INITIATOR) != session_parent:
            raise creation.binding_failure(DETAIL_B9_SESSION.format(label="X initiator", record=record_x))
        self.outsider_sessions["X"] = session_x
        self._require_pool(2)
        if x_evidence is not None:
            x_evidence["finished_ns"] = time.monotonic_ns()
        return session_parent, session_x

    def b9_positive_input(self, intaker: str) -> None:
        """C2's successful BODY_C write binds the in-group intent edit before the owner BODY_A write."""
        attempt = self._b4_begin(EFFECT_C2_INPUT, start_ledger.RECORD_EFFECT)
        before = self.snapshot()
        before_log = self._public_log_entries(before)
        self._late(3, ARGV_C2_INPUT, [NATIVE_TELEC_COMMAND, TODO, "artifacts", "write", ITEM, INPUT, B9_BODY_C])
        self._gate(3, GATE_C2_INPUT)
        journey = self.journeys["child"]
        status, output = self._frame_output(journey, "cmd_inputc")
        if status != 0 or WROTE_PHRASE not in output:
            raise creation.platform_failure(
                DETAIL_WRITE.format(status=status, phrase=WROTE_PHRASE, output=output[-300:])
            )
        after = self._shown()
        items.require_only_changes("B9 C2 intent body", before, after, OWNER_WRITE_PATHS)
        if self._input() != B9_BODY_C:
            raise creation.platform_failure(DETAIL_BODY.format(found=self._input(), expected=B9_BODY_C))
        found, updated_by = creation.dig(after, UPDATED_BY)
        if not found or updated_by != intaker:
            raise creation.platform_failure(DETAIL_UPDATED_SESSION.format(found=updated_by))
        if self._public_log_entries(after) != before_log:
            raise creation.platform_failure(
                DETAIL_LOG_HEADERS.format(
                    when="after C2's positive input", before=before_log, after=self._public_log_entries(after)
                )
            )
        self.require_live(intaker, "after C2's positive input")
        self._b4_discharge(attempt, "C2 command succeeded, BODY_C is public, and updated_by names C2")

    def _b9_refusal(
        self,
        label: str,
        index: int,
        argv_file: str,
        gate: str,
        frame: str,
        argv: list[str],
        expected: tuple[str, ...],
    ) -> None:
        attempt = self._b4_begin(label, start_ledger.RECORD_EFFECT)
        snapshot = self.snapshot()
        entries = self._public_log_entries(snapshot)
        sessions = self.observer.sessions()
        self._late(index, argv_file, argv)
        self._gate(index, gate)
        journey = self._journey("outsider", 1 if index == 1 else index)
        status, output = self._frame_output(journey, frame)
        if status in (None, 0) or any(needle not in output for needle in expected) or "Performed " in output:
            raise creation.platform_failure(
                DETAIL_B9_REFUSAL.format(act=label, status=status, expected=expected, output=output[-400:])
            )
        self.require_snapshot(snapshot, f"B9 {label}")
        if self._public_log_entries(self._shown()) != entries:
            raise creation.platform_failure(
                DETAIL_LOG_HEADERS.format(
                    when=f"B9 {label}", before=entries, after=self._public_log_entries(self._shown())
                )
            )
        creation.require_sessions_equal(sessions, self.observer.sessions(retain=False), f"B9 {label}")
        self._b4_discharge(attempt, f"public refusal {expected!r}; complete show, log and session set unchanged")

    def b9_wrong_performers(self, author: str, intaker: str, r1: str) -> None:
        """Run X and C2's phase-valid refused probes before D2's successful prepared."""
        if self._record(author).get(waiting.FIELD_ROLE) != "prepare-orchestrator":
            raise creation.platform_failure(DETAIL_B9_SESSION.format(label="D2", record=self._record(author)))
        if (
            self._record(intaker).get(waiting.FIELD_ROLE) != "intaker"
            or self._record(intaker).get(waiting.FIELD_INITIATOR) != author
        ):
            raise creation.platform_failure(DETAIL_B9_SESSION.format(label="C2", record=self._record(intaker)))
        creation.require_value(ITEM, self._shown(), "state.active_runner", author)
        x = self.outsider_sessions.get("X")
        if x is None:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail="X was not recorded"))
        self._b9_refusal(
            EFFECT_X_INPUT,
            1,
            ARGV_X_INPUT,
            GATE_X_INPUT,
            "cmd_inputforeign",
            [NATIVE_TELEC_COMMAND, TODO, "artifacts", "write", ITEM, INPUT, B9_X_INPUT],
            ("409", f"{ITEM} is held by session {author}", "holder or a session of its claiming group"),
        )
        self._b9_refusal(
            EFFECT_C2_PREPARED,
            3,
            ARGV_C2_PREPARED,
            GATE_C2_PREPARED,
            "cmd_preparedwrong",
            [NATIVE_TELEC_COMMAND, TODO, "act", ITEM, "prepared", "--revision", r1, B9_PREPARED_TEXT],
            ("Error: 409 — prepared requires the holding driver",),
        )
        self._b9_refusal(
            EFFECT_C2_WAITING,
            3,
            ARGV_C2_WAITING,
            GATE_C2_WAITING,
            "cmd_waitingwrong",
            [NATIVE_TELEC_COMMAND, TODO, "act", ITEM, "waiting", "--person", self.owner_slug, B9_WAITING_TEXT],
            ("Error: 409 — waiting requires the holding driver",),
        )

    def _end_b9_session(self, label: str, session: str) -> None:
        assert self.b4_ledger is not None
        attempt = next((row for row in self.b4_ledger.attempts.values() if row.label == label), None)
        if attempt is not None and attempt.state == start_ledger.RECORD_DISCHARGED:
            return
        if attempt is None:
            identifier = self._b4_begin(label, start_ledger.RECORD_OPERATION)
        elif attempt.operation_id:
            identifier = attempt.identifier
        else:
            self.b4_ledger.unknown(attempt.identifier)
            return
        if attempt is None or not attempt.operation_id:
            outcome = self.observer.run((TELEC, "sessions", "end", session))
            receipt = foundation.json_object(outcome.output)
            operation = receipt.get("operation_id") if receipt is not None else None
            if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
                self.b4_ledger.unknown(identifier)
                return
            self.b4_ledger.record_operation(identifier, operation)
        else:
            operation = attempt.operation_id
        terminal = publication.await_terminal(self.observer, operation, OPERATION_SECONDS)
        record = self._record(session)
        if (
            terminal.get(publication.FIELD_STATE) != publication.STATE_COMPLETED
            or record.get(waiting.FIELD_CLOSED_AT) is None
            or record.get(waiting.FIELD_LIFECYCLE) != foundation.CLOSED
        ):
            raise creation.platform_failure(DETAIL_B9_END.format(session=session, record=record))
        self._b4_discharge(identifier, "public end operation completed and retained session record closed")

    def close_b9_outsiders(self, *, strict: bool = True) -> None:
        """Close X before S_P with independent receipts and retained records, before D2's valid prepared."""
        session_x = self.outsider_sessions.get("X")
        session_parent = self.outsider_sessions.get("S_P")
        if session_x is not None:
            self._end_b9_session(END_X, session_x)
        if session_parent is not None:
            self._end_b9_session(END_S_P, session_parent)
        if strict and (session_x is None or session_parent is None):
            raise creation.binding_failure(
                DETAIL_B9_ATTEMPT.format(detail="S_P or X has no observed public session id")
            )
        assert self.b4_ledger is not None
        for label in (SESSION_X, SESSION_S_P):
            attempt = next(row for row in self.b4_ledger.attempts.values() if row.label == label)
            if attempt.state == start_ledger.RECORD_DISCHARGED:
                continue
            if attempt.session_id is None:
                if strict:
                    raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail=f"{label} has no public session id"))
                continue
            if attempt.state != start_ledger.RECORD_OPEN:
                if strict:
                    raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail=f"{label} has no proven end"))
                continue
            closed = self._record(attempt.session_id)
            if closed.get(waiting.FIELD_CLOSED_AT) is None or closed.get(waiting.FIELD_LIFECYCLE) != foundation.CLOSED:
                raise creation.platform_failure(DETAIL_B9_END.format(session=attempt.session_id, record=closed))
            self._b4_discharge(
                attempt.identifier, "public session start is owned and its explicit end is proven closed"
            )

    def _b9_open_attempts(self) -> tuple[list[start_ledger.JsonObject], str | None]:
        captured: list[bytes] | None = [] if self.accounting is not None else None
        packet: creation.EvidenceObject | None = None
        if self.accounting is not None:
            packet = {
                "started_ns": time.monotonic_ns(),
                "finished_ns": None,
                "path": str(
                    self.b4_ledger.path if self.b4_ledger is not None else self.controls.root / B4_ATTEMPT_LEDGER
                ),
                "raw_reads": [],
                "error": None,
            }
            cast(list[creation.EvidenceValue], self.accounting["attempt_ledgers"]).append(packet)
        try:
            if self.b4_ledger is None:
                if packet is not None:
                    packet["error"] = "the B4 attempt ledger was not established"
                return [], "the B4 attempt ledger was not established"
            loaded = start_ledger.StartLedger.load(self.b4_ledger.path, captured=captured)
            self.b4_ledger = loaded
        except (OSError, ValueError) as error:
            if packet is not None:
                packet["error"] = str(error)
            return [], str(error)
        finally:
            if packet is not None and captured is not None:
                packet["raw_reads"] = [
                    {
                        "raw_data": base64.b64encode(data).decode("ascii"),
                        "raw_sha256": hashlib.sha256(data).hexdigest(),
                        "raw_byte_count": len(data),
                    }
                    for data in captured
                ]
                packet["finished_ns"] = time.monotonic_ns()
        return [
            {
                "id": attempt.identifier,
                "case": attempt.case,
                "label": attempt.label,
                "kind": attempt.kind,
                "state": attempt.state,
                "parent": attempt.parent,
                "operation_id": attempt.operation_id,
                "session_id": attempt.session_id,
                "evidence": attempt.evidence,
            }
            for attempt in self.b4_ledger.attempts.values()
            if attempt.state != start_ledger.RECORD_DISCHARGED
        ], None

    def _write_b9_retained(self, problems: list[str], attempt_error: str | None) -> None:
        """Retain the complete full-profile runtime before any candidate restore or control deletion."""
        self.b4_retained = True
        marker_path = self.controls.root / RETAINED_NAME
        attempt_rows, read_error = self._b9_open_attempts()
        known: dict[str, start_ledger.JsonValue] = {}
        for label, session in {
            **self.outsider_sessions,
            **{str(i): value for i, value in enumerate(self.known_sessions)},
        }.items():
            try:
                known[label] = cast(start_ledger.JsonValue, self._record(session))
            except BaseException as error:
                known[label] = {"session_id": session, "error": str(error)}
        try:
            item_snapshot = self._shown()
            parsed_log: object = self._public_log_entries(item_snapshot)
        except BaseException as error:
            item_snapshot = {"unavailable": str(error)}
            parsed_log = None
        candidate_identity: object = self.publication.candidate or {
            "unavailable": "candidate identity was not captured"
        }
        try:
            source_identity: object = self.publication.identity()
        except BaseException as error:
            source_identity = {"unavailable": str(error)}
        try:
            fixture_publication_sha: object = self._git(
                "retained fixture publication revision", "-C", str(self.publication.clone), "rev-parse", "HEAD"
            )
        except BaseException as error:
            fixture_publication_sha = {"unavailable": str(error)}
        attempts_path = self.controls.root / B4_ATTEMPT_LEDGER
        plan_and_argv = [
            str(path.resolve())
            for setup in self.setups
            for path in (setup.control / controls.PLAN_FILE, *setup.control.glob("*.argv"))
            if path.exists()
        ]
        marker = {
            "status": "RETAINED-UNPROVEN",
            "reason": "B9 B4 attempt, session close, or process settlement is unresolved; no cleanup pass is claimed",
            "failure": problems,
            "attempt_ledger": str(attempts_path.resolve()),
            "attempt_ledger_error": read_error or attempt_error,
            "open_attempts": attempt_rows,
            "known_sessions": known,
            "driver_start_attempts": dict(self.starts),
            "last_complete_public_show": item_snapshot,
            "parsed_public_log": parsed_log,
            "candidate_identity": candidate_identity,
            "source_identity": source_identity,
            "candidate_publication": self.publication.candidate,
            "fixture_publication_sha": fixture_publication_sha,
            "runtime_home": str(self.temporary_root.resolve()),
            "project": str(self.project),
            "pool_root": str(self.controls.root.resolve()),
            "control_directories": [str(path.resolve()) for path in self.controls.directories],
            "sidecar": str(self.controls.setup.configuration.resolve()),
            "plans_and_argv": plan_and_argv,
            "publication_clone": str(self.publication.clone.resolve()),
            "worktree": str((self.project / "trees" / ITEM).resolve()),
            "owned_origin": str((self.temporary_root / ORIGIN_NAME).resolve()),
            "report": str(self.report_path),
            "proofs": {
                "P1_session_lifecycle": "from public completed ends and closed retained records only",
                "P2_launch_consumption": "unknown B9 starts or effects remain open",
                "P3_daemon_stopped": "pending profile boundary make stop outcome",
                "P4_fixture_processes_and_panes": "unproven by the approved contract",
            },
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = marker_path.with_name(f".{marker_path.name}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(marker, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker_path)
        self.retain(DETAIL_B9_RETAINED.format(path=marker_path.resolve()))

    # -- the owner write set ----------------------------------------------------------------------------------------
    def require_owner_write(self, before: Json, after: Json) -> None:
        """A body write by the owner changes `show` only in the paths of section 4a, with the clock moving forward."""
        items.require_only_changes("owner body write", before, after, OWNER_WRITE_PATHS)
        found, updated_by = creation.dig(after, UPDATED_BY)
        if not found:
            raise creation.trace_failure(creation.DETAIL_PATH_ABSENT.format(slug=ITEM, path=UPDATED_BY))
        if updated_by != creation.EMPTY:
            if updated_by in set(self.known_sessions):
                raise creation.platform_failure(DETAIL_UPDATED_SESSION.format(found=updated_by))
            raise creation.trace_failure(DETAIL_UPDATED_BY.format(found=updated_by))
        stamps: list[datetime] = []
        for label, payload in (("before", before), ("after", after)):
            found, value = creation.dig(payload, UPDATED_AT)
            if not found or not isinstance(value, str):
                raise creation.trace_failure(
                    creation.DETAIL_PATH_ABSENT.format(slug=f"{ITEM} {label}", path=UPDATED_AT)
                )
            try:
                stamps.append(datetime.fromisoformat(value))
            except ValueError as error:
                raise creation.trace_failure(f"roadmap.updated_at is not an ISO instant: {value!r}") from error
        if stamps[1] < stamps[0]:
            raise creation.platform_failure(DETAIL_CLOCK.format(before=stamps[0], after=stamps[1]))

    def require_live(self, session: str, when: str) -> None:
        """The live author is active and unclosed: a body write or a refused act ends nothing."""
        record = self._record(session)
        if record.get(waiting.FIELD_CLOSED_AT) is not None or record.get(waiting.FIELD_LIFECYCLE) != foundation.ACTIVE:
            raise creation.platform_failure(
                DETAIL_LIVE.format(
                    actor="author", session=session, problem=f"is not active and unclosed {when}", record=record
                )
            )

    def owner_write(self, body: str) -> Json:
        outcome = self.observer.run((TELEC, TODO, "artifacts", "write", ITEM, INPUT, body))
        if outcome.exit_status != 0 or WROTE_PHRASE not in outcome.output:
            raise creation.platform_failure(
                DETAIL_WRITE.format(status=outcome.exit_status, phrase=WROTE_PHRASE, output=outcome.output[-300:])
            )
        after = self._shown()
        if self._input() != body:
            raise creation.platform_failure(DETAIL_BODY.format(found=self._input(), expected=body))
        return after

    def snapshot(self) -> Json:
        """Two equal reads at least two seconds apart: nothing else is writing the item."""
        first = self._shown()
        payload_work.sleep(creation.QUIESCENCE_GAP_SECONDS)
        second = self._shown()
        changed = creation.differences(first, second)
        if changed:
            raise creation.binding_failure(creation.DETAIL_NOT_QUIESCENT.format(paths=changed))
        return second

    def require_snapshot(self, expected: Json, when: str) -> None:
        for label, pause in (("immediately", 0.0), ("five seconds later", items.SETTLE_SECONDS)):
            if pause:
                payload_work.sleep(pause)
            changed = creation.differences(expected, self._shown())
            if changed:
                raise creation.platform_failure(DETAIL_CHANGED.format(when=f"{when} {label}", paths=changed))

    # -- steps -----------------------------------------------------------------------------------------------------
    def step1_driver(self) -> tuple[driver.DriverCase, str, str]:
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
                waiting.DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        child_attempt = driver.begin_attempt(self.starts, "session-child")
        author = self._discover(self._known())
        case = self._case("author", 2, driver.DRIVER_ID, "prepare", PREPARATION_PHASE)
        outsiders = set(self.outsider_sessions.values())
        case.check_startup(author, frozenset({*outsiders, author}))
        self._require_pool(3)
        instruction = case.claim_call([starter])
        case.check_instruction(author, instruction)
        case.observe_claim(author, known_entries=self.known_claims)
        self.starts[starter] = publication.START_CLAIMED
        child_evidence = driver.actor_inputs(self.accounting, "child", 3)
        if child_evidence is not None:
            child_evidence["parent_actor"] = author
        status, text = self._frame_output(self.journeys["author"], waiting.FRAME_CHILD, child_evidence)
        started = waiting.STARTED_CHILD.search(text)
        if status != 0 or started is None or started.group("procedure") != waiting.CHILD_PROCEDURE:
            raise creation.platform_failure(
                waiting.DETAIL_CHILD.format(stdout=text[-300:], procedure=waiting.CHILD_PROCEDURE)
            )
        child = started.group("session")
        if child_evidence is not None:
            child_evidence["session_id"] = child
        driver.release_attempt(self.starts, child_attempt)
        self.known_sessions = [author, child]
        child_journey = self._journey("child", 3)
        self._startup(child, child_journey, 3, child_evidence)
        record = self._record(child)
        if child_evidence is not None:
            child_evidence["fact_record"] = cast(creation.EvidenceValue, dict(record))
        for field, expected in (
            (waiting.FIELD_ROLE, "intaker"),
            (waiting.FIELD_INITIATOR, author),
        ):
            if record.get(field) != expected:
                raise creation.platform_failure(
                    waiting.DETAIL_CHILD_RECORD.format(
                        session=child, field=field, found=record.get(field), expected=expected
                    )
                )
        self._require_pool(4)
        if child_evidence is not None:
            child_evidence["finished_ns"] = time.monotonic_ns()
        self.known_sessions = [*self.outsider_sessions.values(), author, child]
        return case, author, child

    def _case(self, name: str, index: int, driver_id: str, verb: str, phase: str) -> driver.DriverCase:
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
            driver_id=driver_id,
            verb=verb,
            phase=phase,
            case_evidence=driver.driver_inputs(self.accounting, name, index, driver_id, verb, phase),
        )

    def _startup(
        self, session: str, journey: foundation.Journey, index: int, evidence: creation.EvidenceObject | None = None
    ) -> None:
        journey.session_id = session
        launch = journey.await_json(self.setups[index].control / foundation.LAUNCH_FILE, waiting.LAUNCH_SECONDS)
        if evidence is not None:
            evidence["launch"] = cast(creation.EvidenceValue, dict(launch))
        native = str(launch.get("native_session_id"))
        deadline = time.monotonic() + waiting.START_CAP_SECONDS
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
                    waiting.DETAIL_MAPPING.format(actor="child", session=session, recorded=recorded, launched=native)
                )
            payload_work.sleep(POLL_SECONDS)
        raise creation.platform_failure(
            waiting.DETAIL_NOT_STARTED.format(
                actor="child", session=session, seconds=int(waiting.START_CAP_SECONDS), record=record
            )
        )

    def step2_move(self, author: str, child: str) -> tuple[str, str]:
        before = self._shown()
        original = self._input()
        r0 = digest(original)
        after = self.owner_write(BODY_A)
        r1 = digest(self._input())
        if r1 == r0:
            raise creation.binding_failure(DETAIL_DIGEST_SAME.format(digest=r0))
        self.require_owner_write(before, after)
        creation.require_value(ITEM, after, "state.active_runner", author)
        self.require_live(child, "after the body write")
        return r0, r1

    def step3_old_refused(self, author: str, child: str, r0: str, r1: str) -> None:
        snapshot = self.snapshot()
        headers = self._headers()
        sessions = self.observer.sessions()
        self._late(2, ARGV_OLD, ["telec", TODO, "act", ITEM, "prepared", "--revision", r0])
        self._gate(2, GATE_OLD)
        status, text = self._frame_output(self.journeys["author"], FRAME_OLD)
        problems = []
        if status in (0, None):
            problems.append("was not refused with a non-zero exit")
        if waiting.PERFORMED.format(act="prepared", item=ITEM) in text:
            problems.append("printed a performed prepared")
        if r0 not in text or r1 not in text:
            problems.append("does not name both digests in full")
        if problems:
            raise creation.platform_failure(
                DETAIL_REFUSAL.format(
                    case="prepared at the old digest", problem="; ".join(problems), status=status, output=text[-400:]
                )
            )
        self.require_snapshot(snapshot, "after the refused prepared")
        if self._headers() != headers:
            raise creation.platform_failure(
                DETAIL_LOG_HEADERS.format(when="after the refused prepared", before=headers, after=self._headers())
            )
        creation.require_value(ITEM, self._shown(), "state.active_runner", author)
        self.require_live(child, "after the refused prepared")
        creation.require_sessions_equal(sessions, self.observer.sessions(retain=False), "after the refused prepared")

    def step4_prepared(self, author: str, child: str, r1: str) -> None:
        headers = self._headers()
        self._late(2, ARGV_NEW, ["telec", TODO, "act", ITEM, "prepared", "--revision", r1])
        self._gate(2, GATE_NEW)
        status, text = self._frame_output(self.journeys["author"], FRAME_NEW)
        performed = waiting.PERFORMED.format(act="prepared", item=ITEM)
        if status != 0 or performed not in text or COMPLETE_ENDING.search(text.replace("\r\n", "\n")) is None:
            raise creation.platform_failure(
                DETAIL_REFUSAL.format(
                    case="prepared at the current digest",
                    problem=f"lacks {performed!r} ... complete",
                    status=status,
                    output=text[-400:],
                )
            )
        shown = self._shown()
        for path, expected in (
            ("state.lifecycle_phase", PREPARED_PHASE),
            ("standing.phase", PREPARED_PHASE),
        ):
            creation.require_value(ITEM, shown, path, expected)
        creation.require_unclaimed(ITEM, shown)
        record = self._record(child)
        if record.get(waiting.FIELD_CLOSED_AT) is None or record.get(waiting.FIELD_LIFECYCLE) != foundation.CLOSED:
            raise creation.platform_failure(
                DETAIL_LIVE.format(actor="author", session=child, problem="is not closed after prepared", record=record)
            )
        added = [header for header in self._headers() if header not in headers]
        suffix = f" · prepared ({r1})"
        if len(added) != 1 or not added[0].rstrip().endswith(suffix) or author not in added[0]:
            raise creation.platform_failure(
                DETAIL_LOG_ADDED.format(when="after prepared", added=added, suffix=suffix, session=author)
            )

    def step5_end_author(self, case: driver.DriverCase, author: str) -> None:
        case.require_title_stable(author)
        journey = self.journeys["author"]
        journey.session_id = author
        journey.end_session()

    def step6_moved_refuses_work(self, r0: str, r1: str) -> str:
        before = self._shown()
        after = self.owner_write(BODY_B)
        r2 = digest(self._input())
        if r2 in (r0, r1):
            raise creation.binding_failure(DETAIL_DIGEST_SAME.format(digest=r2))
        self.require_owner_write(before, after)
        creation.require_value(ITEM, after, "state.lifecycle_phase", PREPARED_PHASE)
        snapshot = self.snapshot()
        sessions = self.observer.sessions()
        outcome, operation = driver.start_call(self.starts, self.observer, (TELEC, TODO, "work", ITEM), "work-moved")
        if outcome.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                waiting.DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        state = publication.await_terminal(self.observer, operation, OPERATION_SECONDS)
        error = state.get(publication.FIELD_ERROR)
        needles = (r2, r1)
        if (
            state.get(publication.FIELD_STATE) != publication.STATE_FAILED
            or not isinstance(error, str)
            or any(needle not in error for needle in needles)
        ):
            raise creation.platform_failure(
                DETAIL_WORK_REFUSED.format(state=state.get(publication.FIELD_STATE), error=error, needles=list(needles))
            )
        self.starts[operation] = publication.START_REFUSED
        self.require_snapshot(snapshot, "after the refused work")
        deadline = time.monotonic() + OBSERVATION_SECONDS
        while time.monotonic() < deadline:
            creation.require_sessions_equal(sessions, self.observer.sessions(retain=False), "after the refused work")
            payload_work.sleep(POLL_SECONDS)
        creation.require_value(ITEM, self._shown(), "state.lifecycle_phase", PREPARED_PHASE)
        return r2

    def step7_restore(self, r1: str) -> None:
        before = self._shown()
        after = self.owner_write(BODY_A)
        if self._input() != BODY_A or digest(self._input()) != r1:
            raise creation.binding_failure(DETAIL_BODY.format(found=digest(self._input()), expected=r1))
        self.require_owner_write(before, after)

    def step8_work(self, author: str, child: str) -> tuple[driver.DriverCase, str]:
        outcome, operation = driver.start_call(
            self.starts,
            self.observer,
            (TELEC, TODO, "work", ITEM),
            "work",
            evidence=cast(list[creation.EvidenceValue], self.accounting["start_calls"])
            if self.accounting is not None
            else None,
        )
        if outcome.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                waiting.DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        worker = self._discover(self._known(author, child))
        case = self._case("worker", 4, WORK_DRIVER_ID, "work", WORK_PHASE)
        case.check_startup(worker, frozenset({*self.known_sessions, worker}))
        self._require_pool(5)
        instruction = case.claim_call([operation])
        case.check_instruction(worker, instruction)
        for needle in (ITEM, str(self.project / "trees" / ITEM)):
            if needle not in instruction:
                raise creation.platform_failure(DETAIL_INSTRUCTION.format(needle=needle, text=instruction[-600:]))
        case.observe_claim(worker, known_entries=self.known_claims + 1)
        self.starts[operation] = publication.START_CLAIMED
        _, log = creation.dig(self._shown(), "artifact_content.log")
        claims = driver.claim_entries(str(log))
        branch_note = f"on branch {ITEM}"
        if not claims or branch_note not in claims[-1][1]:
            raise creation.platform_failure(
                DETAIL_BRANCH_NOTE.format(note=branch_note, entry=claims[-1] if claims else None)
            )
        roles = [
            session
            for session in (author, child, worker)
            if self._record(session).get(waiting.FIELD_ROLE) == "work-orchestrator"
        ]
        if roles != [worker]:
            raise creation.platform_failure(DETAIL_ROLE_COUNT.format(count=len(roles), found=roles))
        shown = self._shown()
        creation.require_value(ITEM, shown, "state.lifecycle_phase", WORK_PHASE)
        creation.require_value(ITEM, shown, "standing.phase", WORK_PHASE)
        creation.require_value(ITEM, shown, "standing.held_by", worker)
        self.worktree(worker)
        return case, worker

    def _worktree_block(self) -> str:
        """The expected worktree\'s block of the porcelain listing, or an empty text when it is not listed."""
        expected = str(self.project / "trees" / ITEM)
        listing = self._git("worktree list", "worktree", "list", "--porcelain")
        blocks = [chunk.split("\n") for chunk in listing.replace("\r\n", "\n").split("\n\n")]
        block = next((lines for lines in blocks if lines and lines[0] == f"worktree {expected}"), [])
        return "\n".join(block)

    def worktree(self, worker: str) -> None:
        """The worktree and the opening commit the claim queued, read with real `git`."""
        deadline = time.monotonic() + WORKTREE_SECONDS
        expected = str(self.project / "trees" / ITEM)
        listing = ""
        block: list[str] = []
        while time.monotonic() < deadline:
            listing = self._git("worktree list", "worktree", "list", "--porcelain")
            blocks = [chunk.split("\n") for chunk in listing.replace("\r\n", "\n").split("\n\n")]
            block = next((lines for lines in blocks if lines and lines[0] == f"worktree {expected}"), [])
            if block:
                break
            payload_work.sleep(POLL_SECONDS)
        else:
            raise creation.platform_failure(
                DETAIL_WORKTREE.format(what="worktree list", found=listing[-300:], expected=expected)
            )
        if f"branch refs/heads/{ITEM}" not in block:
            raise creation.platform_failure(
                DETAIL_WORKTREE.format(what="the worktree's branch", found=block, expected=f"refs/heads/{ITEM}")
            )
        count = self._git("opening commit count", "rev-list", "--count", f"{ORIGIN}/{MAIN}..{ITEM}")
        if count != "1":
            raise creation.platform_failure(
                DETAIL_WORKTREE.format(what="commits beyond origin/main", found=count, expected="1")
            )
        parent = self._git("opening commit parent", "rev-parse", f"{ITEM}^")
        tip = self._git("origin tip", "rev-parse", f"{ORIGIN}/{MAIN}")
        if parent != tip:
            raise creation.platform_failure(
                DETAIL_WORKTREE.format(what="parent of the opening commit", found=parent, expected=tip)
            )
        self.require_declared(
            "the worktree's HEAD", self._git("worktree declaration", "-C", expected, "show", f"HEAD:{BASE_FILE}")
        )
        message = self._git("opening commit message", "log", "-1", "--format=%B", ITEM)
        if not message.startswith(OPENING_SUBJECT) or f"Session: {worker}" not in message:
            raise creation.platform_failure(
                DETAIL_WORKTREE.format(
                    what="opening commit message",
                    found=message[-300:],
                    expected=f"{OPENING_SUBJECT} ... Session: {worker}",
                )
            )

    def step9_close(self, case: driver.DriverCase, worker: str) -> None:
        self.handover.before(ITEM, worker, WORK_PHASE)
        case.close(worker)
        self.handover.after([ITEM])
        if self.baseline is None:
            raise creation.binding_failure(DETAIL_B9_ATTEMPT.format(detail="B0 was not retained"))
        expected = frozenset((*self.known_sessions, worker))
        current = self.observer.sessions(retain=False)
        if current.ids - self.baseline.ids != expected:
            raise creation.platform_failure(
                DETAIL_B9_SESSION.format(label="B4 post-B0 session set", record=sorted(current.ids - self.baseline.ids))
            )
        for session in sorted(expected):
            record = self._record(session)
            if record.get(waiting.FIELD_CLOSED_AT) is None or record.get(waiting.FIELD_LIFECYCLE) != foundation.CLOSED:
                raise creation.platform_failure(DETAIL_B9_END.format(session=session, record=record))


def run_prepared(
    host: FoundationHost,
    setup: foundation.FixtureSetup,
    project: Path,
    source_root: Path,
    owner_email: str,
    owner_slug: str,
    report_path: Path,
    project_slug: str,
    event_binding: events.EventWindowBinding,
    register_company: Callable[[], None],
    retain: Callable[[str], None],
    accounting: creation.EvidenceObject | None = None,
) -> None:
    """Journey B4; raises JourneyFailure leading with its class."""
    prepared = _Prepared(
        host, setup, project, source_root, owner_email, owner_slug, report_path, register_company, retain
    )
    events.verify_case(event_binding, events.FIRST_CASE)
    retain(f"B10 event evidence retained at {event_binding.carrier_root}")
    observer = prepared.observer
    prepared.accounting = accounting
    failure: BaseException | None = None
    event_seal: start_ledger.JsonObject | None = None
    try:
        creation.require_manual_runner(observer)
        prepared.publication.begin(own_generation=True)
        creation.enter_project(observer, project)
        prepared.baseline = observer.sessions(
            evidence=cast(list[creation.EvidenceValue], accounting["baseline"]) if accounting is not None else None
        )
        prepared.declare_docs_capability(project_slug)
        prepared.git_fixture()
        prepared.setup_pool()
        prepared.preconditions()
        before = driver.shown_with_content(observer, ITEM)
        prepared.clone = prepared.publication.prepare()
        creation.enter_project(observer, project)
        publication.negative_control(observer, ITEM, prepared.baseline, before, prepared.starts)
        prepared.publication.publish()
        prepared.publication.verify_parity()
        creation.enter_project(observer, project)
        prepared.start_b9_outsiders()
        author_case, author, child = prepared.step1_driver()
        prepared.b9_positive_input(child)
        r0, r1 = prepared.step2_move(author, child)
        prepared.b9_wrong_performers(author, child, r1)
        prepared.step3_old_refused(author, child, r0, r1)
        prepared.close_b9_outsiders()
        prepared.step4_prepared(author, child, r1)
        prepared.step5_end_author(author_case, author)
        r2 = prepared.step6_moved_refuses_work(r0, r1)
        prepared.step7_restore(r1)
        worker_case, worker = prepared.step8_work(author, child)
        prepared.step9_close(worker_case, worker)
        event_seal = events.append_case(
            event_binding,
            "B4",
            {
                "selected_variant": "B9",
                "outsider_sessions": dict(prepared.outsider_sessions),
                "sessions": list(prepared.known_sessions) + [worker],
                "author": author,
                "child": child,
                "worker": worker,
                "R0": r0,
                "R1": r1,
                "R2": r2,
                "BODY_C": B9_BODY_C,
                "BODY_A": BODY_A,
                "BODY_B": BODY_B,
                "prepared_log_actor": author,
                "work_log_actor": worker,
            },
            previous_case=events.FIRST_CASE,
        )
    except BaseException as error:
        failure = error
        if accounting is not None:
            accounting["journey_error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            problems = _cleanup(prepared, failure)
            if accounting is not None:
                accounting["cleanup_problems"] = list(problems)
        except BaseException as error:
            if accounting is not None:
                accounting["cleanup_error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            try:
                events.verify_case(event_binding, "B4", event_seal if failure is None else None)
            except BaseException as error:
                if accounting is not None:
                    accounting["seal_error"] = f"{type(error).__name__}: {error}"
                prepared.retain(DETAIL_B9_RETAINED.format(path=event_binding.carrier_root))
                if failure is None:
                    raise
            finally:
                if accounting is not None:
                    accounting["finished_ns"] = time.monotonic_ns()


def _cleanup(prepared: _Prepared, failure: BaseException | None) -> list[str]:
    """Settle the sessions the journey owns, restore the candidate publication and the sidecar, report every failure."""
    b9_problems: list[str] = []
    try:
        prepared.close_b9_outsiders(strict=False)
    except BaseException as error:
        b9_problems.append(f"closing B9 outsider sessions failed: {error}")
    settlement_proven = False
    try:
        settlement = publication.settle_sessions(
            prepared.observer,
            prepared.baseline,
            prepared.starts,
            prepared.controls.directories,
            evidence=cast(creation.EvidenceObject, prepared.accounting["settlement"])
            if prepared.accounting is not None
            else None,
        )
        settlement_proven = settlement.proven
        problems = list(settlement.problems)
    except BaseException as error:
        prepared.b4_retained = True
        problems = [f"public session settlement could not be classified: {error}"]
    problems.extend(b9_problems)
    open_attempts, attempt_error = prepared._b9_open_attempts()
    retained_marker = prepared.controls.root / RETAINED_NAME
    if (
        open_attempts
        or attempt_error
        or b9_problems
        or not settlement_proven
        or retained_marker.exists()
        or prepared.handover.unrelated
    ):
        try:
            prepared._write_b9_retained(problems, attempt_error)
        except BaseException as error:
            prepared.b4_retained = True
            prepared.retain(DETAIL_B9_RETAINED.format(path=retained_marker.resolve()))
            problems.append(f"writing B9 RETAINED.json failed: {error}")
    if not prepared.b4_retained:
        try:
            restore_problems = prepared.publication.restore()
            problems.extend(restore_problems)
            if restore_problems:
                prepared.b4_retained = True
        except BaseException as error:
            prepared.b4_retained = True
            problems.append(f"candidate publication restore could not be proven: {error}")
    if not prepared.b4_retained and settlement_proven and not prepared.handover.unrelated:
        try:
            control_problems = prepared.controls.restore()
            problems.extend(control_problems)
            if control_problems:
                prepared.b4_retained = True
        except BaseException as error:
            prepared.b4_retained = True
            problems.append(f"control restoration could not be proven: {error}")
    else:
        kept = DETAIL_CONTROLS_KEPT.format(control=prepared.controls.root)
        if prepared.handover.unrelated:
            kept = f"{kept}; {prepared.handover.unrelated}"
        problems.append(kept)
        prepared.retain(kept)
    try:
        creation.leave_project(prepared.observer, prepared.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    try:
        candidate_problems = prepared.publication.candidate_unchanged()
        problems.extend(candidate_problems)
        if candidate_problems:
            prepared.b4_retained = True
    except BaseException as error:
        prepared.b4_retained = True
        problems.append(f"candidate publication read-back failed: {error}")
    if prepared.b4_retained and not retained_marker.exists():
        try:
            prepared._write_b9_retained(problems, attempt_error)
        except BaseException as error:
            prepared.retain(DETAIL_B9_RETAINED.format(path=retained_marker.resolve()))
            problems.append(f"writing B9 RETAINED.json failed: {error}")
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        try:
            prepared.publication.note("cleanup-problems", "; ".join(problems))
        except BaseException:
            prepared.retain(DETAIL_B9_RETAINED.format(path=retained_marker.resolve()))
    return problems
