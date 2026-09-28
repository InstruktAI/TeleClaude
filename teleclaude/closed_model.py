"""The closed validation posture shared by configuration models.

Hosted as a leaf module, not inside ``teleclaude.config``, because
``teleclaude.events.domain_config`` must inherit it without creating a reverse
import edge back into the config package.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import UnionType
from typing import Self, Union, get_args, get_origin

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
    annotated :data:`SENSITIVE` and of undeclared keys, which are masked.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def _mask_sensitive_inputs(cls, data: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        try:
            return handler(data)
        except ValidationError as error:
            lines = error.errors(include_url=False)
            masked = [_masked_input_at(cls, line["loc"], line["input"]) for line in lines]
            if all(value is line["input"] for value, line in zip(masked, lines, strict=True)):
                raise
            raise ValidationError.from_exception_data(
                error.title,
                [_rebuilt_line(line, value) for line, value in zip(lines, masked, strict=True)],
            ) from None


def _masked_input_at(model: type[ClosedModel], loc: tuple[int | str, ...], value: object) -> object:
    """Mask the input of one error raised while validating ``model``.

    An error on a sensitive or undeclared field hides its value. An error on the model as a
    whole, or on one of its fields, carries raw input that may hold nested
    secrets, so that input is masked along the model's declared structure.
    """
    if not loc:
        return _masked_by_annotation(model, value)
    field = model.model_fields.get(loc[0]) if isinstance(loc[0], str) else None
    if field is None or field_is_sensitive(field):
        # An undeclared key is rejected by name, so its value adds no diagnosis, and the
        # loader has already expanded any secret reference it held.
        return MASKED_INPUT
    return _masked_by_annotation(field.annotation, value) if len(loc) == 1 else value


def _masked_by_annotation(annotation: object, value: object) -> object:
    """Mask sensitive values in raw ``value`` shaped by ``annotation``; other values are kept."""
    if isinstance(annotation, type) and issubclass(annotation, ClosedModel):
        if not isinstance(value, Mapping):
            return value
        masked = {
            key: _masked_input_at(annotation, (key,), item) if isinstance(key, str) else item
            for key, item in value.items()
        }
        return value if all(masked[key] is item for key, item in value.items()) else masked
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType):
        for arg in args:
            value = _masked_by_annotation(arg, value)
        return value
    if isinstance(value, Mapping) and len(args) == 2:
        masked_map = {key: _masked_by_annotation(args[1], item) for key, item in value.items()}
        return value if all(masked_map[key] is item for key, item in value.items()) else masked_map
    if isinstance(value, list | tuple) and args:
        masked_items = [_masked_by_annotation(args[0], item) for item in value]
        return value if all(new is old for new, old in zip(masked_items, value, strict=True)) else masked_items
    return value


def _rebuilt_line(line: ErrorDetails, value: object) -> InitErrorDetails:
    return InitErrorDetails(
        # Re-raised under pydantic's own rendered type and message, so nothing is re-templated;
        # both are runtime strings, which the LiteralString parameter types cannot express.
        type=PydanticCustomError(line["type"], line["msg"]),  # pyright: ignore[reportArgumentType]
        loc=line["loc"],
        input=value,
    )
