"""Retryable HTTP refusal of new business work while the daemon drains."""

from __future__ import annotations

from http import HTTPMethod, HTTPStatus
from typing import Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from teleclaude.core.shutdown_drain import ShutdownRefusal

STATE_CHANGING_METHODS: frozenset[str] = frozenset(
    {HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH, HTTPMethod.DELETE}
)
_RETRY_AFTER_HEADER = "Retry-After"


class ShutdownRefusalDTO(BaseModel):
    """Body of a refusal: nothing was accepted, retry against the next daemon process."""

    kind: Literal["shutdown_refusal"] = "shutdown_refusal"
    phase: str
    work: str
    retry_after_seconds: int


def shutdown_refusal_response(refusal: ShutdownRefusal) -> JSONResponse:
    """The explicit, retryable answer to work refused before acceptance."""
    body = ShutdownRefusalDTO(
        phase=refusal.phase,
        work=refusal.work,
        retry_after_seconds=refusal.retry_after_seconds,
    )
    return JSONResponse(
        {"detail": body.model_dump()},
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        headers={_RETRY_AFTER_HEADER: str(refusal.retry_after_seconds)},
    )
