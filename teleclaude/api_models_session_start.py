"""Public session-start input boundary, excluding in-daemon workflow context."""

from pydantic import BaseModel, model_validator

from teleclaude.types.session_creation import reject_workflow_creation_input


class PublicSessionStartRequest(BaseModel):
    """Preserve public request shapes while refusing the internal carrier key, including null."""

    @model_validator(mode="before")
    @classmethod
    def reject_internal_workflow(cls, value: object) -> object:
        """Do not let normal extra-field handling silently discard supplied internal authority."""
        return reject_workflow_creation_input(value)
