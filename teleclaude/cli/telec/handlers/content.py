"""Handlers for telec content commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import CONTENT_DUMP
from teleclaude.config import config
from teleclaude.content_scaffold import _resolve_author, create_content_inbox_entry
from teleclaude.events.envelope import EventLevel, EventSubjectMarker
from teleclaude.events.envelope_facts import cli_envelope_fact_resolver
from teleclaude.events.producer import emit_event, loop_local_producer
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.slug import normalize_slug

__all__ = [
    "_handle_content",
    "_handle_content_dump",
]

_CONTENT_DUMPED_EVENT = "content.dumped"
_CONTENT_DUMP_SOURCE = "telec-cli"
_CONTENT_DOMAIN = "content"
_CONTENT_DUMPED_DESCRIPTION = "Content dumped: {path}"
_EMIT_FAILED_LOG_EVENT = "content_dump_event_emit_failed"
_REDIS_UNCONFIGURED_REASON = "redis_url_not_configured"


class _ContentDumpPayload(TypedDict):
    """Payload published with the `content.dumped` event."""

    inbox_path: str
    author: str
    tags: list[str]


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

    text, slug, tags, author = _parse_content_dump_args(args)
    if slug:
        # Validate and normalise provided slug
        slug = normalize_slug(slug)

    try:
        project_root = resolve_invocation_roots().require_project_root()
        resolved_author = author if author is not None else _resolve_author()
        resolved_tags = tags or []
        entry_dir = create_content_inbox_entry(
            project_root,
            text,
            slug=slug,
            tags=resolved_tags,
            author=resolved_author,
        )
        _emit_content_dump_event(project_root, entry_dir, resolved_author, resolved_tags)
        _log = get_logger(__name__)
        _log.info("Content dumped: %s", entry_dir.relative_to(project_root))
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


def _parse_content_dump_args(args: list[str]) -> tuple[str, str | None, list[str] | None, str | None]:
    parsed = parse_command_args(CONTENT_DUMP, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one text argument is allowed.")
        print(_usage("content", "dump"))
        raise SystemExit(1)
    text = positionals[0] if positionals else None
    if not text:
        print("Missing required text argument.")
        print(_usage("content", "dump"))
        raise SystemExit(1)

    slug = parsed.value(F.FLAG_CONTENT_SLUG)
    tags_raw = parsed.value(F.FLAG_CONTENT_TAGS)
    tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()] if tags_raw is not None else None
    author = parsed.value(F.FLAG_CONTENT_AUTHOR)
    return text, slug, tags, author


def _emit_content_dump_event(
    project_root: Path, entry_dir: Path, resolved_author: str, resolved_tags: list[str]
) -> None:
    relative_path = entry_dir.relative_to(project_root)
    payload = _ContentDumpPayload(
        inbox_path=str(relative_path),
        author=resolved_author,
        tags=resolved_tags,
    )
    _log = get_logger(__name__)

    # The inbox entry is already durably written by the time this runs, and the
    # command's documented contract makes notification delivery optional — so an
    # unavailable notification service is logged rather than failed.
    if not config.redis.url:
        _log.warning(_EMIT_FAILED_LOG_EVENT, inbox_path=payload["inbox_path"], error=_REDIS_UNCONFIGURED_REASON)
        return

    async def emit() -> None:
        resolver = cli_envelope_fact_resolver()
        session_id = resolver.session_id()
        session_subject = await resolver.session_home(session_id) if session_id else EventSubjectMarker.NONE
        async with loop_local_producer() as producer:
            await emit_event(
                _CONTENT_DUMPED_EVENT,
                source=_CONTENT_DUMP_SOURCE,
                level=EventLevel.WORKFLOW,
                producer=producer,
                domain=_CONTENT_DOMAIN,
                subject=session_subject,
                description=_CONTENT_DUMPED_DESCRIPTION.format(path=relative_path),
                payload=payload,
            )

    try:
        asyncio.run(emit())
    except (RedisError, OSError, TimeoutError) as exc:
        _log.warning(_EMIT_FAILED_LOG_EVENT, inbox_path=payload["inbox_path"], error=repr(exc))
