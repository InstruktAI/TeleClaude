"""Which computer a telec invocation addresses, and how it names the project it acts on there.

The router records the computer a command is addressed to. Every request the
invocation then sends carries it, so the computer that owns the object answers
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).
A command run from a project's checkout and addressed to another computer acts on
that same registered project there: the checkout's path means nothing on another
computer, so the project is named by the identity it is registered under.
"""

from __future__ import annotations

import sys
from contextvars import ContextVar

from teleclaude.cli.session_auth import ComputerTargetDisposition, classify_computer_target
from teleclaude.paths import invocation_cwd
from teleclaude.services.project_catalog.ownership import load_project_ownership_index

_ADDRESSED_COMPUTER_NAME = "telec_cli_addressed_computer"
_ADDRESSED_COMPUTER: ContextVar[str | None] = ContextVar(_ADDRESSED_COMPUTER_NAME, default=None)
_UNREGISTERED_CHECKOUT = "Error: {path} is not in a registered project, so it names no project on {computer}."


def address_computer(target_computer: str | None) -> None:
    """Record the computer this invocation addresses when it is not this one."""
    if classify_computer_target(target_computer) is ComputerTargetDisposition.REMOTE:
        _ADDRESSED_COMPUTER.set(target_computer)


def remote_computer(computer: str | None) -> str | None:
    """The computer a UI row belongs to when it is another computer, else None."""
    if classify_computer_target(computer) is ComputerTargetDisposition.REMOTE:
        return computer
    return None


def addressed_computer() -> str | None:
    """The other computer this invocation addresses, or None when it acts on this one."""
    return _ADDRESSED_COMPUTER.get()


def project_reference() -> str:
    """The project this invocation acts on, named the way the addressed computer will read it.

    On this computer that is the checkout's own path. On another computer it is the identity
    the checkout's project is registered under here; a checkout outside every registered project
    names none, which is this computer's fact about its own checkout and is refused here.
    """
    checkout = invocation_cwd()
    computer = addressed_computer()
    if computer is None:
        return str(checkout)
    ownership = load_project_ownership_index().for_path(checkout)
    if ownership is None:
        print(_UNREGISTERED_CHECKOUT.format(path=checkout, computer=computer), file=sys.stderr)
        raise SystemExit(1)
    return ownership.project_slug
