"""Handler for telec message."""

from __future__ import annotations

from teleclaude.api_models import PersonMessageRequest
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import MESSAGE
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.config.schema import MessagingChannel

__all__ = ["_handle_message"]


def _handle_message(args: list[str]) -> None:
    """Handle telec message <slug> <text> [--file <path>] [--subject <text>] [--channel <name>]."""
    if not args:
        print(_usage("message"))
        return

    parsed = parse_command_args(MESSAGE, args)
    positionals = parsed.positionals
    if len(positionals) > 2:
        print("Only one slug and one text argument are allowed.")
        print(_usage("message"))
        raise SystemExit(1)
    slug = positionals[0] if positionals else None
    text = positionals[1] if len(positionals) > 1 else None

    if not slug or not text:
        print("Missing required <slug> and <text>.")
        print(_usage("message"))
        raise SystemExit(1)

    channel_raw = parsed.value(F.FLAG_MSG_CHANNEL)
    channel: MessagingChannel | None = None
    if channel_raw is not None:
        try:
            channel = MessagingChannel(channel_raw)
        except ValueError:
            print(f"Invalid --channel '{channel_raw}': must be one of {', '.join(m.value for m in MessagingChannel)}.")
            raise SystemExit(1) from None

    request = PersonMessageRequest(
        slug=slug,
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
    if not (isinstance(api_result, dict) and api_result.get("status") == "ok"):
        detail = api_result.get("detail", api_result) if isinstance(api_result, dict) else api_result
        print(f"Error: {detail}")
        raise SystemExit(1)

    print(f"Message sent to {slug} via {api_result.get('channel', '?')}.")
