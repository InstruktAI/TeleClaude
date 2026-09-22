"""API request/response models for durable operation receipts and outcomes."""

from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict


class OperationStatusBlockingSnippetPayload(BaseModel):
    """Machine-readable snippet blocker payload exposed by operation DTOs."""

    model_config = ConfigDict(frozen=True)

    path: str
    slug_role: str
    live_deliverer_count: int
    other_removed_deliverers: list[str]


class OperationStatusErrorPayload(BaseModel):
    """Machine-readable operation failure payload exposed by API DTOs."""

    model_config = ConfigDict(frozen=True)

    kind: str | None = None
    blocking_snippets: list[OperationStatusBlockingSnippetPayload] | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.model_dump(exclude_none=True) == other
        return super().__eq__(other)


class OperationStatusDTO(BaseModel):
    """DTO for long-running operation receipts and status payloads."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    kind: str
    state: Literal["queued", "running", "completed", "failed", "stale", "cancelled"]
    poll_after_ms: int = 0
    status_path: str
    recovery_command: str
    slug: str | None = None
    success_event: str | None = None
    failure_event: str | None = None
    computer: str | None = None
    progress_phase: str | None = None
    progress_decision: str | None = None
    progress_reason: str | None = None
    result: str | None = None
    error: str | None = None
    error_payload: OperationStatusErrorPayload | None = None
    client_request_id: str | None = None


class OperationStatusPayload(TypedDict):
    """Typed dict form of the durable operation receipt payload."""

    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str
    slug: NotRequired[str]
    success_event: NotRequired[str]
    failure_event: NotRequired[str]
    computer: NotRequired[str]
    progress_phase: NotRequired[str]
    progress_decision: NotRequired[str]
    progress_reason: NotRequired[str]
    result: NotRequired[str]
    error: NotRequired[str]
    error_payload: NotRequired[OperationStatusErrorPayload]
    client_request_id: NotRequired[str]


class OperationSucceededEventDTO(BaseModel):
    """WebSocket event for a successful operation outcome."""

    model_config = ConfigDict(frozen=True)

    event: Literal[
        "operation.todo_work.completed",
        "operation.task_run.completed",
        "operation.todo_integrate.completed",
        "operation.todo_create.completed",
        "operation.todo_prepare.completed",
        "operation.todo_remove.completed",
        "operation.todo_rename.completed",
        "session.close.completed",
        "agent.restart.completed",
        "agent_runtime.handoff.completed",
    ]
    operation_id: str


class OperationFailedEventDTO(BaseModel):
    """WebSocket event for a failed operation outcome."""

    model_config = ConfigDict(frozen=True)

    event: Literal[
        "operation.todo_work.failed",
        "operation.task_run.failed",
        "operation.todo_integrate.failed",
        "operation.todo_create.failed",
        "operation.todo_prepare.failed",
        "operation.todo_remove.failed",
        "operation.todo_rename.failed",
        "session.close.failed",
        "agent.restart.failed",
        "agent_runtime.handoff.failed",
    ]
    operation_id: str
    error: str
