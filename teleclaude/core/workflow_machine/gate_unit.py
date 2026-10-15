"""The gate unit: the process group that holds one stamp's build gates, and what is known about it.

The gates run in a runner process of their own (``teleclaude.core.next_machine.gate_runner``), which supervises
``make test`` with a time limit. The owned unit is the process group ``make`` leads, announced by the runner as
soon as it exists and recorded on the stamp's flight, together with the runner itself. Both are observed
positively, by process-group probe and by pid with start time, from spawn through abnormal exit, cleanup and
replacement. A release or a replacement waits for the unit to settle, and settling kills the groups and checks
that they are gone within a bound.

Known limit: a descendant that leaves the group by starting a session of its own is outside the unit.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import psutil

from teleclaude.core.next_machine.gate_runner import UNIT_LINE_TEMPLATE, GateOutcome

GATE_RUNNER_MODULE: Final = "teleclaude.core.next_machine.gate_runner"
GATE_TOKEN_ENV: Final = "TELECLAUDE_STAMP_GATE"
UNIT_PREFIX: Final = UNIT_LINE_TEMPLATE.split("{", 1)[0]
OUTCOME_PREFIX: Final = "{"
NO_START: Final = 0.0
START_TOLERANCE: Final = 0.5
SETTLE_TIMEOUT_SECONDS: Final = 10.0
SETTLE_POLL_SECONDS: Final = 0.1
OUTPUT_TAIL_LINES: Final = 20
RUNNER_FAILED_TEMPLATE: Final = "the gate runner ended without an outcome (exit {code}): {tail}"
UNSETTLED_TEMPLATE: Final = "the gate unit could not be settled; its processes may still run"


@dataclass(frozen=True)
class GateRun:
    """How one gate run ended: its outcome, and whether every process of the unit has ended."""

    outcome: GateOutcome
    settled: bool


def identity_of(pid: int) -> float:
    """The start time of a process, which with its pid names it for as long as it lives."""
    try:
        created: float = psutil.Process(pid).create_time()
    except psutil.Error:
        return NO_START
    return created


def is_process_alive(pid: int, started: float) -> bool:
    """Whether the recorded process still lives: the same pid with the same start time, and not a zombie."""
    if not pid:
        return False
    try:
        process = psutil.Process(pid)
        created: float = process.create_time()
        status: str = process.status()
    except psutil.Error:
        return False
    return abs(created - started) < START_TOLERANCE and status != psutil.STATUS_ZOMBIE


def is_group_alive(pgid: int, leader_started: float) -> bool:
    """Whether any process of the recorded group lives.

    A group id cannot be reused while the group has members, so a leader that is gone with members left is
    still this group; a leader with another start time means the id was reused after the group ended.
    """
    if not pgid:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    try:
        created: float = psutil.Process(pgid).create_time()
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return True
    return abs(created - leader_started) < START_TOLERANCE


def is_token_alive(key: str) -> bool:
    """Whether any process shows the invocation's token in its environment.

    Backs the recorded identities only: a host may hide environments (macOS does for system binaries), so an
    absent token proves nothing.
    """
    for process in psutil.process_iter():
        try:
            if process.environ().get(GATE_TOKEN_ENV) == key and process.status() != psutil.STATUS_ZOMBIE:
                return True
        except psutil.Error:
            continue
    return False


def settle_group(pgid: int, leader_started: float) -> bool:
    """Kill the group and wait, within a bound, until none of it remains; True when it is gone."""
    if not is_group_alive(pgid, leader_started):
        return True
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + SETTLE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not is_group_alive(pgid, leader_started):
            return True
        time.sleep(SETTLE_POLL_SECONDS)
    return not is_group_alive(pgid, leader_started)


def run_in_runner(
    worktree: str,
    item: str,
    key: str,
    on_runner: Callable[[int, float], None],
    on_unit: Callable[[int, float], None],
) -> GateRun:
    """Run the gates in a runner process of their own and wait for it, settling the unit before returning.

    The runner reports its unit as soon as ``make`` runs; when the runner ends without an outcome, whether
    killed or crashed, the unit it left is killed and observed gone before the run is reported as failed.
    """
    runner = subprocess.Popen(
        [sys.executable, "-m", GATE_RUNNER_MODULE, worktree, item],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        # guard: direct-env-read - allowed: child-process environment construction
        env={**os.environ, GATE_TOKEN_ENV: key},
    )
    runner_started = identity_of(runner.pid)
    on_runner(runner.pid, runner_started)
    unit_pgid = 0
    unit_started = NO_START
    outcome: GateOutcome | None = None
    tail: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
    assert runner.stdout is not None  # the pipe was requested above
    for line in runner.stdout:
        if line.startswith(UNIT_PREFIX):
            unit_pgid = int(line.removeprefix(UNIT_PREFIX).strip())
            unit_started = identity_of(unit_pgid)
            on_unit(unit_pgid, unit_started)
        elif line.startswith(OUTCOME_PREFIX):
            outcome = GateOutcome.model_validate_json(line)
        else:
            tail.append(line.rstrip())
    returncode = runner.wait()
    settled = settle_group(runner.pid, runner_started)
    if unit_pgid:
        settled = settle_group(unit_pgid, unit_started) and settled
    if outcome is not None and returncode == 0:
        return GateRun(outcome=outcome, settled=settled)
    failure = GateOutcome(passed=False, output=RUNNER_FAILED_TEMPLATE.format(code=returncode, tail=" | ".join(tail)))
    return GateRun(outcome=failure, settled=settled)
