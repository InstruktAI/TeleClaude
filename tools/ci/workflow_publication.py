"""The disposable publication of the four folded driver procedures, and the settlement of what a journey leaves running.

Shared by the native B journeys (B1 to B4), whose assertions rest on a published installation whose drivers and
subscriptions are the four folded procedures: a separately committed, owned clone of the candidate checkout in which the
four live files carry their `*.issue-128.md` companions' bytes and the companions are deleted, published through the
supported installation entry point. The candidate checkout is never edited. Every journey restores the candidate
publication when it ends, so none may assume the fold is still installed: each installs and verifies it for itself,
reusing the verified owned clone (same commit, clean tree) of an earlier journey of the profile instead of folding and
validating again.

The controller imports no application module and reads no private index: every observation is a public command.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from tools.ci import acceptance_work as payload_work
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
CODE: Final = "code"
LINT: Final = "lint"
ALL_FLAG: Final = "--all"
SESSIONS: Final = "sessions"
SHOW: Final = "show"
END: Final = "end"
FULL_FLAG: Final = "--full"
OPERATIONS: Final = "operations"
INSTALL_MODULE: Final = "teleclaude.entrypoints.install_publication"
CLONE_NAME: Final = "b-publication-fixture"
GIT_AUTHOR: Final = "Runtime Acceptance Fixture"
GIT_EMAIL: Final = "runtime-acceptance@example.invalid"
ENVIRONMENT_DIRECTORY: Final = Path(".venv")
DOCS_ROOT: Final = Path("docs") / "global"
COMPANION_SUFFIX: Final = ".issue-128.md"
LIVE_SUFFIX: Final = ".md"
DRIVER_ID: Final = "sdlc/procedure/lifecycle/prepare/overview-v2"
FOLD_IDS: Final = (
    DRIVER_ID,
    "sdlc/procedure/lifecycle/prepare/intake-v2",
    "sdlc/procedure/lifecycle/work/overview-v2",
    "sdlc/procedure/lifecycle/work/build-v2",
)

FIELD_OPERATION: Final = "operation_id"
FIELD_STATE: Final = "state"
FIELD_ERROR: Final = "error"
FIELD_RESULT: Final = "result"
STATE_COMPLETED: Final = "completed"
STATE_FAILED: Final = "failed"
TERMINAL_STATES: Final = frozenset({"completed", "failed", "stale", "cancelled"})
KNOWN_STATES: Final = TERMINAL_STATES | frozenset({"queued", "running"})
CLOSED_STATUS: Final = "closed"
FIELD_CLOSED_AT: Final = "closed_at"
FIELD_LIFECYCLE: Final = "lifecycle_status"

CLI_TIMEOUT_SECONDS: Final = 60
CLONE_TIMEOUT_SECONDS: Final = 60
LINT_TIMEOUT_SECONDS: Final = 180
PUBLISH_TIMEOUT_SECONDS: Final = 120
POLL_SECONDS: Final = 2.0
SETTLE_SECONDS: Final = 120.0
PROCESS_EXIT_SECONDS: Final = 30.0
LOG_TAIL_LINES: Final = 200
LOG_TAIL_BYTES: Final = 1400

DETAIL_COMMAND: Final = "`{command}` exited {status}: {output!r}"
DETAIL_FOLD_PATHS: Final = (
    "the fold changed {found!r}, not exactly the four live files modified and four companions deleted"
)
DETAIL_FOLD_DIRTY: Final = "the fixture clone is not clean after the fold commit: {status!r}"
DETAIL_NO_BODY: Final = "`telec docs get {identity}` printed no snippet body: {output!r}"
DETAIL_BODY_MISMATCH: Final = "the published body of {identity} differs from the {expected}"
DETAIL_OPERATION_READ: Final = (
    "the public read of operation {operation} is unreadable or names an unknown state: {output!r}"
)
DETAIL_OPERATION_TIMEOUT: Final = (
    "operation {operation} did not reach a terminal state within {seconds} seconds: {last!r}"
)
DETAIL_IDENTITY_MOVED: Final = "the candidate checkout changed during the journey: {before!r} became {after!r}"
DETAIL_UNSETTLED_SESSIONS: Final = "sessions beyond the baseline are still open after their end: {owned!r}"
DETAIL_LEDGER_UNREADABLE: Final = (
    "the launch record of {control} is unreadable or does not hold the launch it shows, so its processes are unknown"
)
DETAIL_PROCESS_ALIVE: Final = "the fixture process {pid} of {control} is still alive after its session ended"
DETAIL_UNRESOLVED_START: Final = "accepted starts {operations!r} were never observed consumed by a claim or refused, so they may still create a driver"
DETAIL_SESSION_OPEN: Final = "session {session} could not be closed: {detail}"


PENDING_NOTE_MARKER: Final = "\n# NOTE: This snippet has pending changes."


def _text(output: str) -> str:
    return output.replace("\r\n", "\n")


def docs_body(output: str) -> str | None:
    """The snippet body of a `telec docs get` response: everything after its metadata block, line ends normalized."""
    lines = _text(output).split("\n")
    dividers = [index for index, line in enumerate(lines) if line.strip() == "---"]
    if len(dividers) < 2:
        return None
    body = "\n".join(lines[dividers[1] + 1 :])
    return body.split(PENDING_NOTE_MARKER)[0].strip()


def operation_state(observer: creation.Observer, operation: str, *, retain: bool = False) -> Mapping[str, object]:
    """One public read of an operation; an unreadable read or a state outside the known set fails the case."""
    outcome = observer.run((TELEC, OPERATIONS, GET, operation), retain=retain)
    state = foundation.json_object(outcome.output)
    value = state.get(FIELD_STATE) if state is not None else None
    if outcome.exit_status != 0 or state is None or value not in KNOWN_STATES:
        raise creation.binding_failure(DETAIL_OPERATION_READ.format(operation=operation, output=outcome.output[-300:]))
    return state


def await_terminal(observer: creation.Observer, operation: str, seconds: float) -> Mapping[str, object]:
    """Poll one operation to a terminal state; unreadable reads fail, an operation still open at the end fails."""
    deadline = time.monotonic() + seconds
    last: Mapping[str, object] = {}
    while time.monotonic() < deadline:
        last = operation_state(observer, operation)
        if last.get(FIELD_STATE) in TERMINAL_STATES:
            return operation_state(observer, operation, retain=True)
        payload_work.sleep(POLL_SECONDS)
    raise creation.platform_failure(
        DETAIL_OPERATION_TIMEOUT.format(operation=operation, seconds=int(seconds), last=last)
    )


def _session_closed(record: Mapping[str, object] | None) -> bool:
    return (
        record is not None and record.get(FIELD_CLOSED_AT) is not None and record.get(FIELD_LIFECYCLE) == CLOSED_STATUS
    )


def _session_record(
    observer: creation.Observer, session_id: str, evidence: list[creation.EvidenceValue] | None = None
) -> Mapping[str, object] | None:
    outcome = observer.run((TELEC, SESSIONS, SHOW, session_id, FULL_FLAG), retain=False)
    if evidence is not None:
        evidence.append(creation.command_evidence((TELEC, SESSIONS, SHOW, session_id, FULL_FLAG), outcome))
    return foundation.json_object(outcome.output) if outcome.exit_status == 0 else None


@dataclass(frozen=True)
class Settlement:
    """What the settlement of a journey\'s actors found: the failures, and whether closure was proven."""

    problems: list[str]
    proven: bool


