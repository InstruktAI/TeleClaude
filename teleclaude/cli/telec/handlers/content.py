"""Handlers for telec content commands."""
from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.content_scaffold import _resolve_author, create_content_inbox_entry
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.slug import normalize_slug



__all__ = [
    "_handle_content",
    "_handle_content_dump",
]

def _handle_content(args: list[str]) -> None:
    """Handle telec content subcommands."""
    if not args:
        print(_usage("content"))
        return

    subcommand = args[0]
    if subcommand == "dump":
        _handle_content_dump(args[1:])
    else:
        print(f"Unknown content subcommand: {subcommand}")
        print(_usage("content"))
        raise SystemExit(1)


def _handle_content_dump(args: list[str]) -> None:
    """Handle telec content dump <text> [--slug <slug>] [--tags <tags>] [--author <author>]."""

    if not args:
        print(_usage("content", "dump"))
        return

    text: str | None = None
    slug: str | None = None
    tags: list[str] | None = None
    author: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg == "--tags" and i + 1 < len(args):
            raw = args[i + 1]
            tags = [t.strip() for t in raw.split(",") if t.strip()]
            i += 2
        elif arg == "--author" and i + 1 < len(args):
            author = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("content", "dump"))
            raise SystemExit(1)
        else:
            if text is not None:
                print("Only one text argument is allowed.")
                print(_usage("content", "dump"))
                raise SystemExit(1)
            text = arg
            i += 1

    if not text:
        print("Missing required text argument.")
        print(_usage("content", "dump"))
        raise SystemExit(1)

    if slug:
        # Validate and normalise provided slug
        slug = normalize_slug(slug)

    try:
        resolved_author = author if author is not None else _resolve_author()
        resolved_tags = tags or []
        entry_dir = create_content_inbox_entry(
            project_root,
            text,
            slug=slug,
            tags=resolved_tags,
            author=resolved_author,
        )
        try:
            envelope = EventEnvelope(
                event="content.dumped",
                source="telec-cli",
                level=EventLevel.WORKFLOW,
                domain="content",
                description=f"Content dumped: {entry_dir.relative_to(project_root)}",
                payload={
                    "inbox_path": str(entry_dir.relative_to(project_root)),
                    "author": resolved_author,
                    "tags": resolved_tags,
                },
            )
            tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
        except Exception:
            pass
        _log = get_logger(__name__)
        _log.info("Content dumped: %s", entry_dir.relative_to(project_root))
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
