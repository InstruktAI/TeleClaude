"""Normalized query parsing for transcript-backed session reads."""

from dataclasses import dataclass

from fastapi import Query


@dataclass(frozen=True)
class SessionMessagesQuery:
    """Normalized query parameters for message retrieval."""

    computer: str | None = None
    since: str | None = None
    include_tools: bool | None = None
    include_thinking: bool = False
    tail_chars: int = 10000
    tail_scope: str = "all"


def parse_session_messages_query(
    computer: str | None = Query(None, description="Target computer"),
    since: str | None = Query(None, description="ISO 8601 UTC timestamp; only messages after this time"),
    include_tools: bool | None = Query(None, description="Include tool invocation entries when policy allows them"),
    include_thinking: bool = Query(False, description="Include thinking/reasoning blocks"),
    tail_chars: int = Query(10000, description="Fallback char budget for tmux/session tail output"),
    tail_scope: str = Query("all", description="Message window: all or latest_turn"),
) -> SessionMessagesQuery:
    """Collect session-messages query parameters into one object."""
    return SessionMessagesQuery(
        computer=computer,
        since=since,
        include_tools=include_tools,
        include_thinking=include_thinking,
        tail_chars=tail_chars,
        tail_scope=tail_scope,
    )
