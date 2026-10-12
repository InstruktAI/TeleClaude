"""The closed validation posture shared by configuration models and the models that reuse it."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum, auto
from types import UnionType
from typing import Self, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, ModelWrapValidatorHandler, ValidationError, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import ErrorDetails, InitErrorDetails, PydanticCustomError

MASKED_INPUT = "********"
_UNSET_TEXT = ""


class SensitiveMarker:
    """Annotation marker declaring that a field holds a secret."""

    __slots__ = ()


SENSITIVE = SensitiveMarker()
"""Mark a field secret: ``token: Annotated[str | None, SENSITIVE] = None``."""


def field_is_sensitive(field_info: FieldInfo) -> bool:
    """Whether a Pydantic field is annotated with :data:`SENSITIVE`."""
    return any(isinstance(marker, SensitiveMarker) for marker in field_info.metadata)


def mask_sensitive_values(annotation: object, value: object) -> object:
    """Replace every set value of a :data:`SENSITIVE` field in raw ``value`` shaped by ``annotation``.

    Undeclared keys and unset values are kept, so a rendered view still shows what is absent.
    """
    return _masked_by_annotation(annotation, value, _MaskScope.SENSITIVE_ONLY)


class _MaskScope(Enum):
    """Which values a structural mask replaces."""

    SENSITIVE_ONLY = auto()
    SENSITIVE_AND_UNDECLARED = auto()


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
            masked = [
                _masked_input_at(cls, line["loc"], line["input"], _MaskScope.SENSITIVE_AND_UNDECLARED) for line in lines
            ]
            if all(value is line["input"] for value, line in zip(masked, lines, strict=True)):
                raise
            raise ValidationError.from_exception_data(
                error.title,
                [_rebuilt_line(line, value) for line, value in zip(lines, masked, strict=True)],
            ) from None


def _masked_input_at(model: type[ClosedModel], loc: tuple[int | str, ...], value: object, scope: _MaskScope) -> object:
    """Mask the input of one error raised while validating ``model``.

    An error on a sensitive or undeclared field hides its value. An error on the model as a
    whole, or on one of its fields, carries raw input that may hold nested
    secrets, so that input is masked along the model's declared structure.
    """
    if not loc:
        return _masked_by_annotation(model, value, scope)
    field = model.model_fields.get(loc[0]) if isinstance(loc[0], str) else None
    if field is None:
        # An undeclared key is rejected by name, so its value adds no diagnosis, and the
        # loader has already expanded any secret reference it held.
        return MASKED_INPUT if scope is _MaskScope.SENSITIVE_AND_UNDECLARED else value
    if field_is_sensitive(field):
        unset = value is None or value == _UNSET_TEXT
        return MASKED_INPUT if scope is _MaskScope.SENSITIVE_AND_UNDECLARED or not unset else value
    return _masked_by_annotation(field.annotation, value, scope) if len(loc) == 1 else value


def _masked_by_annotation(annotation: object, value: object, scope: _MaskScope) -> object:
    """Mask sensitive values in raw ``value`` shaped by ``annotation``; other values are kept."""
    if isinstance(annotation, type) and issubclass(annotation, ClosedModel):
        if not isinstance(value, Mapping):
            return value
        masked = {
            key: _masked_input_at(annotation, (key,), item, scope) if isinstance(key, str) else item
            for key, item in value.items()
        }
        return value if all(masked[key] is item for key, item in value.items()) else masked
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType):
        for arg in args:
            value = _masked_by_annotation(arg, value, scope)
        return value
    if isinstance(value, Mapping) and len(args) == 2:
        masked_map = {key: _masked_by_annotation(args[1], item, scope) for key, item in value.items()}
        return value if all(masked_map[key] is item for key, item in value.items()) else masked_map
    if isinstance(value, list | tuple) and args:
        masked_items = [_masked_by_annotation(args[0], item, scope) for item in value]
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
