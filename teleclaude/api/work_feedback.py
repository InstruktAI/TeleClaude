"""HTTP carrier for work refusals whose owner publishes an operator message."""

from fastapi import HTTPException
from fastapi.responses import JSONResponse

_DETAIL_FIELD = "detail"
_WORK_FEEDBACK_FIELD = "work_feedback"


class DeclaredWorkRefusal(HTTPException):
    """Carry an explicit work-feedback declaration beside the ordinary HTTP error."""

    def __init__(self, *, status_code: int, detail: object, work_feedback: str, headers: dict[str, str] | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.work_feedback = work_feedback


def declared_refusal_response(
    *, status_code: int, detail: object, work_feedback: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    """The JSON body a declared work refusal travels as, for callers that answer outside the router."""
    return JSONResponse(
        status_code=status_code,
        content={_DETAIL_FIELD: detail, _WORK_FEEDBACK_FIELD: work_feedback},
        headers=headers,
    )
