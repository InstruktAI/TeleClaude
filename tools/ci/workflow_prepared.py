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

It proves no event, no stamp, ready or delivery, no builder child, no model following and no intermediate sweep order.
The Git base, main branch and owned bare origin are controller-owned fixture preparation by the real `git`
executable. This controller creates no session record, role, reservation, identity or authentication state, reads no
private store and imports no application module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

from tools.ci import workflow_controls as controls
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_items as items
from tools.ci import workflow_publication as publication
from tools.ci import workflow_waiting as waiting
from tools.ci.workflow_foundation import FoundationHost

TELEC: Final = "bin/telec"
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
BODY_A: Final = "b4 body one"
BODY_B: Final = "b4 body two"
INPUT: Final = creation.INPUT_ARTIFACT
COMPLETE_ENDING: Final = re.compile(r"^Performed prepared on b3-item.*, complete\s*$", re.MULTILINE)
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


class _Prepared:
    """One run of journey B4."""

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
        self.temporary_root = setup.control.parent
        self.source_root = source_root
        self.project = project.resolve()
        self.owner_email = owner_email
        self.baseline: creation.SessionView | None = None
        self.starts: dict[str, str] = {}
        self.setups: list[foundation.FixtureSetup] = []
        self.journeys: dict[str, foundation.Journey] = {}
        self.clone: Path = source_root
        self.initial_headers: list[str] = []
        self.known_claims = 0
        self.known_sessions: list[str] = []

    # -- helpers ---------------------------------------------------------------------------------------------------
    def _known(self, *sessions: str) -> frozenset[str]:
        assert self.baseline is not None
        return self.baseline.ids | frozenset(sessions)

    def _journey(self, name: str, index: int) -> foundation.Journey:
        journey = foundation.Journey(self.host, self.setups[index], self.project, self.owner_email)
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

    def _record(self, session: str) -> Json:
        outcome = self.observer.run((TELEC, "sessions", "show", session, foundation.FULL_FLAG), retain=False)
        record = foundation.json_object(outcome.output) if outcome.exit_status == 0 else None
        if record is None:
            raise creation.binding_failure(f"session {session} is unreadable: {outcome.output[-300:]!r}")
        return record

    def _frame_output(self, journey: foundation.Journey, name: str) -> tuple[int | None, str]:
        frame = journey.await_frame(name, time.monotonic() + FRAME_SECONDS)
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
            time.sleep(POLL_SECONDS)
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
        first = [
            controls.command("claim", prepare),
            controls.command("child", child),
            controls.late("preparedold", ARGV_OLD, GATE_OLD),
            controls.late("preparednew", ARGV_NEW, GATE_NEW),
        ]
        work = [controls.command("claim", ["telec", TODO, "work", ITEM])]
        plans = [controls.PlanFile(commands=commands) for commands in (first, [], work, [])]
        self.setups = self.controls.pool(plans)

    def preconditions(self) -> None:
        shown = self._shown()
        # The earlier journey ended its last driver, which can leave the item held; a driver start clears that brake in
        # its own write, so the starting hold is recorded, not asserted.
        _, hold = creation.dig(shown, "state.hold")
        self.host.note(("starting-hold", repr(hold)), foundation.Outcome(0, repr(hold)), "")
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
        time.sleep(creation.QUIESCENCE_GAP_SECONDS)
        second = self._shown()
        changed = creation.differences(first, second)
        if changed:
            raise creation.binding_failure(creation.DETAIL_NOT_QUIESCENT.format(paths=changed))
        return second

    def require_snapshot(self, expected: Json, when: str) -> None:
        for label, pause in (("immediately", 0.0), ("five seconds later", items.SETTLE_SECONDS)):
            if pause:
                time.sleep(pause)
            changed = creation.differences(expected, self._shown())
            if changed:
                raise creation.platform_failure(DETAIL_CHANGED.format(when=f"{when} {label}", paths=changed))

    # -- steps -----------------------------------------------------------------------------------------------------
    def step1_driver(self) -> tuple[driver.DriverCase, str, str]:
        outcome, starter = driver.start_call(self.starts, self.observer, (TELEC, TODO, "prepare", ITEM), "start")
        if outcome.exit_status != 0 or starter is None:
            raise creation.platform_failure(
                waiting.DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        child_attempt = driver.begin_attempt(self.starts, "session-child")
        author = self._discover(self._known())
        case = self._case("author", 0, driver.DRIVER_ID, "prepare", PREPARATION_PHASE)
        case.check_startup(author, frozenset({author}))
        self._require_pool(1)
        instruction = case.claim_call([starter])
        case.check_instruction(author, instruction)
        case.observe_claim(author, known_entries=self.known_claims)
        self.starts[starter] = publication.START_CLAIMED
        status, text = self._frame_output(self.journeys["author"], waiting.FRAME_CHILD)
        started = waiting.STARTED_CHILD.search(text)
        if status != 0 or started is None or started.group("procedure") != waiting.CHILD_PROCEDURE:
            raise creation.platform_failure(
                waiting.DETAIL_CHILD.format(stdout=text[-300:], procedure=waiting.CHILD_PROCEDURE)
            )
        child = started.group("session")
        driver.release_attempt(self.starts, child_attempt)
        self.known_sessions = [author, child]
        child_journey = self._journey("child", 1)
        self._startup(child, child_journey, 1)
        record = self._record(child)
        for field, expected in ((waiting.FIELD_ROLE, waiting.CHILD_ROLE), (waiting.FIELD_INITIATOR, author)):
            if record.get(field) != expected:
                raise creation.platform_failure(
                    waiting.DETAIL_CHILD_RECORD.format(
                        session=child, field=field, found=record.get(field), expected=expected
                    )
                )
        self._require_pool(2)
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
        )

    def _startup(self, session: str, journey: foundation.Journey, index: int) -> None:
        journey.session_id = session
        launch = journey.await_json(self.setups[index].control / foundation.LAUNCH_FILE, waiting.LAUNCH_SECONDS)
        native = str(launch.get("native_session_id"))
        deadline = time.monotonic() + waiting.START_CAP_SECONDS
        record: Json | None = None
        while time.monotonic() < deadline:
            record = journey.record(retain=False)
            if journey.started(record, native):
                return
            recorded = record.get(foundation.FIELD_NATIVE) if record is not None else None
            if isinstance(recorded, str) and recorded and recorded != native:
                raise creation.binding_failure(
                    waiting.DETAIL_MAPPING.format(actor="child", session=session, recorded=recorded, launched=native)
                )
            time.sleep(POLL_SECONDS)
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
        self._late(0, ARGV_OLD, ["telec", TODO, "act", ITEM, "prepared", "--revision", r0])
        self._gate(0, GATE_OLD)
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
        self._late(0, ARGV_NEW, ["telec", TODO, "act", ITEM, "prepared", "--revision", r1])
        self._gate(0, GATE_NEW)
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
            time.sleep(POLL_SECONDS)
        creation.require_value(ITEM, self._shown(), "state.lifecycle_phase", PREPARED_PHASE)
        return r2

    def step7_restore(self, r1: str) -> None:
        before = self._shown()
        after = self.owner_write(BODY_A)
        if self._input() != BODY_A or digest(self._input()) != r1:
            raise creation.binding_failure(DETAIL_BODY.format(found=digest(self._input()), expected=r1))
        self.require_owner_write(before, after)

    def step8_work(self, author: str, child: str) -> tuple[driver.DriverCase, str]:
        outcome, operation = driver.start_call(self.starts, self.observer, (TELEC, TODO, "work", ITEM), "work")
        if outcome.exit_status != 0 or operation is None:
            raise creation.platform_failure(
                waiting.DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        worker = self._discover(self._known(author, child))
        case = self._case("worker", 2, WORK_DRIVER_ID, "work", WORK_PHASE)
        case.check_startup(worker, frozenset({author, child, worker}))
        self._require_pool(3)
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
            time.sleep(POLL_SECONDS)
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
        case.close(worker)


def run_prepared(
    host: FoundationHost,
    setup: foundation.FixtureSetup,
    project: Path,
    source_root: Path,
    owner_email: str,
    project_slug: str,
    register_company: Callable[[], None],
    retain: Callable[[str], None],
) -> None:
    """Journey B4; raises JourneyFailure leading with its class."""
    prepared = _Prepared(host, setup, project, source_root, owner_email, register_company, retain)
    observer = prepared.observer
    failure: BaseException | None = None
    try:
        creation.require_manual_runner(observer)
        prepared.publication.begin(own_generation=True)
        creation.enter_project(observer, project)
        prepared.baseline = observer.sessions()
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
        author_case, author, child = prepared.step1_driver()
        r0, r1 = prepared.step2_move(author, child)
        prepared.step3_old_refused(author, child, r0, r1)
        prepared.step4_prepared(author, child, r1)
        prepared.step5_end_author(author_case, author)
        prepared.step6_moved_refuses_work(r0, r1)
        prepared.step7_restore(r1)
        worker_case, worker = prepared.step8_work(author, child)
        prepared.step9_close(worker_case, worker)
    except BaseException as error:
        failure = error
        raise
    finally:
        _cleanup(prepared, failure)


def _cleanup(prepared: _Prepared, failure: BaseException | None) -> None:
    """Settle the sessions the journey owns, restore the candidate publication and the sidecar, report every failure."""
    settlement = publication.settle_sessions(
        prepared.observer, prepared.baseline, prepared.starts, prepared.controls.directories
    )
    problems = list(settlement.problems)
    problems.extend(prepared.publication.restore())
    if settlement.proven:
        problems.extend(prepared.controls.restore())
    else:
        kept = DETAIL_CONTROLS_KEPT.format(control=prepared.controls.root)
        problems.append(kept)
        prepared.retain(kept)
    try:
        creation.leave_project(prepared.observer, prepared.source_root)
    except BaseException as error:
        problems.append(f"returning the owner terminal failed: {error}")
    problems.extend(prepared.publication.candidate_unchanged())
    if problems and failure is None:
        raise creation.binding_failure("; ".join(problems))
    if problems:
        prepared.publication.note("cleanup-problems", "; ".join(problems))
