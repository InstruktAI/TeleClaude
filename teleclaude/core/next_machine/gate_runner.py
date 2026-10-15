"""The build gates as a process of their own, so their lifetime does not depend on the process that asked.

``run_build_gates`` supervises ``make test`` with a time limit and kills its process group when the limit passes.
Run inside the daemon, that supervision dies with the daemon, and a wedged ``make`` outlives it. Run here, in a
process started in its own session, the supervisor survives the daemon and still enforces the limit, so the whole
tree ends by itself within a bound the caller can rely on.

Invoked as ``python -m teleclaude.core.next_machine.gate_runner <worktree> <slug>``; it prints the outcome as JSON.
"""

from __future__ import annotations

import sys

from pydantic import BaseModel, ConfigDict

from teleclaude.core.next_machine.build_gates import run_build_gates

USAGE = "usage: python -m teleclaude.core.next_machine.gate_runner <worktree> <slug>"
EXPECTED_ARGUMENTS = 3
USAGE_EXIT = 2


class GateOutcome(BaseModel):
    """What the gates concluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    output: str


def main(argv: list[str]) -> int:
    """Run the gates for one worktree and print their outcome."""
    if len(argv) != EXPECTED_ARGUMENTS:
        print(USAGE, file=sys.stderr)
        return USAGE_EXIT
    passed, output = run_build_gates(argv[1], argv[2])
    print(GateOutcome(passed=passed, output=output).model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
