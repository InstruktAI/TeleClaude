"""The daemon's side of the gate runner: starting it, handing it GO, and reading how it ended.

The protocol is ``local/projects/teleclaude/design/process-lifecycle`` (gate runner ownership). Spawning, the wait
for READY, the hand-off of GO and the wait for the outcome are blocking and run on worker threads. Nothing here
records or classifies a unit: the registry row and the classifier do that, and this module never signals a process
it has not itself spawned and still holds.
"""

from __future__ import annotations

import select
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine.gate_runner import GO_LINE, READY_LINE, GateOutcome
from teleclaude.core.process_group import live_members
from teleclaude.core.process_identity import NO_IDENTITY, start_identity

logger = get_logger(__name__)

GATE_RUNNER_MODULE: Final = "teleclaude.core.next_machine.gate_runner"
READY_WAIT_SECONDS: Final = 30.0
REAP_WAIT_SECONDS: Final = 10.0
OUTCOME_PREFIX: Final = "{"
OUTPUT_TAIL_LINES: Final = 20
NOT_READY_TEMPLATE: Final = "the gate runner did not report ready: {reason}"
RUNNER_FAILED_TEMPLATE: Final = "the gate runner ended without an outcome (exit {code}): {tail}"
GO_FAILED_TEMPLATE: Final = "the gate runner could not be told to go: {reason}"
REAP_FAILED_LOG: Final = "a gate runner bootstrap could not be reaped"


class RunnerNotReady(Exception):
    """The runner could not be started or told to go; no workload was started."""


@dataclass(frozen=True)
class RunnerHandle:
    """A spawned runner: the process this daemon holds, and the start identity read when it was spawned."""

    process: subprocess.Popen[str]
    pid: int
    identity: str


@dataclass(frozen=True)
class RunnerResult:
    """How the runner ended: its outcome if it reported one, its exit status, and the last of its output."""

    outcome: GateOutcome
    ended: bool


def end_bootstrap(handle: RunnerHandle) -> None:
    """End a runner that has started no workload, by the handle held from its spawn, and reap it."""
    for stream in (handle.process.stdin, handle.process.stdout):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    handle.process.kill()
    try:
        handle.process.wait(timeout=REAP_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning(REAP_FAILED_LOG, pid=handle.pid)


def start_runner(worktree: str, item: str) -> RunnerHandle:
    """Spawn the runner in a session of its own and wait, within a bound, for it to report ready.

    On any failure the bootstrap is ended and reaped before the failure is raised: nothing was started.
    """
    process = subprocess.Popen(
        [sys.executable, "-m", GATE_RUNNER_MODULE, worktree, item],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    handle = RunnerHandle(process=process, pid=process.pid, identity=start_identity(process.pid))
    try:
        if not handle.identity:
            raise RunnerNotReady(NOT_READY_TEMPLATE.format(reason="its identity could not be read"))
        assert process.stdout is not None  # the pipe was requested above
        readable, _, _ = select.select([process.stdout], [], [], READY_WAIT_SECONDS)
        line = process.stdout.readline().strip() if readable else NO_IDENTITY
        if line != READY_LINE:
            raise RunnerNotReady(NOT_READY_TEMPLATE.format(reason=line or "the wait ended"))
    except BaseException:
        end_bootstrap(handle)
        raise
    return handle


def send_go(handle: RunnerHandle) -> None:
    """Tell the runner to start the workload; its identity is durable by now."""
    stdin = handle.process.stdin
    assert stdin is not None  # the pipe was requested at spawn
    try:
        stdin.write(GO_LINE + "\n")
        stdin.flush()
    except (BrokenPipeError, OSError) as failure:
        raise RunnerNotReady(GO_FAILED_TEMPLATE.format(reason=str(failure))) from failure


def await_outcome(handle: RunnerHandle) -> RunnerResult:
    """Read the runner to its end and report how it ended; whether its group is empty is the caller's to observe."""
    outcome: GateOutcome | None = None
    tail: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
    stdout = handle.process.stdout
    assert stdout is not None  # the pipe was requested at spawn
    for line in stdout:
        if line.startswith(OUTCOME_PREFIX):
            outcome = GateOutcome.model_validate_json(line)
        else:
            tail.append(line.rstrip())
    returncode = handle.process.wait()
    if handle.process.stdin is not None:
        try:
            handle.process.stdin.close()
        except OSError:
            pass
    if outcome is not None and returncode == 0:
        return RunnerResult(outcome=outcome, ended=not live_members(handle.pid))
    failure = GateOutcome(passed=False, output=RUNNER_FAILED_TEMPLATE.format(code=returncode, tail=" | ".join(tail)))
    return RunnerResult(outcome=failure, ended=not live_members(handle.pid))
