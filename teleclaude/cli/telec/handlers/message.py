"""Handler for telec message."""

from __future__ import annotations

from teleclaude.api_models import PersonMessageRequest
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.config.schema import MessagingChannel

__all__ = ["_handle_message"]


def _handle_message(args: list[str]) -> None:
    """Handle telec message <slug> <text> [--file <path>] [--subject <text>] [--channel <name>]."""
    if not args:
        print(_usage("message"))
        return

    slug: str | None = None
    text: str | None = None
    file: str | None = None
    subject: str | None = None
    channel_raw: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--file" and i + 1 < len(args):
            file = args[i + 1]
            i += 2
        elif arg == "--subject" and i + 1 < len(args):
            subject = args[i + 1]
            i += 2
        elif arg == "--channel" and i + 1 < len(args):
            channel_raw = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("message"))
            raise SystemExit(1)
        elif slug is None:
            slug = arg
            i += 1
        elif text is None:
            text = arg
            i += 1
        else:
            print("Only one slug and one text argument are allowed.")
            print(_usage("message"))
            raise SystemExit(1)

    if not slug or not text:
        print("Missing required <slug> and <text>.")
        print(_usage("message"))
        raise SystemExit(1)

    channel: MessagingChannel | None = None
    if channel_raw is not None:
        try:
            channel = MessagingChannel(channel_raw)
        except ValueError:
            print(f"Invalid --channel '{channel_raw}': must be one of {', '.join(m.value for m in MessagingChannel)}.")
            raise SystemExit(1) from None

    request = PersonMessageRequest(slug=slug, text=text, file=file, subject=subject, channel=channel)
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