START_OPEN: Final = "open"
START_CLAIMED: Final = "claimed"
START_REFUSED: Final = "refused"


def _close_owned(
    observer: creation.Observer,
    owned: Sequence[str],
    problems: list[str],
    evidence: list[creation.EvidenceValue] | None = None,
) -> None:
    """End each owned open session through the public command and prove its retained record closed."""
    for session_id in owned:
        reads: list[creation.EvidenceValue] | None = [] if evidence is not None else None
        packet: creation.EvidenceObject | None = None
        if evidence is not None:
            packet = {"session_id": session_id, "command": None, "terminal": None, "reads": reads, "error": None}
            evidence.append(packet)
        try:
            ended = observer.run((TELEC, SESSIONS, END, session_id))
            if packet is not None:
                packet["command"] = creation.command_evidence((TELEC, SESSIONS, END, session_id), ended)
            receipt = foundation.json_object(ended.output)
            operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
            if ended.exit_status != 0 or not isinstance(operation, str) or not operation:
                problems.append(DETAIL_SESSION_OPEN.format(session=session_id, detail=ended.output[-200:]))
                continue
            outcome = await_terminal(observer, operation, SETTLE_SECONDS)
            if packet is not None:
                packet["terminal"] = cast(creation.EvidenceValue, dict(outcome))
            if outcome.get(FIELD_STATE) != STATE_COMPLETED or not _session_closed(
                _session_record(observer, session_id, reads)
            ):
                problems.append(DETAIL_SESSION_OPEN.format(session=session_id, detail=str(outcome.get(FIELD_ERROR))))
        except BaseException as error:
            if packet is not None:
                packet["error"] = f"{type(error).__name__}: {error}"
            problems.append(DETAIL_SESSION_OPEN.format(session=session_id, detail=str(error)))


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _launch_pids(control: Path, problems: list[str], evidence: list[creation.EvidenceValue] | None = None) -> list[int]:
    """Every fixture process the directory\'s launches recorded, from the append-only record of each launch.

    A directory that holds no launch has no fixture process, which is legitimate. A directory that shows a launch
    (`launch.json`) whose append-only record is unreadable, malformed, or lacks that launch\'s own process is a launch
    whose processes are unknown, which is never read as none.
    """
    shown = control / "launch.json"
    exists = shown.exists()
    packet: creation.EvidenceObject | None = None
    if evidence is not None:
        packet = {
            "control": str(control),
            "shown_exists": exists,
            "launches_data": None,
            "shown_data": None,
            "read_error": None,
        }
        evidence.append(packet)
    if not exists:
        return []
    try:
        data = (control / "launches.jsonl").read_bytes()
        if packet is not None:
            packet["launches_data"] = base64.b64encode(data).decode("ascii")
        lines = data.decode("utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        pids = [record["pid"] for record in records if isinstance(record, dict) and isinstance(record.get("pid"), int)]
        data = shown.read_bytes()
        if packet is not None:
            packet["shown_data"] = base64.b64encode(data).decode("ascii")
        current = json.loads(data.decode("utf-8")).get("pid")
    except (OSError, ValueError, KeyError, AttributeError) as error:
        if packet is not None:
            packet["read_error"] = f"{type(error).__name__}: {error}"
        problems.append(DETAIL_LEDGER_UNREADABLE.format(control=control))
        return []
    if len(pids) != len(records) or not isinstance(current, int) or current not in pids:
        problems.append(DETAIL_LEDGER_UNREADABLE.format(control=control))
    return pids


def _fixture_processes_gone(
    controls: Sequence[Path], problems: list[str], evidence: list[creation.EvidenceValue] | None = None
) -> None:
    """The owned fixture processes of every launch have exited, after the controller asked each directory to stop."""
    for control in controls:
        with suppress(OSError):
            (control / "stop").write_text("stop\n", encoding="utf-8")
        for pid in _launch_pids(control, problems, evidence):
            deadline = time.monotonic() + PROCESS_EXIT_SECONDS
            while _process_alive(pid) and time.monotonic() < deadline:
                payload_work.sleep(POLL_SECONDS)
            if _process_alive(pid):
                problems.append(DETAIL_PROCESS_ALIVE.format(pid=pid, control=control))


def settle_sessions(
    observer: creation.Observer,
    baseline: creation.SessionView | None,
    starts: Mapping[str, str],
    controls: Sequence[Path] = (),
    *,
    evidence: creation.EvidenceObject | None = None,
) -> Settlement:
    """End what the journey owns and prove closure from the evidence that can prove it, never from waiting.

    Public lifecycle evidence: every session beyond the baseline that is not closed is ended and its retained record
    shown closed. Process evidence: the fixture process each owned launch recorded has exited. Causal evidence: a start
    the platform accepted is settled only by what consumed it: an observed claim by the session it started, or a refusal
    that created nothing. A start with neither may still create its driver (a minute-tick scan or a ready trigger can
    spawn after any final listing), so it keeps the settlement unproven however long nothing appears, and the caller
    keeps the resources needed to settle or diagnose it.
    """
    lists: list[creation.EvidenceValue] | None = [] if evidence is not None else None
    closures: list[creation.EvidenceValue] | None = [] if evidence is not None else None
    launches: list[creation.EvidenceValue] | None = [] if evidence is not None else None
    problems: list[str] = []
    if evidence is not None:
        evidence.update(
            {
                "baseline_ids": list(sorted(baseline.ids)) if baseline is not None else None,
                "starts": dict(starts),
                "lists": lists,
                "closures": closures,
                "launches": launches,
                "read_error": None,
                "problems": cast(list[creation.EvidenceValue], problems),
                "legacy_proven": None,
            }
        )
    if baseline is None:
        if evidence is not None:
            evidence["legacy_proven"] = True
        return Settlement([], True)
    try:
        view = observer.sessions(retain=False, evidence=lists)
        _close_owned(observer, sorted(view.ids - baseline.ids - view.closed), problems, closures)
        after = observer.sessions(retain=False, evidence=lists)
        still_open = sorted(after.ids - baseline.ids - after.closed)
    except BaseException as error:  # settlement reports the read failure beside the journey's own
        if evidence is not None:
            evidence["read_error"] = f"{type(error).__name__}: {error}"
            evidence["problems"] = [f"reading the actors to settle failed: {error}"]
            evidence["legacy_proven"] = False
        return Settlement([f"reading the actors to settle failed: {error}"], False)
    if still_open:
        problems.append(DETAIL_UNSETTLED_SESSIONS.format(owned=still_open))
    _fixture_processes_gone(controls, problems, launches)
    unresolved = sorted(operation for operation, state in starts.items() if state == START_OPEN)
    if unresolved:
        problems.append(DETAIL_UNRESOLVED_START.format(operations=unresolved))
    if evidence is not None:
        evidence["legacy_proven"] = not problems
    return Settlement(problems, not problems)


class Publication:
    """The owned fold of the four drivers, its publication, and the restoration of the candidate publication."""

    _verified: dict[str, str] = {}

    def __init__(
        self,
        host: FoundationHost,
        observer: creation.Observer,
        temporary_root: Path,
        source_root: Path,
        register_company: Callable[[], None],
    ) -> None:
        self.host = host
        self.observer = observer
        self.temporary_root = temporary_root
        self.source_root = source_root
        self.register_company = register_company
        self.clone = temporary_root / CLONE_NAME
        self.attempted = False
        self.live_bodies: dict[str, str] = {}
        self.pending_bodies: dict[str, str] = {}
        self.candidate = ""
        self.copies = 0

    def _run(self, argv: Sequence[str], cwd: Path, timeout: float, *, what: str) -> Outcome:
        outcome = self.host.process(argv, cwd, self.host.environment, timeout)
        if outcome.exit_status != 0:
            raise creation.binding_failure(
                DETAIL_COMMAND.format(command=what, status=outcome.exit_status, output=outcome.output[-400:])
            )
        return outcome

    def identity(self) -> str:
        head = self._run((GIT, "rev-parse", "HEAD"), self.source_root, CLONE_TIMEOUT_SECONDS, what="git rev-parse HEAD")
        tree = self._run(
            (GIT, "rev-parse", "HEAD^{tree}"), self.source_root, CLONE_TIMEOUT_SECONDS, what="git rev-parse tree"
        )
        return f"commit {head.output.strip()} tree {tree.output.strip()}"

    def note(self, label: str, text: str) -> None:
        """Retain a fact of the journey; the text rides in the argv, which the report keeps when output is stripped."""
        self.host.note((label, text), Outcome(0, text), "")

    def body_of(self, identity: str, *, pending: bool) -> str:
        """The body a public `telec docs get` prints for the identity, read from the candidate checkout."""
        self.observer.run(("cd", str(self.source_root)))
        argv = [TELEC, DOCS, GET, identity]
        if pending:
            argv.extend((TARGET_OPTION, PENDING_TARGET))
        outcome = self.observer.run(argv, retain=False)
        body = docs_body(outcome.output) if outcome.exit_status == 0 else None
        if not body:
            raise creation.binding_failure(DETAIL_NO_BODY.format(identity=identity, output=outcome.output[-300:]))
        return body

    def _file_body(self, identity: str) -> str:
        """The body of a candidate live file: everything after its header block, line ends normalized."""
        text = (self.source_root / DOCS_ROOT / f"{identity}{LIVE_SUFFIX}").read_text(encoding="utf-8")
        parts = text.split("---", 2)
        return _text(parts[2]).strip() if len(parts) == 3 else ""

    def classify_generation(self) -> tuple[str, str]:
        """The installed generation from public reads alone, and the evidence for it.

        Fixture generation: all four current bodies equal the pending ones. Candidate generation: all four differ from
        the pending bodies and equal the candidate checkout's live files. Anything else is inconsistent.
        """
        pending = {identity: self.body_of(identity, pending=True) for identity in FOLD_IDS}
        current = {identity: self.body_of(identity, pending=False) for identity in FOLD_IDS}
        files = {identity: self._file_body(identity) for identity in FOLD_IDS}
        if all(current[identity] == pending[identity] for identity in FOLD_IDS):
            return GENERATION_FIXTURE, "all four current bodies equal the pending bodies"
        if all(
            current[identity] != pending[identity] and current[identity] == files[identity] for identity in FOLD_IDS
        ):
            return (
                GENERATION_CANDIDATE,
                "all four current bodies equal the candidate live files and differ from pending",
            )
        detail = {
            identity: {
                "equals_pending": current[identity] == pending[identity],
                "equals_candidate_file": current[identity] == files[identity],
                "first_difference": _first_difference(current[identity], files[identity]),
            }
            for identity in FOLD_IDS
        }
        return GENERATION_INCONSISTENT, repr(detail)

    def release_candidate_files(self) -> None:
        """Take the candidate\'s live bodies from its checkout, so a restoration can be verified from the start."""
        self.live_bodies = {identity: self._file_body(identity) for identity in FOLD_IDS}

    def ensure_candidate(self) -> str:
        """Own the starting generation: reuse nothing, restore the candidate first when the fold is installed.

        A `prepare` is never issued before this has verified the candidate generation by public reads. A fixture
        generation is restored (the candidate checkout published through the supported entry point) and verified; an
        inconsistent one stops the case as a binding failure.
        """
        state, evidence = self.classify_generation()
        path = f"generation {state}: {evidence}"
        if state == GENERATION_FIXTURE:
            self.attempted = True  # the attempt is owned before the bounded command that may exchange the generation
            self._publish(self._fresh_copy(self.source_root, "ensure"))
            state, evidence = self.classify_generation()
            path += f"; restored the candidate, then generation {state}: {evidence}"
        self.note("generation-path", path)
        if state != GENERATION_CANDIDATE:
            raise creation.binding_failure(DETAIL_GENERATION.format(path=path))
        return path

    def begin(self, *, own_generation: bool = False) -> None:
        """B-P1: record the candidate, register the synthetic company its project declares, capture its live bodies."""
        self.candidate = self.identity()
        self.note("candidate-identity", self.candidate)
        self.register_company()
        if own_generation:
            self.release_candidate_files()
            self.ensure_candidate()
        self.live_bodies = {identity: self.body_of(identity, pending=False) for identity in FOLD_IDS}

    def _fold_sha(self) -> str:
        return self._run(
            (GIT, "rev-parse", "HEAD"), self.clone, CLONE_TIMEOUT_SECONDS, what="git rev-parse HEAD"
        ).output.strip()

    def _reusable(self) -> bool:
        """Whether an earlier journey of the profile left a verified owned clone: same commit, clean tree."""
        recorded = self._verified.get(self.candidate)
        if not recorded or not (self.clone / ".git").exists():
            return False
        try:
            clean = not self._run(
                (GIT, "status", "--porcelain"), self.clone, CLONE_TIMEOUT_SECONDS, what="git status"
            ).output.strip()
            return clean and self._fold_sha() == recorded
        except creation.JourneyFailure:
            return False

    def prepare(self) -> Path:
        """B-P2 and B-P3: the fold in a separately committed clone, validated by the public documentation lint."""
        if not self._reusable():
            self._clone()
            self._fold()
            self._run(
                (str(self.source_root / TELEC), CODE, LINT, ALL_FLAG),
                self.clone,
                LINT_TIMEOUT_SECONDS,
                what="telec code lint --all",
            )
            self._verified[self.candidate] = self._fold_sha()
        self.note("fixture-publication-sha", self._fold_sha())
        self.pending_bodies = {identity: self.body_of(identity, pending=True) for identity in FOLD_IDS}
        return self.clone

    def _clone(self) -> None:
        shutil.rmtree(self.clone, ignore_errors=True)
        self._run(
            (GIT, "clone", "--quiet", "--shared", str(self.source_root), str(self.clone)),
            self.temporary_root,
            CLONE_TIMEOUT_SECONDS,
            what="git clone --shared",
        )
        environment = self.source_root / ENVIRONMENT_DIRECTORY
        if not (environment / "bin" / "python").is_file():
            raise creation.binding_failure("the dependency environment of the source checkout is missing")
        (self.clone / ENVIRONMENT_DIRECTORY).symlink_to(environment, target_is_directory=True)
        for key, value in (("user.name", GIT_AUTHOR), ("user.email", GIT_EMAIL)):
            self._run((GIT, "config", key, value), self.clone, CLONE_TIMEOUT_SECONDS, what=f"git config {key}")

    def _fold(self) -> None:
        clone = self.clone
        for identity in FOLD_IDS:
            live = clone / DOCS_ROOT / f"{identity}{LIVE_SUFFIX}"
            companion = clone / DOCS_ROOT / f"{identity}{COMPANION_SUFFIX}"
            live.write_bytes(companion.read_bytes())
            self._run(
                (GIT, "rm", "--quiet", str(companion.relative_to(clone))), clone, CLONE_TIMEOUT_SECONDS, what="git rm"
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

    def _fresh_copy(self, origin: Path, purpose: str) -> Path:
        """A new repository of the origin\'s committed tree: publication is owed once per repository, never twice.

        The supported publication records the commit it published per repository, and publishes nothing when that
        commit is recorded already. A copy that has never published is owed again, whatever the deployed generation
        currently holds, which is what installing and restoring the fold require.
        """
        self.copies += 1
        copy = self.temporary_root / f"{CLONE_NAME}-{purpose}-{self.copies}"
        shutil.rmtree(copy, ignore_errors=True)
        self._run(
            (GIT, "clone", "--quiet", "--shared", str(origin), str(copy)),
            self.temporary_root,
            CLONE_TIMEOUT_SECONDS,
            what="git clone --shared",
        )
        (copy / ENVIRONMENT_DIRECTORY).symlink_to(self.source_root / ENVIRONMENT_DIRECTORY, target_is_directory=True)
        return copy

    def _publish(self, checkout: Path) -> None:
        self._run(
            (UV, "run", "--project", str(self.source_root), "--no-sync", "python", "-m", INSTALL_MODULE),
            checkout,
            PUBLISH_TIMEOUT_SECONDS,
            what="install_publication",
        )

    def publish(self) -> None:
        """B-P6: publish the fold. The attempt is recorded first: a bounded command that fails may have exchanged it."""
        self.attempted = True
        self._publish(self._fresh_copy(self.clone, "fold"))

    def verify_parity(self) -> None:
        """B-P7: every published body equals the pending body captured before publication."""
        for identity in FOLD_IDS:
            if self.body_of(identity, pending=False) != self.pending_bodies[identity]:
                raise creation.binding_failure(
                    DETAIL_BODY_MISMATCH.format(identity=identity, expected="pending body captured before publication")
                )

    def restore(self) -> list[str]:
        """B-P8: republish the candidate and verify its live bodies, whatever the fold attempt's outcome was."""
        if not self.attempted:
            return []
        problems: list[str] = []
        try:
            self._publish(self._fresh_copy(self.source_root, "restore"))
            for identity, body in self.live_bodies.items():
                if self.body_of(identity, pending=False) != body:
                    problems.append(DETAIL_BODY_MISMATCH.format(identity=identity, expected="candidate's live body"))
            if not problems:
                self.attempted = False
        except BaseException as error:  # the restore reports, never hides, the journey's own failure
            problems.append(f"restoring the candidate publication failed: {error}")
        return problems

    def candidate_unchanged(self) -> list[str]:
        """The candidate checkout is the one the journey began with."""
        try:
            after = self.identity()
        except BaseException as error:
            return [f"re-reading the candidate identity failed: {error}"]
        return [] if after == self.candidate else [DETAIL_IDENTITY_MOVED.format(before=self.candidate, after=after)]


def _first_difference(left: str, right: str) -> str:
    """Where two texts first differ, with a window of each, for a failure message only."""
    index = next((i for i, (a, b) in enumerate(zip(left, right, strict=False)) if a != b), min(len(left), len(right)))
    return f"at {index} of {len(left)}/{len(right)}: {left[max(0, index - 40) : index + 80]!r} vs {right[max(0, index - 40) : index + 80]!r}"


def log_evidence(host: FoundationHost, terms: Sequence[str]) -> str:
    """The daemon\'s recent log text for a failed case, bounded, for the failure message itself; never an oracle.

    Successful commands lose their output at the harness\'s evidence boundaries, so the text is returned to be written
    into the failure that explains it. The matching lines for the terms come from the supported log reader; the newest
    lines of the installation\'s log files follow, for the case that the terms match nothing.
    """
    home = host.environment.get("HOME", "")
    tool = Path(home) / ".local" / "bin" / "instrukt-ai-logs"
    executable = str(tool) if tool.exists() else "instrukt-ai-logs"
    commands = (
        (executable, "teleclaude", "--since", "60m", "--grep", "|".join(terms)),
        (
            "sh",
            "-c",
            f'tail -n {LOG_TAIL_LINES} "$HOME"/.local/state/instrukt-ai/teleclaude/*.log 2>&1 | tail -c {LOG_TAIL_BYTES}',
        ),
    )
    texts: list[str] = []
    for argv in commands:
        try:
            outcome = host.process(argv, Path(home or "."), host.environment, 60)
        except BaseException as error:  # evidence gathering must not replace the failure it explains
            texts.append(f"[{argv[0]} failed: {type(error).__name__}]")
            continue
        texts.append(f"[{argv[0]} exit {outcome.exit_status}] {outcome.output.strip()[-LOG_TAIL_BYTES:]}")
    return " || ".join(texts)


GENERATION_CANDIDATE: Final = "candidate"
GENERATION_FIXTURE: Final = "fixture"
GENERATION_INCONSISTENT: Final = "inconsistent"
DETAIL_GENERATION: Final = (
    "the installed publication is not a verified candidate generation, so no prepare was issued: {path}"
)
EXCEPTION_TEXT: Final = re.compile(r"[A-Za-z_][\w.]*(?:Error|Exception)\b:?[^\\\n]{0,200}")
EXCEPTION_LINES: Final = 6
EXCEPTION_LINE_BYTES: Final = 260


def exception_evidence(host: FoundationHost) -> str:
    """The last exception lines of the daemon\'s recent log: what a traceback ends with, which a bounded tail cuts off."""
    home = host.environment.get("HOME", "")
    tool = Path(home) / ".local" / "bin" / "instrukt-ai-logs"
    executable = str(tool) if tool.exists() else "instrukt-ai-logs"
    try:
        outcome = host.process((executable, "teleclaude", "--since", "15m"), Path(home or "."), host.environment, 60)
    except BaseException as error:  # evidence gathering must not replace the failure it explains
        return f"[{executable} failed: {type(error).__name__}]"
    found = [match.group(0).strip() for match in EXCEPTION_TEXT.finditer(outcome.output)]
    return " || ".join(text[-EXCEPTION_LINE_BYTES:] for text in found[-EXCEPTION_LINES:]) or "[no exception text found]"


NO_DRIVER_PHRASE: Final = "no published procedure drives preparation"
NOT_ACTIVATED_PHRASE: Final = "is not activated yet"
ACTIVATION_WAIT_SECONDS: Final = 180.0
ACTIVATION_POLL_SECONDS: Final = 20.0
NEGATIVE_OPERATION_SECONDS: Final = 60.0
PREPARE: Final = "prepare"
TODO: Final = "todo"
DETAIL_ACTIVATION: Final = (
    "the store was not activated and the drivers still unpublished within {seconds} seconds: {last!r}"
)
DETAIL_NEGATIVE_STATE: Final = (
    "the pre-publication prepare ended {state!r} with {error!r}, not the driver-lookup refusal"
)
DETAIL_NEGATIVE_WRITE: Final = "the pre-publication prepare changed the item or the sessions: {detail}"
DETAIL_RECEIPT: Final = "`telec todo prepare` printed no operation receipt: exit {status}, {output!r}"


ATTEMPT_PREFIX: Final = "attempt:"


def receipt_operation(output: str) -> str | None:
    """The operation id a receipt-backed verb printed, or None."""
    receipt = foundation.json_object(output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    return operation if isinstance(operation, str) and operation else None


def begin_attempt(starts: MutableMapping[str, str], label: str) -> str:
    """Own an attempted start before the call or the gate that may cause it is crossed.

    A timeout, a lost exit frame or a malformed answer proves nothing about acceptance, so the attempt stays open (and
    closure stays unproven) until a receipt names the operation it became.
    """
    key = f"{ATTEMPT_PREFIX}{label}:{len(starts)}"
    starts[key] = START_OPEN
    return key


def settle_attempt(starts: MutableMapping[str, str], key: str, operation: str | None) -> None:
    """A parsed operation id replaces its attempt, whatever the exit status or frame completeness said."""
    if operation is None:
        return
    starts.pop(key, None)
    starts.setdefault(operation, START_OPEN)


def release_attempt(starts: MutableMapping[str, str], key: str) -> None:
    """An attempt whose outcome public evidence has settled (consumed, refused or established) is no longer open."""
    starts.pop(key, None)


def start_call(
    starts: MutableMapping[str, str], observer: creation.Observer, argv: Sequence[str], label: str
) -> tuple[Outcome, str | None]:
    """One public start verb on the owner terminal, owned before it runs; the operation is parsed whatever its status."""
    key = begin_attempt(starts, label)
    outcome = observer.run(argv)
    operation = receipt_operation(outcome.output)
    settle_attempt(starts, key, operation)
    return outcome, operation


def negative_control(
    observer: creation.Observer,
    item: str,
    baseline: creation.SessionView,
    before: Mapping[str, object],
    starts: MutableMapping[str, str],
) -> None:
    """B-P5: the unpublished installation is refused at the driver lookup, writing nothing; the store is activated.

    The call is repeated (at most once per 20 seconds, for 180 seconds) while the store is not yet activated, and ends
    at the first refusal for the missing driver. Any other terminal state fails the preflight, and neither the item nor
    the sessions may differ from before the control afterwards.
    """
    deadline = time.monotonic() + ACTIVATION_WAIT_SECONDS
    last = ""
    while True:
        key = begin_attempt(starts, "negative-control")
        outcome = observer.run((TELEC, TODO, PREPARE, item))
        operation = receipt_operation(outcome.output)
        settle_attempt(starts, key, operation)
        if outcome.exit_status == 0 and operation is not None:
            state = await_terminal(observer, operation, NEGATIVE_OPERATION_SECONDS)
            error = state.get(FIELD_ERROR)
            failed = state.get(FIELD_STATE) == STATE_FAILED and isinstance(error, str)
            # Only an established pre-launch refusal discharges the attempt; any other failure may have reserved.
            if failed and (NO_DRIVER_PHRASE in str(error) or NOT_ACTIVATED_PHRASE in str(error)):
                starts[operation] = START_REFUSED
            if failed and NO_DRIVER_PHRASE in str(error):
                break
            if not (failed and NOT_ACTIVATED_PHRASE in str(error)):
                raise creation.binding_failure(DETAIL_NEGATIVE_STATE.format(state=state.get(FIELD_STATE), error=error))
            last = str(error)
        elif NOT_ACTIVATED_PHRASE in outcome.output:
            release_attempt(starts, key)  # refused by the CLI before anything was requested
            last = outcome.output[-200:]
        else:
            raise creation.binding_failure(
                DETAIL_RECEIPT.format(status=outcome.exit_status, output=outcome.output[-300:])
            )
        if time.monotonic() >= deadline:
            raise creation.binding_failure(DETAIL_ACTIVATION.format(seconds=int(ACTIVATION_WAIT_SECONDS), last=last))
        payload_work.sleep(ACTIVATION_POLL_SECONDS)
    after = observer.show(item)
    changed = creation.differences(before, after if after is not None else {})
    sessions = observer.sessions()
    if changed or sessions.ids != baseline.ids:
        raise creation.binding_failure(DETAIL_NEGATIVE_WRITE.format(detail=changed or sorted(sessions.ids)))
