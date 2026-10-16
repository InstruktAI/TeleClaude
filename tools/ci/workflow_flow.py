"""Shared flow-owned controls, registry, ledger and handover state for B5/B7/B6.

The functional bindings are the independently approved B5, B7 revision 6 and B6 artifacts. Their exact hashes and
the bounded SFC failure contract are carried by the flow manifest; B2-B4 retain their separate evidence ownership.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_events as events
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_ledger as start_ledger
from tools.ci import workflow_publication as publication
from tools.ci.workflow_creation import Observer, SessionView
from tools.ci.workflow_foundation import FixtureSetup, FoundationHost

FLOW_NAME: Final = "workflow-b5-b7-b6"
ITEM: Final = "b3-item"
MAIN: Final = "main"
ORIGIN: Final = "origin"
GIT: Final = "git"
TELEC: Final = "telec"
SESSIONS: Final = "sessions"
SHOW: Final = "show"
FULL_FLAG: Final = "--full"
LIST: Final = "list"
ALL_FLAG: Final = "--all"
CLOSED_FLAG: Final = "--closed"
WORKTREE_DIRECTORY: Final = "trees"
INTEGRATION_DIRECTORY: Final = "_integration"
ORIGIN_NAME: Final = "b-item-origin.git"
READY_PHASE: Final = "ready"
WORK_PHASE: Final = "work"
PREPARATION_PHASE: Final = "preparation"
STATE_ACTIVE_RUNNER: Final = "state.active_runner"
STATE_PHASE: Final = "state.lifecycle_phase"
STATE_PHASE_FIELD: Final = "lifecycle_phase"
STATE_HOLD: Final = "hold"
STANDING: Final = "standing"
STANDING_PHASE: Final = "standing.phase"
STANDING_READY_COMMIT: Final = "standing.ready_at_commit"
STANDING_READY_SINCE: Final = "standing.ready_since"
STANDING_ADMITTED: Final = "admitted"
ARTIFACT_LOG: Final = "artifact_content.log"
ARTIFACT_INPUT: Final = "artifact_content.input"
FIELD_ROLE: Final = "role"
FIELD_JOB: Final = "job"
FIELD_PROJECT_PATH: Final = "project_path"
FIELD_NATIVE: Final = "native_session_id"
FIELD_INITIATOR: Final = "initiator_session_id"
FIELD_STATUS: Final = "status"
FIELD_ERROR: Final = "error"
FIELD_RESULT: Final = "result"
FIELD_STATE: Final = "state"
FIELD_OPERATION: Final = "operation_id"
FIELD_SESSION: Final = "session_id"
FIELD_CLOSED_AT: Final = "closed_at"
FIELD_LIFECYCLE: Final = "lifecycle_status"
STATE_COMPLETED: Final = "completed"
STATE_FAILED: Final = "failed"
STATE_ACTIVE: Final = "active"
STATUS_SUCCESS: Final = "success"
STATUS_OK: Final = "ok"
ROLE_WORK: Final = "work-orchestrator"
ROLE_BUILDER: Final = "builder"
ROLE_INTEGRATOR: Final = "integrator"
PROC_WORK: Final = "sdlc/procedure/lifecycle/work/overview-v2"
PROC_BUILD: Final = "sdlc/procedure/lifecycle/work/build-v2"
PROC_INTEGRATE: Final = "sdlc/procedure/lifecycle/integrate"
B5_COMMIT_1: Final = "feat(b5): add feature file"
B5_COMMIT_2: Final = "feat(b5): extend feature file"
B11_SENTINEL_TEXT: Final = "b11 dirty sentinel\n"
B11_SENTINEL_SHA256: Final = "9da495e86c2785fb74ddd5e8fe6d2afa5ae0ee387a0e04d6810168b092c8dc81"
B11_LOCAL_HEAD_MESSAGE: Final = "chore(b5): temporary local head for stamp refusal"
B6_COMMIT: Final = "feat(b3-item): integrate the b5 feature"
ENCODING: Final = "utf-8"
JSON_INDENT: Final = 2
JSON_SEPARATOR_VALUES: Final = (",", ":")
LINE_BREAK: Final = "\n"
PATH_SEPARATOR: Final = "/"
REGISTRY_FIELD: Final = "plan_sets"
MESSAGE_KEY_PREFIX: Final = "message:"
FLOW_ID_FIELD: Final = "flow_id"
CHAIN_FIELD: Final = "declared_chain"
APPROVALS_FIELD: Final = "approval_records"
SESSIONS_FIELD: Final = "sessions"
SFC_STATUS_FIELD: Final = "cleanup"
RETAINED_NAME: Final = "RETAINED.json"
MANIFEST_NAME: Final = "manifest.json"
LEDGER_NAME: Final = "starts.jsonl"
RETAINED_STATE: Final = "RETAINED-UNPROVEN"
RETAINED_REASON: Final = "SFC P4 has no reviewed proof for every owned pane and accepted launch"
RETAINED_MARKER: Final = "SFC resources retained at {path}; CLEANUP PASS remains unavailable"
SFC_UNPROVEN: Final = (
    "P4 is unproven: a trigger or accepted launch may still create a session, and fixture panes may still execute"
)
SFC_CHAIN_B5: Final = "B5"
SFC_CHAIN_B7: Final = "B7"
SFC_CHAIN_B6: Final = "B6"
B5_SCENARIO: Final = "UC-WF-B5"
B7_SCENARIO: Final = "UC-WF-B7"
B6_SCENARIO: Final = "UC-WF-B6"
B5_APPROVAL: Final = "b5-review-stamp-approval.json"
B7_APPROVAL: Final = "b7-held-ready-approval.json"
B6_APPROVAL: Final = "b6-integration-delivery-approval.json"
SFC_APPROVAL: Final = "flow-finalizer-contract-approval.json"
B5_HASH: Final = "638b9dcd405177b9b644b6d1d2adf38292dd1de7646b1b0b36ef069094065f16"
B7_HASH: Final = "64ac539451f85353c4c4bc4bb713c717fc76f7bb27db1179b1af79bba17c4ca5"
B6_HASH: Final = "47094e9234e60ed2d527aef021b18844a7d1c259f05c263d8e8d24e696ff71f4"
SFC_HASH: Final = "0f854a0cf428947e00f44c992d55442580989d76d367063eec9e8f4e65485fc9"
MINIMUM_B5_CONTROLS: Final = 8
MINIMUM_B7_CONTROLS: Final = 11
POOL_SPARE_COUNT: Final = 2
START_RECORD_SECONDS: Final = 900.0
OPERATION_POLL_SECONDS: Final = 2.0
FLOW_COMMAND_SECONDS: Final = 60.0
RECORD_POLL_SECONDS: Final = 2.0

DETAIL_ITEM: Final = "the shared flow item is absent from the prepared disposable project"
DETAIL_CANDIDATE: Final = "the candidate checkout identity changed during the chained workflow"
DETAIL_MANIFEST: Final = "the B5/B7 handover manifest is missing, unreadable or malformed"
DETAIL_PLAN_REGISTRY: Final = "the flow plan registry is missing, unreadable or differs from its declaration"
DETAIL_CONTROL_MAP: Final = "the launch record and the public session record do not identify one actor"
DETAIL_PLAN_ACTOR: Final = "no active launch owns {procedure} plan index {index} for role {role}"
DETAIL_NATIVE: Final = "the fixture launch or native hook evidence is unreadable for {session}"
DETAIL_CLOSED: Final = "session {session} did not reach a retained closed lifecycle record: {record!r}"
DETAIL_COMMAND: Final = "{command} exited {status}: {output!r}"
DETAIL_GIT: Final = "{command} returned {status}: {output!r}"
DETAIL_TIMEOUT: Final = "{what} was not observed within {seconds} seconds: {found!r}"
DETAIL_RETENTION: Final = "the retained SFC marker could not be written: {error}"
DETAIL_FLOW_STOPPED: Final = "the declared flow was already finalized and retained"
DETAIL_ROLE: Final = "session {session} has role {found!r}, not {expected!r}"
DETAIL_START_SET: Final = "new sessions are {found!r}, not the required role set {expected!r}"
DETAIL_WORKTREE: Final = "the disposable worktree operation failed: {output!r}"
DETAIL_JSON: Final = "the owned workflow record is malformed: {path}"
DETAIL_DOOR: Final = "the approved declared chain does not include {case}"
DETAIL_LEDGER: Final = "the owned start ledger is invalid: {detail}"
DETAIL_OPERATION: Final = "operation {operation} ended in {state!r}: {detail!r}"
DETAIL_CASE_LEDGER: Final = "the {case} closed action list was already declared"
DETAIL_FINALIZER: Final = "the shared flow finalizer could not complete: {detail}"
STOP_MARKER: Final = "stop"
FIELD_KEY_KIND: Final = "key_kind"
FIELD_PLAN_KEY: Final = "key"
FIELD_PLAN_INDEX: Final = "index"

type Json = Mapping[str, object]
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type MutableJson = dict[str, JsonValue]
type PlanSets = dict[str, list[controls.Plan]]

B5_ACTIONS: Final = (
    {"label": "w2-start", "kind": start_ledger.RECORD_OPERATION},
    {"label": "w2-child", "kind": start_ledger.RECORD_SESSION, "parent": "w2-start"},
    {"label": "reviewed", "kind": start_ledger.RECORD_EFFECT},
    {"label": "finding", "kind": start_ledger.RECORD_EFFECT},
    {"label": "reply", "kind": start_ledger.RECORD_EFFECT},
    {"label": "reviewed-wrong", "kind": start_ledger.RECORD_EFFECT},
    {"label": "finding-wrong", "kind": start_ledger.RECORD_EFFECT},
    {"label": "reply-wrong", "kind": start_ledger.RECORD_EFFECT},
    {"label": "kickback-wrong", "kind": start_ledger.RECORD_EFFECT},
    {"label": "release-wrong", "kind": start_ledger.RECORD_EFFECT},
    {"label": "stamp-performer", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "stamp-nonhead", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "stamp-empty", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "dirty-sentinel", "kind": start_ledger.RECORD_EFFECT},
    {"label": "stamp-unclean", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "temporary-local-head", "kind": start_ledger.RECORD_EFFECT},
    {"label": "stamp-worktree-head", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "stamp-ok", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "w3-start", "kind": start_ledger.RECORD_OPERATION},
    {"label": "stamp-ok2", "kind": start_ledger.RECORD_TRIGGER},
)
B7_ACTIONS: Final = (
    {"label": "ready-door", "kind": start_ledger.RECORD_OPERATION},
    {"label": "ready-no-reason", "kind": start_ledger.RECORD_OPERATION},
    {"label": "ready-no-session", "kind": start_ledger.RECORD_OPERATION},
    {"label": "session-S_R", "kind": start_ledger.RECORD_SESSION},
    {"label": "session-S2", "kind": start_ledger.RECORD_SESSION},
    {"label": "reasonone", "kind": start_ledger.RECORD_OPERATION},
    {"label": "reasontwo", "kind": start_ledger.RECORD_OPERATION},
)
B6_ACTIONS: Final = (
    {"label": "int1", "kind": start_ledger.RECORD_TRIGGER},
    {"label": "refused-work", "kind": start_ledger.RECORD_OPERATION},
    {"label": "int2", "kind": start_ledger.RECORD_TRIGGER},
)


def procedure_key(procedure: str) -> str:
    """The opaque key for a procedure loader, shared with the external native fixture."""
    return hashlib.sha256(procedure.encode(ENCODING)).hexdigest()


def message_key(first_line: str) -> str:
    """The opaque key for an ordinary first input line, shared with the external native fixture."""
    return hashlib.sha256(f"{MESSAGE_KEY_PREFIX}{first_line}".encode(ENCODING)).hexdigest()


def declared_chain(selection: frozenset[str]) -> tuple[str, ...]:
    """The run's declared chain follows the selected, prepared scenarios in order."""
    if not selection:
        return (SFC_CHAIN_B5, SFC_CHAIN_B7, SFC_CHAIN_B6)
    selected = {
        case
        for case, scenario in ((SFC_CHAIN_B5, B5_SCENARIO), (SFC_CHAIN_B7, B7_SCENARIO), (SFC_CHAIN_B6, B6_SCENARIO))
        if scenario in selection
    }
    return tuple(case for case in (SFC_CHAIN_B5, SFC_CHAIN_B7, SFC_CHAIN_B6) if case in selected)


