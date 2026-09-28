"""The closed validation posture shared by configuration models.

Hosted as a leaf module, not inside ``teleclaude.config``, because
``teleclaude.events.domain_config`` must inherit it without creating a reverse
import edge back into the config package.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, ConfigDict, ModelWrapValidatorHandler, ValidationError, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails, InitErrorDetails, PydanticCustomError

MASKED_INPUT = "********"


class SensitiveMarker:
    """Annotation marker declaring that a field holds a secret."""

    __slots__ = ()


SENSITIVE = SensitiveMarker()
"""Mark a field secret: ``token: Annotated[str | None, SENSITIVE] = None``."""


def field_is_sensitive(field_info: FieldInfo) -> bool:
    """Whether a Pydantic field is annotated with :data:`SENSITIVE`."""
    return any(isinstance(marker, SensitiveMarker) for marker in field_info.metadata)


class ClosedModel(BaseModel):
    """A model that rejects undeclared keys instead of silently accepting them.

    Validation errors keep every rejected input value except those of fields
    annotated :data:`SENSITIVE`, which are masked.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def _mask_sensitive_inputs(cls, data: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        try:
            return handler(data)
        except ValidationError as error:
            sensitive = frozenset(name for name, info in cls.model_fields.items() if field_is_sensitive(info))
            if not sensitive:
                raise
            raise ValidationError.from_exception_data(
                error.title,
                [_masked_line(line, sensitive) for line in error.errors(include_url=False)],
            ) from None


def _masked_line(line: ErrorDetails, sensitive: frozenset[str]) -> InitErrorDetails:
    loc = line["loc"]
    value: object = line["input"]
    if loc and loc[0] in sensitive:
        value = MASKED_INPUT
    elif not loc and isinstance(value, Mapping):
        value = {key: MASKED_INPUT if key in sensitive else item for key, item in value.items()}
    return InitErrorDetails(
        # Re-raised under pydantic's own rendered type and message, so nothing is re-templated;
        # both are runtime strings, which the LiteralString parameter types cannot express.
        type=PydanticCustomError(line["type"], line["msg"]),  # pyright: ignore[reportArgumentType]
        loc=loc,
        input=value,
    )
