"""The request deadline of workflow API requests, and the explicit refusals their store waits end in."""

from __future__ import annotations

from collections.abc import AsyncIterator
from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.work_feedback import declared_refusal_response
from teleclaude.core.todos_db._write_admission import WorkingCopyWriteRefused, request_deadline
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure
from teleclaude.core.workflow_store.store import GitHubIORefused

logger = get_logger(__name__)

_RETRY_AFTER_HEADER = "Retry-After"
_RETRY_AFTER_SECONDS = "5"

_NOTHING_WRITTEN = (
    "The working copy was busy past this request's deadline, so nothing was written. Send the request again."
)
_PART_SAVED = (
    "Part of this request was saved before the working copy refused the rest. "
    "Check the current state before sending the remainder again."
)
_MAY_BE_SAVED = (
    "The working copy ran out of time after the change was sent to GitHub, so it may have been saved "
    "and will appear once the store refreshes. Check before sending it again."
)
_AWAITING_REPUBLICATION = (
    "This item's record awaits republication to GitHub's native artifacts, so nothing was written. "
    "Send the request again once it has been republished."
)
_GITHUB_STORE_REFUSED_EVENT = "github_store_refused"
_GITHUB_STORE_REFUSED = (
    "The GitHub store refused this request ({reason}). "
    "A change already sent to GitHub may have been saved and will appear once the store refreshes."
)


async def working_copy_request_deadline() -> AsyncIterator[None]:
    """Router dependency: every working-copy wait of this request shares one deadline.

    FastAPI runs an async dependency in the request's own task, which is the task the scope is honoured in.
    """
    with request_deadline():
        yield


def working_copy_refusal_response(refusal: WorkingCopyWriteRefused) -> JSONResponse:
    """The explicit 503 for a refused working-copy wait, stating only what the refusal establishes."""
    if refusal.commit_point_sent:
        feedback, headers = _MAY_BE_SAVED, None
    elif refusal.request_saved:
        feedback, headers = _PART_SAVED, None
    else:
        feedback, headers = _NOTHING_WRITTEN, {_RETRY_AFTER_HEADER: _RETRY_AFTER_SECONDS}
    return declared_refusal_response(
        status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=feedback, work_feedback=feedback, headers=headers
    )


async def working_copy_refusal_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Exception handler for the store's working-copy refusal."""
    if not isinstance(exc, WorkingCopyWriteRefused):
        raise exc
    return working_copy_refusal_response(exc)


async def github_store_refusal_handler(request: Request, exc: Exception) -> JSONResponse:
    """Exception handler for the GitHub store's refusal: the response names its bounded reason, never provider text."""
    if not isinstance(exc, GitHubIORefused):
        raise exc
    logger.warning(
        _GITHUB_STORE_REFUSED_EVENT,
        reason=exc.reason.value,
        method=request.method,
        path=request.url.path,
    )
    if exc.reason is GitHubIOFailure.AWAITING_REPUBLICATION:
        return declared_refusal_response(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail=_AWAITING_REPUBLICATION,
            work_feedback=_AWAITING_REPUBLICATION,
            headers={_RETRY_AFTER_HEADER: _RETRY_AFTER_SECONDS},
        )
    feedback = _GITHUB_STORE_REFUSED.format(reason=exc.reason.value)
    return declared_refusal_response(
        status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=feedback, work_feedback=feedback
    )