def _command_plan(name: str, argv: Sequence[str], gate: str) -> controls.Command:
    return controls.command(name, list(argv), gate)


def _late_plan(name: str, argument_file: str, gate: str) -> controls.Command:
    return controls.late(name, argument_file, gate)


def flow_plan_sets(chain: Sequence[str]) -> PlanSets:
    """All plans for the selected chain, fixed before the first fixture launch."""
    work: list[controls.Plan] = [
        controls.PlanFile(
            commands=[
                controls.command("claim", [TELEC, "todo", "work", ITEM]),
                controls.command("child", [TELEC, "todo", "child", ITEM]),
                _late_plan("reviewed", "reviewed.argv", "go_rev"),
                _late_plan("finding", "finding.argv", "go_find"),
                _late_plan("replywrong", "replywrong.argv", "go_replywrong"),
                _late_plan("stamp_nonhead", "stamp_nonhead.argv", "go_nh"),
                _late_plan("stamp_empty", "stamp_empty.argv", "go_empty"),
                _late_plan("stampunclean", "stampunclean.argv", "go_unclean"),
                _late_plan("stampworktree", "stampworktree.argv", "go_worktree"),
                _late_plan("stamp_ok", "stamp_ok.argv", "go_ok"),
            ]
        ),
        controls.PlanFile(
            commands=[
                controls.command("claim", [TELEC, "todo", "work", ITEM]),
                _late_plan("stamp_ok2", "stamp_ok2.argv", "go_ok2"),
            ]
        ),
    ]
    build: list[controls.Plan] = [
        controls.PlanFile(
            commands=[
                controls.Command(
                    name="write1",
                    writes=[
                        {"path": "feature.txt", "mode": "create", "text": "b5 file one\n"},
                        {"path": "Makefile", "mode": "create", "text": "test:\n\t@true\n"},
                    ],
                    wait_for="go_w1",
                ),
                _command_plan(
                    "commit1",
                    (TELEC, "code", "commit", "--approved", B5_COMMIT_1, "--only", "feature.txt", "Makefile"),
                    "go_w1",
                ),
                _late_plan("reviewedwrong", "reviewedwrong.argv", "go_reviewedwrong"),
                _late_plan("findingwrong", "findingwrong.argv", "go_findingwrong"),
                _late_plan("kickbackwrong", "kickbackwrong.argv", "go_kickbackwrong"),
                _late_plan("releasewrong", "releasewrong.argv", "go_releasewrong"),
                _late_plan("stampperformer", "stampperformer.argv", "go_stampperformer"),
                _late_plan("reply", "reply.argv", "go_reply"),
                controls.Command(
                    name="write2",
                    writes=[{"path": "feature.txt", "mode": "append", "text": "b5 file two\n"}],
                    wait_for="go_c2",
                ),
                _command_plan(
                    "commit2",
                    (TELEC, "code", "commit", "--approved", B5_COMMIT_2, "--only", "feature.txt"),
                    "go_c2",
                ),
                controls.Command(
                    name="dirtywrite",
                    writes=[{"path": "feature.txt", "mode": "append", "text": B11_SENTINEL_TEXT}],
                    wait_for="go_dirtywrite",
                ),
            ]
        )
    ]
    plans: PlanSets = {
        procedure_key(PROC_WORK): work,
        procedure_key(PROC_BUILD): build,
    }
    if SFC_CHAIN_B7 in chain:
        plans[procedure_key(PROC_WORK)].append(
            controls.PlanFile(
                commands=[
                    controls.command("claim", [TELEC, "todo", "work", ITEM]),
                    controls.command("releasenokey", [TELEC, "todo", "act", ITEM, "release"], "go_nokey"),
                    _late_plan("releasestale", "releasestale.argv", "go_stale"),
                    controls.command("recall", [TELEC, "todo", "work", ITEM], "go_recall"),
                    _late_plan("releaseok", "releaseok.argv", "go_ok"),
                ]
            )
        )
        plans[message_key("b7 session one")] = [
            controls.PlanFile(
                commands=[
                    _command_plan("reasonone", (TELEC, "todo", "work", ITEM, "--reason", "b7 reason one"), "go_r1")
                ]
            )
        ]
        plans[message_key("b7 session two")] = [
            controls.PlanFile(
                commands=[
                    _command_plan("reasontwo", (TELEC, "todo", "work", ITEM, "--reason", "b7 reason two"), "go_r2")
                ]
            )
        ]
    if SFC_CHAIN_B6 in chain:
        plans[procedure_key(PROC_INTEGRATE)] = [
            controls.PlanFile(
                commands=[
                    controls.command("int1", [TELEC, "todo", "integrate", ITEM], "go_int1"),
                    controls.Command(
                        name="commit_int",
                        argv=[TELEC, "code", "commit", "--approved", B6_COMMIT],
                        wait_for="go_commit",
                        cwd="trees/_integration",
                    ),
                    controls.command("int2", [TELEC, "todo", "integrate", ITEM], "go_int2"),
                ]
            )
        ]
    return plans


