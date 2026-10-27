"""The commit-review stamp surface backed by repository-scoped workflow evidence."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.working_copy_request import working_copy_request_deadline
from teleclaude.core.next_machine.commit_review_stamps import apply_commit_review_stamp
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.git import GitCommandError
from teleclaude.types.todos import CommitReviewVerdict

router = APIRouter(prefix="/code", tags=["code"], dependencies=[Depends(working_copy_request_deadline)])

_ERR_NO_SESSION = "a commit-review stamp requires a TeleClaude session: the record must name the stamping session"
_ERR_NO_CWD = "cwd required: working directory not provided"


class CommitReviewStampResponse(BaseModel):
    """What one stamp request recorded and which sessions' review gate it discharges."""

    slug: str | None
    shas: list[str]
    verdict: CommitReviewVerdict
    discharged_sessions: list[str]


@router.post("/stamp", response_model=CommitReviewStampResponse)
async def commit_review_stamp(
    shas: Annotated[list[str], Body()],
    verdict: Annotated[CommitReviewVerdict, Body()],
    cwd: Annotated[str | None, Body()] = None,
    reason: Annotated[str, Body()] = "",
    identity: CallerIdentity = Depends(carried_caller),
) -> CommitReviewStampResponse:
    """Record one repository-scoped commit-review stamp per SHA.

    The stamping session is the verified request identity, never the body. A
    caller with no session id is refused: the record must name who stamped.
    Unresolvable or off-main SHAs are refused before anything is written.
    """
    if not identity.session_id:
        raise HTTPException(status_code=403, detail=_ERR_NO_SESSION)
    if not cwd:
        raise HTTPException(status_code=400, detail=_ERR_NO_CWD)
    try:
        result = await apply_commit_review_stamp(
            cwd=cwd, session_id=identity.session_id, shas=shas, verdict=verdict, reason=reason
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (StateMutationError, ValueError, GitCommandError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CommitReviewStampResponse(
        slug=result.slug,
        shas=list(result.shas),
        verdict=result.verdict,
        discharged_sessions=list(result.discharged_sessions),
    )
