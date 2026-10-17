"""Typed partial models for editor work that the configuration owner completes later."""

from __future__ import annotations

from collections.abc import Mapping
from types import UnionType
from typing import Union, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError

type Document = Mapping[str, object]  # guard: loose-dict - partial effective configuration projection


def partial_model[ModelT: BaseModel](model_type: type[ModelT], data: Document) -> ModelT:
    """Build a typed model from held values, leaving unresolved required leaves unset."""
    held: dict[str, object] = {  # guard: loose-dict - values declared by the configuration model
        name: _partial_value(field_info.annotation, data[name])
        for name, field_info in model_type.model_fields.items()
        if name in data and data[name] is not None
    }
    try:
        return model_type.model_validate(held)
    except ValidationError:
        return model_type.model_construct(None, **{**_unset_fields(model_type), **held})


def _unset_fields(model_type: type[BaseModel]) -> dict[str, object]:  # guard: loose-dict - model construction input
    return {
        name: None if field_info.is_required() else field_info.get_default(call_default_factory=True)
        for name, field_info in model_type.model_fields.items()
    }


def _partial_value(annotation: object, value: object) -> object:
    if isinstance(value, Mapping):
        nested = _model_in(annotation)
        if nested is not None:
            return partial_model(nested, value)
        value_annotation = _dict_value_annotation(annotation)
        if value_annotation is not None:
            return {key: _partial_value(value_annotation, item) for key, item in value.items()}
    if isinstance(value, list):
        item_annotation = _list_item_annotation(annotation)
        if item_annotation is not None:
            return [_partial_value(item_annotation, item) for item in value]
    return value


def _options(annotation: object) -> tuple[object, ...]:
    if get_origin(annotation) in (Union, UnionType):
        return tuple(option for option in get_args(annotation) if option is not type(None))
    return (annotation,)


def _model_in(annotation: object) -> type[BaseModel] | None:
    return next(
        (option for option in _options(annotation) if isinstance(option, type) and issubclass(option, BaseModel)),
        None,
    )


def _dict_value_annotation(annotation: object) -> object | None:
    for option in _options(annotation):
        if get_origin(option) is dict and len(get_args(option)) == 2:
            return cast(object, get_args(option)[1])
    return None


def _list_item_annotation(annotation: object) -> object | None:
    for option in _options(annotation):
        if get_origin(option) is list and get_args(option):
            return cast(object, get_args(option)[0])
    return None
