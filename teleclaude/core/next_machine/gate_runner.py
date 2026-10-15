"""The build gates as a process of their own, so their lifetime does not depend on the process that asked.

``run_build_gates`` supervises ``make test`` with a time limit and kills its process group when the limit passes.
Run inside the daemon, that supervision dies with the daemon, and a wedged ``make`` outlives it. Run here, in a
process started in its own session, the supervisor survives the daemon and still enforces the limit, so the whole
tree ends by itself within a bound the caller can rely on.

Invoked as ``python -m teleclaude.core.next_machine.gate_runner <worktree> <slug>``. It prints ``UNIT <pgid>``
when the gates start (the process group that holds them) and the outcome as JSON when they end.
"""

from __future__ import annotations

import sys

from pydantic import BaseModel, ConfigDict

from teleclaude.core.next_machine.build_gates import run_build_gates

USAGE = "usage: python -m teleclaude.core.next_machine.gate_runner <worktree> <slug>"
EXPECTED_ARGUMENTS = 3
USAGE_EXIT = 2
UNIT_LINE_TEMPLATE = "UNIT {pgid}"


class GateOutcome(BaseModel):
    """What the gates concluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    output: str


def _announce_unit(pgid: int) -> None:
    """Tell the process that started this runner which process group holds the gates, as soon as it exists."""
    print(UNIT_LINE_TEMPLATE.format(pgid=pgid), flush=True)


def main(argv: list[str]) -> int:
    """Run the gates for one worktree and print their outcome."""
    if len(argv) != EXPECTED_ARGUMENTS:
        print(USAGE, file=sys.stderr)
        return USAGE_EXIT
    passed, output = run_build_gates(argv[1], argv[2], on_started=_announce_unit)
    print(GateOutcome(passed=passed, output=output).model_dump_json(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
