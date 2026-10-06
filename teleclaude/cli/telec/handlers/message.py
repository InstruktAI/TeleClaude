"""Handler for telec message."""

from __future__ import annotations

import sys

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import MESSAGE
from teleclaude.cli.tool_client import tool_api_request

__all__ = ["_handle_message"]

_MISSING_TEXT = "Missing required <text>."
_POSITIONAL_MIGRATION = "Only <text> is positional; name the recipient with --recipient <slug>."
_MESSAGE_SENT = "Message sent to {recipient} via {channel}."
_MESSAGE_FAILURE = "Not delivered to {recipient}: {detail}"
_DETAIL_KEY = "detail"
_STATUS_KEY = "status"
_OK_STATUS = "ok"
_UNUSABLE_RESPONSE = "Error: the message service returned an unusable success response."


def _handle_message(args: list[str]) -> None:
    """Handle telec message <text> [--recipient <slug>] [--file <path>] [--subject <text>] [--channel <name>]."""
    parsed = parse_command_args(MESSAGE, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(_POSITIONAL_MIGRATION)
        print(_usage("message"))
        raise SystemExit(1)
    if not positionals:
        print(_MISSING_TEXT)
        print(_usage("message"))
        raise SystemExit(1)
    text = positionals[0]

    from pydantic import ValidationError  # noqa: PLC0415 - deferred command-local dependency.

    from teleclaude.api_models import (  # noqa: PLC0415 - deferred command-local dependency.
        PersonMessageRequest,
        PersonMessageResponse,
    )
    from teleclaude.config.schema import MessagingChannel  # noqa: PLC0415 - deferred command-local dependency.

    channel_raw = parsed.value(F.FLAG_MSG_CHANNEL)
    channel: MessagingChannel | None = None
    if channel_raw is not None:
        try:
            channel = MessagingChannel(channel_raw)
        except ValueError:
            print(f"Invalid --channel '{channel_raw}': must be one of {', '.join(m.value for m in MessagingChannel)}.")
            raise SystemExit(1) from None

    request = PersonMessageRequest(
        recipient=parsed.value(F.FLAG_MSG_RECIPIENT),
        text=text,
        file=parsed.value(F.FLAG_MSG_FILE),
        subject=parsed.value(F.FLAG_MSG_SUBJECT),
        channel=channel,
    )
    api_result = tool_api_request(
        "POST",
        "/api/people/message",
        json_body=request.model_dump(mode="json"),
        timeout=30.0,
    )
    if not (isinstance(api_result, dict) and api_result.get(_STATUS_KEY) == _OK_STATUS):
        detail = api_result.get(_DETAIL_KEY, api_result) if isinstance(api_result, dict) else api_result
        print(f"Error: {detail}")
        raise SystemExit(1)

    try:
        response = PersonMessageResponse.model_validate(api_result)
    except ValidationError:
        print(_UNUSABLE_RESPONSE)
        raise SystemExit(1) from None

    for delivery in response.deliveries:
        print(_MESSAGE_SENT.format(recipient=delivery.recipient, channel=delivery.channel.value))
    for failure in response.failures:
        print(_MESSAGE_FAILURE.format(recipient=failure.recipient, detail=failure.detail), file=sys.stderr)
