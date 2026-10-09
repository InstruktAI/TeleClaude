"""Shared receipt rendering for durable operations.

A receipt-backed command prints its receipt and returns. The operation's outcome is
delivered to the calling session, and `telec operations get` reads the record.
"""

from __future__ import annotations

import sys
from typing import Final

from teleclaude.cli.tool_client import print_json

_OPERATION_ID_FIELD: Final = "operation_id"
_RECOVERY_COMMAND_FIELD: Final = "recovery_command"
_OPERATION_READ_COMMAND_TEMPLATE: Final = "telec operations get {operation_id}"
_OUTCOME_DELIVERY_LINE_TEMPLATE: Final = (
    "Operation {operation_id}: the outcome is delivered to the calling session. Read it with: {read_command}"
)


def render_receipt(response: object) -> None:
    """Print the daemon's response as JSON, then name how a receipt's outcome is read.

    The JSON goes to stdout. A response that carries an operation receipt adds one line to
    stderr saying the outcome is delivered to the calling session and which command reads
    it; any other response prints as JSON only.
    """
    print_json(response)
    if not isinstance(response, dict):
        return
    operation_id = response.get(_OPERATION_ID_FIELD)
    if not isinstance(operation_id, str) or not operation_id:
        return
    read_command = response.get(_RECOVERY_COMMAND_FIELD)
    if not isinstance(read_command, str) or not read_command:
        read_command = _OPERATION_READ_COMMAND_TEMPLATE.format(operation_id=operation_id)
    print(
        _OUTCOME_DELIVERY_LINE_TEMPLATE.format(operation_id=operation_id, read_command=read_command),
        file=sys.stderr,
    )
