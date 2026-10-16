"""The retained workflow event trail of one item, read under the ordinary item-read clearance and identity reach.

``local/projects/teleclaude/spec/feature/event-catalog/item-event-occurrences``. The computer that emitted the events
answers: it reads its own retained stream, applies the caller\'s current reach to every occurrence, and states what the
covered interval does and does not establish.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Query

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution, carried_caller
from teleclaude.api.todo_slug_routes import request_project_root
from teleclaude.config.machine import config
from teleclaude.core.models import JsonDict
from teleclaude.events.envelope import EventHomeRef, home_token
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.item_trail import (
    CURSOR_INVALID,
    CURSOR_LOST,
    DEFAULT_LIMIT,
    TODO_SUBJECT_PREFIX,
    UNAVAILABLE,
    Selection,
    TrailError,
    TrailRequest,
    daemon_cursors,
    read_trail,
)
from teleclaude.events.producer import configured_producer
from teleclaude.identity_reach import resolve_reach
from teleclaude.slug import validate_slug

router = APIRouter(prefix="/events", tags=["events"])

NOT_REGISTERED: Final = "{root} is not a registered project, so it has no retained item trail"
UNAVAILABLE_DETAIL: Final = "the event platform is not available on this computer"
EXCLUSIVE_DETAIL: Final = "--mark, --since and --cursor are mutually exclusive"
STATUS_BY_KIND: Final = {UNAVAILABLE: 503, CURSOR_INVALID: 400, CURSOR_LOST: 410}


@router.get("/trail/{item}")
async def item_trail(
    item: str,
    cwd: str | None = None,
    limit: Annotated[int, Query(ge=1)] = DEFAULT_LIMIT,
    mark: Annotated[bool, Query()] = False,
    since: str | None = None,
    cursor: str | None = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> JsonDict:
    """Return one page of an item\'s retained workflow event trail, or an observation cursor."""
    try:
        validate_slug(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if sum((mark, since is not None, cursor is not None)) > 1:
        raise HTTPException(status_code=400, detail=EXCLUSIVE_DETAIL)
    project_root = request_project_root(cwd)
    home = home_for_project_path(project_root)
    if not isinstance(home, EventHomeRef):
        raise HTTPException(status_code=400, detail=NOT_REGISTERED.format(root=project_root))
    producer = configured_producer()
    if producer is None:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
    selection = Selection(config.computer.name, home_token(home), f"{TODO_SUBJECT_PREFIX}{item}")
    reach = resolve_reach(caller_for_role_resolution(identity))
    try:
        result = await read_trail(
            producer.stream_reader(),
            selection,
            reach,
            TrailRequest(limit=limit, mark=mark, since=since, cursor=cursor),
            daemon_cursors(),
        )
    except TrailError as error:
        raise HTTPException(status_code=STATUS_BY_KIND[error.kind], detail=str(error)) from error
    return result.to_json()
