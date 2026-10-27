"""Find, or write, the moment a project's conversation began.

The project's ledger issue holds one `[action:conversation-start at:<time>]` entry, written by the platform App as
record work the first time any computer runs the publisher for the project. The entry the issue's comment order
puts first is the project's conversation start on every computer and after every rebuild, so neither a restart nor
a rebuilt working copy publishes a turn completed before the capability went live. The entry carries no ledger
marker, so stores that predate it read past it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from teleclaude.core.workflow_store.github_conversation_record import (
    parse_conversation_start,
    render_conversation_start,
)
from teleclaude.core.workflow_store.github_io import GitHubWorkflowIO
from teleclaude.core.workflow_store.github_record import trusted_comment_body


async def read_conversation_start(io: GitHubWorkflowIO, bot_login: str, ledger_issue_number: int) -> datetime | None:
    """The first conversation-start entry the platform App wrote on the ledger issue, in creation order."""
    comments = await io.async_read_comments(ledger_issue_number)
    for comment in sorted(comments, key=lambda candidate: candidate.database_id):
        body = trusted_comment_body(
            author=comment.author,
            editor=comment.editor,
            body=comment.body,
            edits=comment.edit_history,
            history_complete=comment.history_complete,
            bot_login=bot_login,
        )
        started = parse_conversation_start(body) if body is not None else None
        if started is not None:
            return started
    return None


async def ensure_conversation_start(io: GitHubWorkflowIO, bot_login: str, ledger_issue_number: int) -> datetime:
    """The project's conversation start, appending the entry first when the ledger issue holds none.

    Two computers that append at once leave two entries; both then read the same first one.
    """
    started = await read_conversation_start(io, bot_login, ledger_issue_number)
    if started is not None:
        return started
    now = datetime.now(UTC)
    await io.async_create_comment(ledger_issue_number, render_conversation_start(now))
    return await read_conversation_start(io, bot_login, ledger_issue_number) or now
