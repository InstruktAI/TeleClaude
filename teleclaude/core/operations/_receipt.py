"""How a receipt tells its caller where its operation lives and how to read it."""

from teleclaude.config.machine import config

_RECOVERY_COMMAND_TEMPLATE = "telec operations get {operation_id} --computer {computer}"


def recovery_command(operation_id: str) -> str:
    """The command that reads an operation, addressed to the computer that owns its row."""
    return _RECOVERY_COMMAND_TEMPLATE.format(operation_id=operation_id, computer=config.computer.name)