def approval_map(chain: Sequence[str]) -> dict[str, str]:
    """The approved record hashes the current declared chain uses."""
    approvals = {SFC_CHAIN_B5: B5_HASH}
    if SFC_CHAIN_B7 in chain:
        approvals[SFC_CHAIN_B7] = B7_HASH
    if SFC_CHAIN_B6 in chain:
        approvals[SFC_CHAIN_B6] = B6_HASH
    approvals[SFC_APPROVAL] = SFC_HASH
    return approvals


def approval_for(case: str) -> str:
    """Return the exact approved assertion hash named by a handover."""
    return {
        SFC_CHAIN_B5: B5_HASH,
        SFC_CHAIN_B7: B7_HASH,
        SFC_CHAIN_B6: B6_HASH,
    }[case]


@dataclass
class WorkflowFlow:
    """The one shared project, control pool, registry and ledger across the declared B5/B7/B6 chain."""

    host: FoundationHost
    setup: FixtureSetup
    source_root: Path
    project: Path
    owner_email: str
    project_slug: str
    chain: tuple[str, ...]
    register_company: Callable[[], None]
    retain: Callable[[str], None]
    event_window: events.EventWindowBinding | None = None
    event_previous_seal: start_ledger.JsonObject | None = None
    event_case_seal: start_ledger.JsonObject | None = None
    root: Path = field(init=False)
    observer: Observer = field(init=False)
    controls: controls.Controls = field(init=False)
    publication: publication.Publication = field(init=False)
    plan_sets: PlanSets = field(init=False)
    control_setups: list[FixtureSetup] = field(default_factory=list)
    ledger: start_ledger.StartLedger | None = None
    baseline: SessionView | None = None
    candidate_identity: str = ""
    fixture_publication_sha: str = ""
    sessions: dict[str, str] = field(default_factory=dict)
    integrators: set[str] = field(default_factory=set)
    finalized: bool = False
    finalizer_errors: list[str] = field(default_factory=list)
    item_snapshot: Json | None = None
    finalizer_summary: MutableJson = field(default_factory=dict)
    finalizer_ledger_error: str | None = None

    def __post_init__(self) -> None:
        """Reserve the disposable flow root and make cleanup retention active before setup can launch anything."""
        self.project = self.project.resolve()
        self.source_root = self.source_root.resolve()
        self.root = self.setup.control.parent / FLOW_NAME
        self.retain(RETAINED_MARKER.format(path=self.root))
        self.root.mkdir(parents=True)
        self.observer = Observer(self.host)
        self.controls = controls.Controls(self.setup, FLOW_NAME)
        self.publication = publication.Publication(
            self.host,
            self.observer,
            self.root,
            self.source_root,
            self.register_company,
        )
        self.plan_sets = flow_plan_sets(self.chain)
        if self.event_window is not None:
            self.retain(f"B10 event evidence retained at {self.event_window.carrier_root}")
        self.write_retained_marker()

    def setup_flow(self) -> None:
        """Prepare candidate publication, one fixed chain pool, registry and ledger before any start."""
        if not self.chain or self.chain[0] != SFC_CHAIN_B5:
            raise creation.binding_failure(DETAIL_DOOR.format(case=SFC_CHAIN_B5))
        if self.event_window is None:
            raise creation.binding_failure(DETAIL_MANIFEST)
        events.verify_case(self.event_window, "B4", self.event_previous_seal)
        creation.require_manual_runner(self.observer)
        creation.enter_project(self.observer, self.project)
        self.baseline = self.observer.sessions()
        self.publication.begin(own_generation=True)
        self.candidate_identity = self.publication.candidate
        self.publication.prepare()
        self.fixture_publication_sha = self.git(
            ("rev-parse", "HEAD"), cwd=self.publication.clone, what="fixture publication revision"
        )
        self.publication.publish()
        self.publication.verify_parity()
        creation.enter_project(self.observer, self.project)
        count = MINIMUM_B7_CONTROLS if SFC_CHAIN_B7 in self.chain else MINIMUM_B5_CONTROLS
        self.control_setups = self.controls.shared_pool(self.plan_sets, count)
        self.verify_registry()
        self.ledger = start_ledger.StartLedger.create(self.root / LEDGER_NAME)
        self.ledger.declare_case(SFC_CHAIN_B5, B5_ACTIONS)
        self.write_manifest({})
        self.write_retained_marker()

    @property
    def ledger_path(self) -> Path:
        return self.root / LEDGER_NAME

    @property
    def temporary_root(self) -> Path:
        return self.setup.control.parent

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def retained_path(self) -> Path:
        return self.root / RETAINED_NAME

    def attach(self, host: FoundationHost) -> None:
        """Bind the next case's evidence sink while preserving the one flow's shared state."""
        self.host = host
        self.observer.host = host
        self.publication.host = host
        self.publication.observer = self.observer

    def require_ledger(self) -> start_ledger.StartLedger:
        if self.ledger is None:
            self.ledger = start_ledger.StartLedger.load(self.ledger_path)
        return self.ledger

    def begin_case(self, case: str, actions: Sequence[start_ledger.ActionSpec]) -> start_ledger.StartLedger:
        """Load the chain authority and record the case's complete closed list before any call or gate."""
        return self.register_case(case, actions)

    def verify_registry(self) -> None:
        """Read back the immutable registry and pool before a fixture launch can use them."""
        registry_path = self.controls.registry_path
        claims_path = self.controls.claims_path
        if registry_path is None or claims_path is None or not registry_path.is_file() or not claims_path.is_dir():
            raise creation.binding_failure(DETAIL_PLAN_REGISTRY)
        try:
            value = json.loads(registry_path.read_text(encoding=ENCODING))
        except (OSError, ValueError) as error:
            raise creation.binding_failure(DETAIL_PLAN_REGISTRY) from error
        expected = {REGISTRY_FIELD: {key: list(plans) for key, plans in self.plan_sets.items()}}
        if value != expected or len(self.control_setups) < MINIMUM_B5_CONTROLS:
            raise creation.binding_failure(DETAIL_PLAN_REGISTRY)
        if SFC_CHAIN_B7 in self.chain and len(self.control_setups) < MINIMUM_B7_CONTROLS:
            raise creation.binding_failure(DETAIL_PLAN_REGISTRY)
        try:
            configuration = json.loads(self.setup.configuration.read_text(encoding=ENCODING))
        except (OSError, ValueError) as error:
            raise creation.binding_failure(DETAIL_PLAN_REGISTRY) from error
        expected_pool = [str(setup.control) for setup in self.control_setups]
        active_count = len(self.control_setups) - POOL_SPARE_COUNT
        if (
            not isinstance(configuration, Mapping)
            or configuration.get(controls.POOL_KEY) != expected_pool
            or configuration.get(controls.PLAN_REGISTRY_CONFIG_KEY) != str(registry_path)
            or configuration.get(controls.PLAN_CLAIMS_CONFIG_KEY) != str(claims_path)
            or configuration.get(controls.PLAN_CONTROL_COUNT_FIELD) != active_count
            or configuration.get(controls.PLAN_SPARE_COUNT_FIELD) != POOL_SPARE_COUNT
        ):
            raise creation.binding_failure(DETAIL_PLAN_REGISTRY)

    def read_manifest(self) -> Json:
        try:
            value = json.loads(self.manifest_path.read_text(encoding=ENCODING))
        except (OSError, ValueError) as error:
            raise creation.binding_failure(DETAIL_MANIFEST) from error
        if not isinstance(value, Mapping):
            raise creation.binding_failure(DETAIL_MANIFEST)
        return {str(key): item for key, item in value.items()}

    def verify_handover(self, manifest: Json) -> None:
        expected: dict[str, JsonValue] = {
            FLOW_ID_FIELD: self.require_ledger().flow_id,
            CHAIN_FIELD: list(self.chain),
            APPROVALS_FIELD: cast(JsonValue, approval_map(self.chain)),
            "ledger_path": str(self.ledger_path),
            "registry_path": str(self.controls.registry_path),
            "claims_path": str(self.controls.claims_path),
            "controls_root": str(self.controls.root),
            "fixture_publication_sha": self.fixture_publication_sha,
            "candidate_identity": self.candidate_identity,
            "item": ITEM,
        }
        if self.event_window is not None:
            expected["event_window"] = self.event_window.json_value()
        if self.event_case_seal is not None:
            expected["event_case_seal"] = self.event_case_seal
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise creation.binding_failure(DETAIL_MANIFEST)

    def record_session(self, session_id: str, role: str) -> None:
        self.sessions[session_id] = role
        if role == ROLE_INTEGRATOR:
            self.integrators.add(session_id)

    def _session_record(self, session_id: str, *, retain: bool = False) -> Json | None:
        outcome = self.observer.run((TELEC, SESSIONS, SHOW, session_id, FULL_FLAG), retain=retain)
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        return record

    def session_record(self, session_id: str, *, retain: bool = False) -> Json:
        record = self._session_record(session_id, retain=retain)
        if record is None:
            raise creation.binding_failure(DETAIL_NATIVE.format(session=session_id))
        return record

    def control_for_session(self, session_id: str) -> tuple[FixtureSetup, Json]:
        """Map a public session to exactly one fixture control by native id, never by launch order."""
        record = self.session_record(session_id)
        native = record.get(FIELD_NATIVE)
        if not isinstance(native, str) or not native:
            raise creation.binding_failure(DETAIL_CONTROL_MAP)
        matches: list[tuple[FixtureSetup, Json]] = []
        for setup in self.control_setups:
            launch = self._read_object(setup.control / foundation.LAUNCH_FILE)
            if launch is not None and launch.get(FIELD_NATIVE) == native:
                matches.append((setup, launch))
        if len(matches) != 1:
            raise creation.binding_failure(DETAIL_CONTROL_MAP)
        return matches[0]

    def plan_actor(self, procedure: str, index: int, role: str, timeout_seconds: float = START_RECORD_SECONDS) -> str:
        """Find the session that claimed a procedure-key plan and match its native launch to public identity."""
        key = procedure_key(procedure)
        deadline = time.monotonic() + timeout_seconds
        found: list[str] = []
        while time.monotonic() < deadline:
            for setup in self.control_setups:
                launch = self._read_object(setup.control / foundation.LAUNCH_FILE)
                if (
                    launch is None
                    or launch.get(FIELD_KEY_KIND) != "procedure"
                    or launch.get(FIELD_PLAN_KEY) != key
                    or launch.get(FIELD_PLAN_INDEX) != index
                ):
                    continue
                native = launch.get(FIELD_NATIVE)
                if not isinstance(native, str) or not native:
                    raise creation.binding_failure(DETAIL_CONTROL_MAP)
                session = self.session_for_native(native, role)
                if session is not None:
                    found.append(session)
            unique = sorted(set(found))
            if len(unique) == 1:
                return unique[0]
            if len(unique) > 1:
                raise creation.binding_failure(DETAIL_PLAN_ACTOR.format(procedure=procedure, index=index, role=role))
            time.sleep(OPERATION_POLL_SECONDS)
        raise creation.binding_failure(DETAIL_PLAN_ACTOR.format(procedure=procedure, index=index, role=role))

    def message_actor(self, first_line: str, index: int, role: str | None = None, timeout_seconds: float = 0.0) -> str:
        key = message_key(first_line)
        deadline = time.monotonic() + timeout_seconds
        while True:
            matches: list[str] = []
            for setup in self.control_setups:
                launch = self._read_object(setup.control / foundation.LAUNCH_FILE)
                if (
                    launch is None
                    or launch.get(FIELD_KEY_KIND) != "message"
                    or launch.get(FIELD_PLAN_KEY) != key
                    or launch.get(FIELD_PLAN_INDEX) != index
                ):
                    continue
                native = launch.get(FIELD_NATIVE)
                if not isinstance(native, str) or not native:
                    raise creation.binding_failure(DETAIL_CONTROL_MAP)
                session = self.session_for_native(native, role)
                if session is not None:
                    matches.append(session)
            unique = sorted(set(matches))
            if len(unique) > 1:
                raise creation.binding_failure(DETAIL_PLAN_ACTOR.format(procedure=first_line, index=index, role=role))
            if unique:
                return unique[0]
            if time.monotonic() >= deadline:
                raise creation.binding_failure(DETAIL_PLAN_ACTOR.format(procedure=first_line, index=index, role=role))
            time.sleep(OPERATION_POLL_SECONDS)

    def session_for_native(self, native: str, role: str | None = None) -> str | None:
        for session_id in self.observer.sessions(retain=False).ids:
            record = self._session_record(session_id, retain=False)
            if record is None or record.get(FIELD_NATIVE) != native:
                continue
            found_role = record.get(FIELD_ROLE)
            if role is not None and found_role != role:
                raise creation.binding_failure(DETAIL_ROLE.format(session=session_id, found=found_role, expected=role))
            self.record_session(session_id, str(found_role) if isinstance(found_role, str) else "")
            return session_id
        return None

    def setup_for_session(self, session_id: str) -> FixtureSetup:
        setup, _ = self.control_for_session(session_id)
        return setup

    def journey(self, session_id: str, *, message: str | None = None) -> foundation.Journey:
        return foundation.Journey(
            self.host,
            self.setup_for_session(session_id),
            self.project,
            self.owner_email,
            message=message,
        )

    def frame(self, session_id: str, name: str, timeout_seconds: float = FLOW_COMMAND_SECONDS) -> Json:
        journey = self.journey(session_id)
        journey.session_id = session_id
        return journey.await_frame(name, time.monotonic() + timeout_seconds)

    def gate(self, session_id: str, name: str) -> None:
        setup = self.setup_for_session(session_id)
        path = setup.control / name
        try:
            with path.open("x", encoding=ENCODING) as handle:
                handle.write("1\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise creation.binding_failure(
                DETAIL_COMMAND.format(command=name, status=type(error).__name__, output="")
            ) from error

    def late_argv(self, session_id: str, name: str, argv: Sequence[str]) -> None:
        setup = self.setup_for_session(session_id)
        path = setup.control / name
        try:
            with path.open("x", encoding=ENCODING) as handle:
                handle.write(json.dumps(list(argv)))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise creation.binding_failure(
                DETAIL_COMMAND.format(command=name, status=type(error).__name__, output="")
            ) from error

    def cli(self, argv: Sequence[str], *, retain: bool = True) -> foundation.Outcome:
        return self.observer.run(argv, retain=retain)

    def git(self, argv: Sequence[str], *, cwd: Path | None = None, what: str = GIT) -> str:
        working = cwd if cwd is not None else self.project
        outcome = self.host.process((GIT, *argv), working, self.host.environment, FLOW_COMMAND_SECONDS)
        if outcome.exit_status != 0:
            raise creation.binding_failure(
                DETAIL_GIT.format(command=what, status=outcome.exit_status, output=outcome.output[-400:])
            )
        return outcome.output.strip()

    def operation(self, operation_id: str, timeout_seconds: float) -> Json:
        return publication.await_terminal(self.observer, operation_id, timeout_seconds)

    def _read_object(self, path: Path) -> Json | None:
        try:
            value = json.loads(path.read_text(encoding=ENCODING))
        except (OSError, ValueError):
            return None
        return {str(key): entry for key, entry in value.items()} if isinstance(value, Mapping) else None

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("w", encoding=ENCODING) as handle:
            handle.write(json.dumps(value, indent=JSON_INDENT) + LINE_BREAK)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def write_retained_marker(self, extra: Mapping[str, JsonValue] | None = None) -> None:
        """Durably preserve the complete flow root with the SFC's explicit unresolved proof state."""
        try:
            if self.retained_path.exists():
                existing = self._read_object(self.retained_path)
                if existing is None:
                    raise creation.binding_failure(DETAIL_RETENTION.format(error="invalid existing marker"))
                current = cast(MutableJson, dict(existing))
            else:
                current = {}
            current.update(
                {
                    "status": RETAINED_STATE,
                    "reason": RETAINED_REASON,
                    "flow_id": self.ledger.flow_id if self.ledger is not None else None,
                    "declared_chain": list(self.chain),
                    "open_attempt_ids": [attempt.identifier for attempt in self.ledger.open_attempts]
                    if self.ledger is not None
                    else (["unreadable-ledger"] if self.finalizer_ledger_error else ["ledger-not-yet-established"]),
                    "item": ITEM,
                    "project": str(self.project),
                    "sidecar": str(self.setup.configuration),
                    "controls": str(self.controls.root),
                    "registry": str(self.controls.registry_path) if self.controls.registry_path else None,
                    "claims": str(self.controls.claims_path) if self.controls.claims_path else None,
                    "publication_clone": str(self.publication.clone),
                    "origin": str(self.temporary_root / ORIGIN_NAME),
                    "candidate_identity": self.candidate_identity or None,
                    "fixture_publication_sha": self.fixture_publication_sha or None,
                    "event_window": self.event_window.json_value() if self.event_window is not None else None,
                    "event_case_seal": self.event_case_seal,
                    "proofs": {
                        "P1_session_lifecycle": "unproven until finalizer observations",
                        "P2_start_consumption": "unresolved ledger entries remain open",
                        "P3_daemon_stopped": "pending profile boundary make stop outcome",
                        "P4_fixture_processes_and_panes": "unproven by the approved contract",
                    },
                }
            )
            if extra is not None:
                current.update(extra)
            self._atomic_json(self.retained_path, current)
        except OSError as error:
            raise creation.binding_failure(DETAIL_RETENTION.format(error=type(error).__name__)) from error

    def record_profile_stop(self, outcome: str) -> None:
        """Record the independent graceful-stop result; it cannot establish the unresolved process proof P4."""
        stop_proven = outcome == "stopped"
        finalizer = self.finalizer_summary
        p1 = finalizer.get("P1_session_lifecycle") if finalizer else "unproven"
        p2 = finalizer.get("P2_start_consumption") if finalizer else "unproven"
        self.write_retained_marker(
            {
                "daemon_stop_outcome": outcome or "unobserved",
                "proofs": {
                    "P1_session_lifecycle": "proven" if p1 == "proven" else "unproven",
                    "P2_start_consumption": "unproven" if p2 != "classified" else "classified",
                    "P3_daemon_stopped": "proven" if stop_proven else "unproven",
                    "P4_fixture_processes_and_panes": "unproven by the approved contract",
                },
            }
        )

    def finalize(self, failure: str | None = None) -> None:
        """Close owned public sessions and preserve all resources under the approved SFC boundary."""
        if self.finalized:
            return
        self.finalized = True
        issues = [failure] if failure else []
        starts = self._finalizer_start_snapshot(issues)
        classification_complete = self.finalizer_ledger_error is None
        baseline_ids = self.baseline.ids if self.baseline is not None else frozenset()
        sessions = set(self.sessions)
        try:
            sessions.update(set(self.all_current_project_sessions()) - set(baseline_ids))
        except BaseException as error:
            issues.append(f"initial session inventory: {error}")
            classification_complete = False
        roles: dict[str, str] = {}
        classification_complete = (
            self._run_finalizer_stage(
                "session role inventory", lambda: roles.update(self._finalizer_roles(sessions, issues)), issues
            )
            and classification_complete
        )
        if any(role == "unknown" for role in roles.values()):
            classification_complete = False
        session_rows: dict[str, JsonValue] = {}
        ordinary = [session for session, role in roles.items() if role not in (ROLE_INTEGRATOR, "unknown")]
        classification_complete = (
            self._run_finalizer_stage(
                "ordinary session closure",
                lambda: self._finalizer_end_sessions(ordinary, roles, session_rows, issues),
                issues,
            )
            and classification_complete
        )
        if not self._finalizer_sessions_closed(ordinary, session_rows):
            classification_complete = False
        issue_count = len(issues)
        self._run_finalizer_stage(
            "ready hold and admitted recovery", lambda: self._finalizer_hold_ready(issues), issues
        )
        if len(issues) != issue_count:
            classification_complete = False
        integrators = [session for session, role in roles.items() if role in (ROLE_INTEGRATOR, "unknown")]
        classification_complete = (
            self._run_finalizer_stage(
                "integrator session closure",
                lambda: self._finalizer_end_sessions(integrators, roles, session_rows, issues),
                issues,
            )
            and classification_complete
        )
        if not self._finalizer_sessions_closed(integrators, session_rows):
            classification_complete = False
        issue_count = len(issues)
        classification_complete = (
            self._run_finalizer_stage(
                "public session sweep", lambda: self._finalizer_sweep(baseline_ids, session_rows, issues), issues
            )
            and classification_complete
        )
        if len(issues) != issue_count or not all(
            isinstance(row, Mapping) and row.get("closed") is True for row in session_rows.values()
        ):
            classification_complete = False
        if classification_complete:
            self._run_finalizer_stage("publication restore", lambda: self._finalizer_restore(issues), issues)
        else:
            issues.append("publication restore deferred because session classification or closure is incomplete")
            self.retain(RETAINED_MARKER.format(path=self.root))
        self._run_finalizer_stage("fixture stop markers", lambda: self._finalizer_stop_fixtures(issues), issues)
        try:
            current = start_ledger.StartLedger.load(self.ledger_path)
            self.ledger = current
            self.finalizer_ledger_error = None
        except (OSError, ValueError) as error:
            current = None
            self.ledger = None
            self.finalizer_ledger_error = str(error)
            issues.append(DETAIL_LEDGER.format(detail=str(error)))
        open_ids = (
            [attempt.identifier for attempt in current.open_attempts]
            if current is not None
            else (["unreadable-ledger"] if self.finalizer_ledger_error else [])
        )
        self.finalizer_summary = {
            "status": RETAINED_STATE,
            "failure": failure,
            "issues": cast(JsonValue, issues),
            "sessions": cast(JsonValue, session_rows),
            "integrators": cast(JsonValue, sorted(integrators)),
            "start_ledger": cast(JsonValue, starts),
            "open_attempt_ids": cast(JsonValue, open_ids),
            "start_ledger_error": self.finalizer_ledger_error,
            "P1_session_lifecycle": "proven"
            if classification_complete
            and all(isinstance(row, Mapping) and row.get("closed") is True for row in session_rows.values())
            else "unproven",
            "P2_start_consumption": "unproven; explicit starts and async launch backlog lack public settlement evidence",
            "P4_fixture_processes_and_panes": "unproven by the approved contract",
        }
        try:
            self.write_manifest({"finalizer": self.finalizer_summary})
            self.write_retained_marker({"finalizer": self.finalizer_summary})
        except BaseException as error:
            self._finalizer_failure(error)

    @staticmethod
    def _run_finalizer_stage(label: str, action: Callable[[], None], issues: list[str]) -> bool:
        try:
            action()
            return True
        except BaseException as error:
            issues.append(f"{label}: {error}")
            return False

    @staticmethod
    def _finalizer_sessions_closed(sessions: Sequence[str], rows: Mapping[str, JsonValue]) -> bool:
        for session in sessions:
            row = rows.get(session)
            if not isinstance(row, Mapping) or row.get("closed") is not True:
                return False
        return True

    def _finalizer_start_snapshot(self, issues: list[str]) -> list[JsonValue]:
        try:
            current = start_ledger.StartLedger.load(self.ledger_path)
            self.ledger = current
        except (OSError, ValueError) as error:
            self.ledger = None
            self.finalizer_ledger_error = str(error)
            issues.append(DETAIL_LEDGER.format(detail=str(error)))
            return []
        return [
            {
                "id": attempt.identifier,
                "case": attempt.case,
                "label": attempt.label,
                "kind": attempt.kind,
                "state": attempt.state,
                "operation_id": attempt.operation_id,
                "session_id": attempt.session_id,
            }
            for attempt in current.attempts.values()
        ]

    def _finalizer_roles(self, sessions: set[str], issues: list[str]) -> dict[str, str]:
        roles: dict[str, str] = {}
        for session_id in sorted(sessions):
            try:
                record = self.session_record(session_id, retain=False)
                role = record.get(FIELD_ROLE)
                roles[session_id] = role if isinstance(role, str) else "unknown"
                self.record_session(session_id, roles[session_id])
            except BaseException as error:
                issues.append(f"session read {session_id}: {error}")
                roles[session_id] = "unknown"
        return roles

    def _finalizer_end_sessions(
        self, sessions: Sequence[str], roles: Mapping[str, str], rows: MutableJson, issues: list[str]
    ) -> None:
        for session_id in sorted(sessions):
            try:
                record = self.end_session(session_id)
                rows[session_id] = {
                    "role": roles.get(session_id, "unknown"),
                    "closed": record.get(FIELD_CLOSED_AT) is not None and record.get(FIELD_LIFECYCLE) == "closed",
                }
            except BaseException as error:
                issues.append(f"session {session_id}: {error}")
                rows[session_id] = {"role": roles.get(session_id, "unknown"), "closed": False, "error": str(error)}

    def _finalizer_hold_ready(self, issues: list[str]) -> None:
        try:
            creation.enter_project(self.observer, self.project)
            item = self.item()
            standing = item.get(STANDING)
            if item.get("stage") == "delivered" or not isinstance(standing, Mapping):
                return
            state = item.get("state")
            if not isinstance(state, Mapping) or state.get(STATE_PHASE_FIELD) != READY_PHASE:
                return
            held = self.observer.run((TELEC, "todo", "update", ITEM, "--hold", "--reason", "flow finalizer"))
            if held.exit_status != 0:
                issues.append(f"ready item hold: {held.output[-300:]}")
                return
            held_item = self.item()
            held_state = held_item.get("state")
            if not isinstance(held_state, Mapping) or held_state.get(STATE_HOLD) is not True:
                issues.append("ready item hold returned success without a public hold state")
                return
            admitted = standing.get(STANDING_ADMITTED)
            if admitted is None:
                return
            integration = self.project / WORKTREE_DIRECTORY / INTEGRATION_DIRECTORY
            if not integration.is_dir():
                issues.append("admitted undelivered item retained: integration worktree is absent")
                return
            status = self.git(("status", "--porcelain"), cwd=integration)
            head = self.git(("rev-parse", "HEAD"), cwd=integration)
            base = self.git(("rev-parse", f"{ORIGIN}/{MAIN}"), cwd=self.project)
            staged_candidate = status.splitlines()
            if head != base or staged_candidate != ["A  Makefile", "A  feature.txt"]:
                issues.append("admitted undelivered item retained: integration worktree is not clean and uncommitted")
                return
            outcome = self.observer.run((TELEC, "todo", "integrate", ITEM, "--abandon"))
            receipt = foundation.json_object(outcome.output)
            operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
            if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
                issues.append(f"admitted undelivered attempt retained: {outcome.output[-300:]}")
                return
            terminal = self.operation(operation, FLOW_COMMAND_SECONDS)
            if terminal.get(FIELD_STATE) != STATE_COMPLETED:
                issues.append(f"admitted undelivered abandon did not complete: {terminal!r}")
                return
            post = self.item()
            post_standing = post.get(STANDING)
            if isinstance(post_standing, Mapping) and post_standing.get(STANDING_ADMITTED) is not None:
                issues.append("admitted undelivered abandon completed but admission remains; resources retained")
        except BaseException as error:
            issues.append(f"item hold/read: {error}")

    def _finalizer_restore(self, issues: list[str]) -> None:
        try:
            issues.extend(self.publication.restore())
        except BaseException as error:
            issues.append(f"publication restore: {error}")

    def _finalizer_sweep(self, baseline_ids: frozenset[str], rows: MutableJson, issues: list[str]) -> None:
        for _ in range(3):
            try:
                open_sessions = []
                for session_id in set(self.all_current_project_sessions()) - set(baseline_ids):
                    record = self.session_record(session_id, retain=False)
                    if record.get(FIELD_CLOSED_AT) is None and record.get(FIELD_LIFECYCLE) != "closed":
                        open_sessions.append(session_id)
                if not open_sessions:
                    return
                roles = {session: self.sessions.get(session, "unknown") for session in open_sessions}
                self._finalizer_end_sessions(open_sessions, roles, rows, issues)
            except BaseException as error:
                issues.append(f"session sweep read: {error}")
                return
        issues.append("the public session sweep did not reach an all-closed observation")

    def _finalizer_stop_fixtures(self, issues: list[str]) -> None:
        for setup in self.control_setups:
            try:
                (setup.control / STOP_MARKER).touch(exist_ok=True)
            except OSError as error:
                issues.append(f"fixture stop marker {setup.control}: {type(error).__name__}")

    def _finalizer_failure(self, error: BaseException) -> None:
        self.finalizer_errors.append(str(error))
        self.retain(RETAINED_MARKER.format(path=self.root))
        try:
            self.write_retained_marker({"finalizer_error": str(error)})
        except BaseException:
            pass

    def write_manifest(self, updates: Mapping[str, JsonValue]) -> None:
        """Re-emit the chain handover manifest with additive fields; never use it to discharge a ledger attempt."""
        if self.manifest_path.exists():
            existing = self._read_object(self.manifest_path)
            if existing is None:
                raise creation.binding_failure(DETAIL_MANIFEST)
            current = cast(MutableJson, dict(existing))
        else:
            current = {
                FLOW_ID_FIELD: self.require_ledger().flow_id,
                CHAIN_FIELD: list(self.chain),
                APPROVALS_FIELD: cast(JsonValue, approval_map(self.chain)),
                "ledger_path": str(self.ledger_path),
                "registry_path": str(self.controls.registry_path) if self.controls.registry_path else None,
                "claims_path": str(self.controls.claims_path) if self.controls.claims_path else None,
                "controls_root": str(self.controls.root),
                "fixture_publication_sha": self.fixture_publication_sha,
                "candidate_identity": self.candidate_identity,
                "item": ITEM,
            }
            if self.event_window is not None:
                current["event_window"] = self.event_window.json_value()
            if self.event_case_seal is not None:
                current["event_case_seal"] = self.event_case_seal
        current.update(updates)
        self._atomic_json(self.manifest_path, current)

    def verify_manifest(self) -> Json:
        """Check handover identity and then independently reload the authoritative start ledger."""
        manifest = self._read_object(self.manifest_path)
        if manifest is None:
            raise creation.binding_failure(DETAIL_MANIFEST)
        expected: dict[str, JsonValue] = {
            FLOW_ID_FIELD: self.require_ledger().flow_id,
            CHAIN_FIELD: list(self.chain),
            APPROVALS_FIELD: cast(JsonValue, approval_map(self.chain)),
            "ledger_path": str(self.ledger_path),
            "registry_path": str(self.controls.registry_path) if self.controls.registry_path else None,
            "claims_path": str(self.controls.claims_path) if self.controls.claims_path else None,
            "controls_root": str(self.controls.root),
            "fixture_publication_sha": self.fixture_publication_sha,
            "candidate_identity": self.candidate_identity,
            "item": ITEM,
        }
        if self.event_window is not None:
            expected["event_window"] = self.event_window.json_value()
        if self.event_case_seal is not None:
            expected["event_case_seal"] = self.event_case_seal
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise creation.binding_failure(DETAIL_MANIFEST)
        loaded = start_ledger.StartLedger.load(self.ledger_path)
        if loaded.flow_id != self.require_ledger().flow_id:
            raise creation.binding_failure(DETAIL_LEDGER.format(detail="flow id changed"))
        self.ledger = loaded
        return manifest

    def item(self) -> Json:
        """The public item view with artifact content, bound to this shared disposable item."""
        shown = self.observer.show(ITEM)
        if shown is None:
            raise creation.binding_failure(DETAIL_ITEM)
        return dict(shown)

    def handover(self, case: str, next_case: str, extra: Mapping[str, JsonValue]) -> None:
        """Persist the additive handover evidence for the next approved case; no resource is deleted."""
        if next_case not in self.chain:
            raise creation.binding_failure(DETAIL_DOOR.format(case=next_case))
        starts = self.require_ledger()
        sessions = dict(self.sessions)
        current_item = self.item()
        self.item_snapshot = current_item
        update: MutableJson = {
            "last_completed_case": case,
            "next_case": next_case,
            "next_approval": approval_for(next_case),
            SESSIONS_FIELD: cast(JsonValue, sessions),
            "item_snapshot": cast(JsonValue, current_item),
            "ledger_line_count": len(starts.lines),
            "ledger_open_ids": [attempt.identifier for attempt in starts.open_attempts],
        }
        if self.event_window is not None:
            update["event_window"] = self.event_window.json_value()
        if self.event_case_seal is not None:
            update["event_case_seal"] = self.event_case_seal
        update.update(extra)
        self.write_manifest(update)
        self.write_retained_marker({"last_handover_case": case, "next_case": next_case})

    def register_case(self, case: str, actions: Sequence[start_ledger.ActionSpec]) -> start_ledger.StartLedger:
        """Read the existing ledger at case entry and record that case's complete list before any call or gate."""
        if case == SFC_CHAIN_B5 and self.ledger is not None:
            raise creation.binding_failure(DETAIL_CASE_LEDGER.format(case=case))
        if case != SFC_CHAIN_B5:
            self.verify_manifest()
        current = self.require_ledger()
        try:
            current.declare_case(case, actions)
        except ValueError as error:
            raise creation.binding_failure(DETAIL_LEDGER.format(detail=str(error))) from error
        self.write_retained_marker({"active_case": case})
        return current

    def map_message_actor(
        self, first_line: str, index: int, role: str | None = None, timeout_seconds: float = 0.0
    ) -> str:
        """An alias named for the B7 roleless-message case; still grounded in the recorded atomic claim."""
        return self.message_actor(first_line, index, role, timeout_seconds)

    def all_current_project_sessions(self) -> tuple[str, ...]:
        """Read each retained session record and select sessions belonging to the disposable project."""
        found: list[str] = []
        owned_paths = {
            str(self.project),
            str((self.project / WORKTREE_DIRECTORY / ITEM).resolve()),
            str((self.project / WORKTREE_DIRECTORY / INTEGRATION_DIRECTORY).resolve()),
        }
        for session_id in self.observer.sessions(retain=False).ids:
            record = self._session_record(session_id, retain=False)
            if record is not None and record.get(FIELD_PROJECT_PATH) in owned_paths:
                found.append(session_id)
        return tuple(sorted(found))

    def end_session(self, session_id: str, attempt_id: str | None = None) -> Json:
        """Use the public end and operation surfaces, then require the retained record to show closure."""
        current = self.session_record(session_id)
        if current.get(FIELD_CLOSED_AT) is None and current.get(FIELD_LIFECYCLE) != "closed":
            outcome = self.observer.run((TELEC, SESSIONS, "end", session_id))
            receipt = foundation.json_object(outcome.output)
            operation_id = receipt.get(FIELD_OPERATION) if receipt is not None else None
            if outcome.exit_status != 0 or not isinstance(operation_id, str) or not operation_id:
                raise creation.binding_failure(
                    DETAIL_COMMAND.format(
                        command="sessions end", status=outcome.exit_status, output=outcome.output[-300:]
                    )
                )
            terminal = self.operation(operation_id, START_RECORD_SECONDS)
            if terminal.get(FIELD_STATE) != STATE_COMPLETED:
                raise creation.platform_failure(
                    DETAIL_OPERATION.format(
                        operation=operation_id, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR)
                    )
                )
        deadline = time.monotonic() + FLOW_COMMAND_SECONDS
        record = self.session_record(session_id)
        while time.monotonic() < deadline:
            if record.get(FIELD_CLOSED_AT) is not None and record.get(FIELD_LIFECYCLE) == "closed":
                if attempt_id is not None:
                    self.require_ledger().discharge(attempt_id, "public end completed and retained record closed")
                return record
            time.sleep(RECORD_POLL_SECONDS)
            record = self.session_record(session_id, retain=False)
        raise creation.platform_failure(DETAIL_CLOSED.format(session=session_id, record=record))

    def _record_sessions(self) -> dict[str, str]:
        records: dict[str, str] = {}
        for session_id in self.all_current_project_sessions():
            record = self._session_record(session_id, retain=False)
            if record is not None:
                role = record.get(FIELD_ROLE)
                records[session_id] = role if isinstance(role, str) else ""
        return records

    def _read_json_lines(self, path: Path) -> list[Json]:
        try:
            lines = path.read_text(encoding=ENCODING).splitlines()
        except (OSError, UnicodeError):
            return []
        result: list[Json] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                result.append({str(key): entry for key, entry in value.items()})
        return result
