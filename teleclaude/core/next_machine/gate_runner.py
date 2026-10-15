"""The build gates as a process of their own, so their lifetime does not depend on the process that asked.

``run_build_gates`` supervises ``make test`` with a time limit. Run inside the daemon, that supervision dies with
the daemon, and a wedged ``make`` outlives it. Run here, in a process started in its own session, the supervisor
survives the daemon and still enforces the limit
(``local/projects/teleclaude/design/process-lifecycle``, gate runner ownership).

Invoked as ``python -m teleclaude.core.next_machine.gate_runner <worktree> <slug>``. The runner leads its process
group and starts nothing in it until it is told to: it prints ``READY`` and waits, within a bound, for ``GO`` on
its input. If the wait ends or the input closes first, it exits without having started any workload. After ``GO``
the input closing changes nothing. When the workload ends or reaches its limit, the runner ends every other live
member of its group and only then prints the outcome as JSON; a failed write of the outcome is ignored.
"""

from __future__ import annotations

import os
import select
import sys
from typing import Final

from pydantic import BaseModel, ConfigDict

from teleclaude.core.next_machine.build_gates import run_build_gates
from teleclaude.core.process_group import settle_members

READY_LINE: Final = "READY"
GO_LINE: Final = "GO"
GO_WAIT_SECONDS: Final = 30.0
USAGE: Final = "usage: python -m teleclaude.core.next_machine.gate_runner <worktree> <slug>"
EXPECTED_ARGUMENTS: Final = 3
USAGE_EXIT: Final = 2
NO_GO_EXIT: Final = 3
UNSETTLED_NOTE: Final = "\nthe gate's processes could not all be ended within the bound"


class GateOutcome(BaseModel):
    """What the gates concluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    output: str


def _wait_for_go() -> bool:
    """Whether GO arrived on the input within the bound; the input closing, or the wait ending, is no."""
    readable, _, _ = select.select([sys.stdin], [], [], GO_WAIT_SECONDS)
    return bool(readable) and sys.stdin.readline().strip() == GO_LINE


def _report(outcome: GateOutcome) -> None:
    """Print the outcome; the process that asked may be gone, which is no failure of the gates."""
    try:
        print(outcome.model_dump_json(), flush=True)
    except (BrokenPipeError, OSError):
        pass


def main(argv: list[str]) -> int:
    """Wait for GO, run the gates for one worktree, settle the group, and report."""
    if len(argv) != EXPECTED_ARGUMENTS:
        print(USAGE, file=sys.stderr)
        return USAGE_EXIT
    try:
        print(READY_LINE, flush=True)
    except (BrokenPipeError, OSError):
        return NO_GO_EXIT
    if not _wait_for_go():
        return NO_GO_EXIT
    passed, output = False, ""
    try:
        passed, output = run_build_gates(argv[1], argv[2], own_session=False)
    finally:
        settled, _ = settle_members(os.getpgrp(), exclude=os.getpid())
    if not settled:
        passed, output = False, output + UNSETTLED_NOTE
    _report(GateOutcome(passed=passed, output=output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
