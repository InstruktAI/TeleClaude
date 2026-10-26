"""Refuse a caller act whose target is an orchestrator above it in the dispatch chain.

An orchestrator's dispatch confers the mandate its descendants work under, and
their completed turns already reach it, so no session acts on an orchestrator
above it — sending it a message, opening or closing a direct conversation with
it, unsubscribing from it, ending it, or restarting it. Any other dispatch
confers no mandate and restricts nothing. The ancestry fact is
``session_descends_from`` (``teleclaude.core.session_utils``); this module is
its edge translation into an HTTP refusal, parallel to
``teleclaude.api.todo_artifact_authority`` for the todo-claim relationship —
that module reads a todo's claim, this one reads the session graph.
"""

from __future__ import annotations

import re
from http import HTTPMethod

from fastapi import HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity
from teleclaude.core.db import db
from teleclaude.core.roles import is_orchestrator_role
from teleclaude.core.session_utils import session_descends_from

logger = get_logger(__name__)

ACT_SEND_MESSAGE = "telec sessions send"
ACT_END = "telec sessions end"
ACT_UNSUBSCRIBE = "telec sessions unsubscribe"
ACT_RESTART = "telec sessions restart"

_TARGET_GROUP = "session_id"
_ANCESTOR_ACT_ROUTES: tuple[tuple[HTTPMethod, re.Pattern[str], str], ...] = (
    (HTTPMethod.POST, re.compile(rf"^/sessions/(?P<{_TARGET_GROUP}>[^/]+)/message$"), ACT_SEND_MESSAGE),
    (HTTPMethod.DELETE, re.compile(rf"^/sessions/(?P<{_TARGET_GROUP}>[^/]+)$"), ACT_END),
    (HTTPMethod.POST, re.compile(rf"^/sessions/(?P<{_TARGET_GROUP}>[^/]+)/agent-restart$"), ACT_RESTART),
    (HTTPMethod.POST, re.compile(rf"^/sessions/(?P<{_TARGET_GROUP}>[^/]+)/unsubscribe$"), ACT_UNSUBSCRIBE),
)
_SESSION_ACT_REFUSED_ANCESTOR_EVENT = "session_act_refused_ancestor"
REFUSED_ANCESTOR_DETAIL = (
    "orchestrator session '{target_session_id}' is above caller '{caller_session_id}' in its "
    "dispatch chain; {act} is refused. The caller's completed turn already reaches the "
    "orchestrator, so the result belongs in the caller's own output, not in an act directed "
    "upward."
)


async def refuse_act_on_ancestor(caller: CallerIdentity, target_session_id: str, act: str) -> None:
    """Refuse ``act`` when ``target_session_id`` is an orchestrator the caller strictly descends from.

    A caller with no session identity — a human at a terminal, the TUI — has
    no dispatch chain and is never refused. A caller targeting itself is not
    refused: identity is not descent. An ancestor that is not an orchestrator
    conferred no mandate, so an act on it is not refused. Called before any
    side effect of the act being attempted.
    """
    if not caller.session_id or caller.session_id == target_session_id:
        return
    if not await session_descends_from(caller.session_id, target_session_id):
        return
    target = await db.get_session(target_session_id)
    if target is None or not is_orchestrator_role(target.role):
        return
    logger.info(
        _SESSION_ACT_REFUSED_ANCESTOR_EVENT,
        caller_session_id=caller.session_id,
        target_session_id=target_session_id,
        act=act,
    )
    raise HTTPException(
        status_code=403,
        detail=REFUSED_ANCESTOR_DETAIL.format(
            target_session_id=target_session_id,
            caller_session_id=caller.session_id,
            act=act,
        ),
    )


def ancestor_act_for_request(method: str, path: str) -> tuple[str, str] | None:
    """The session act a request performs and the session it targets, when the ancestor rule governs it."""
    for route_method, pattern, act in _ANCESTOR_ACT_ROUTES:
        if method != route_method.value:
            continue
        match = pattern.match(path)
        if match is not None:
            return act, match.group(_TARGET_GROUP)
    return None
