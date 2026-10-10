"""Declared relationships between the fields of one configuration document.

A boolean field declares ``Annotated[bool, Requires("path.to.target", value)]``: when it is
true, the field at that path from the document root must hold that value. The declaration
only validates; it never assigns a value. One collected inventory, one evaluator and one
message feed the published schema rule, model validation and the persistence refusal, so
every surface judges the same document the same way.

A field whose value only some computers need declares ``Annotated[..., RequiredWhen("flag.path")]``
against the machine configuration instead. It is judged by validations that resolved the
document's references on this computer and carry that computer's machine configuration.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from types import UnionType
from typing import Any, Final, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import InitErrorDetails, PydanticCustomError

from teleclaude.closed_model import ClosedModel
from teleclaude.config.surface import nested_model

type SchemaFragment = dict[str, object]  # guard: loose-dict - JSON Schema fragments are untyped JSON

_PATH_SEPARATOR: Final = "."
_MESSAGE: Final = "{requiring} requires {target}: {value}"
_NOT_BOOLEAN: Final = "Field constraint on `{path}`: only a boolean field can require another field"
_DEFAULTS_TO_TRUE: Final = (
    "Field constraint on `{path}`: a requiring field must default to false, "
    "or an absent field would break the relationship unflagged"
)
_UNRESOLVED_TARGET: Final = "Field constraint on `{path}`: `{target}` does not resolve to a field of the document"
_VALUE_REJECTED: Final = "Field constraint on `{path}`: `{target}` does not accept the required value"
_CONTAINER_MEMBER: Final = (
    "Field constraint declared inside `{path}`, which is reachable only through a list or mapping: "
    "no document path addresses it"
)
_VIOLATION_CODE: Final = "field_constraint"
_REQUIREMENT_CODE: Final = "field_requirement"
_REQUIREMENT_MESSAGE: Final = (
    "{field} is needed on a computer where {flag} is set, but ${{{name}}} has no value in its home's .env"
)
_UNKNOWN_MACHINE_FLAG: Final = "Field requirement on `{field}`: `{flag}` is not a field of the machine configuration"

MACHINE_CONTEXT_KEY: Final = "machine"
"""Validation-context key carrying this computer's machine configuration."""
UNRESOLVED_CONTEXT_KEY: Final = "unresolved"
"""Validation-context key carrying the document's references that have no value here, by path."""
_REFUSED_INPUT: Final = True


class SchemaKeyword(StrEnum):
    """The JSON Schema keywords a constraint rule is built from."""

    ALL_OF = "allOf"
    CONST = "const"
    ERROR_MESSAGE = "errorMessage"
    IF = "if"
    NOT = "not"
    PROPERTIES = "properties"
    REQUIRED = "required"
    THEN = "then"


class _Unresolved:
    """The value of a path that no document or default reaches."""


_UNRESOLVED: Final = _Unresolved()


@dataclass(frozen=True, slots=True)
class Requires:
    """Annotation marker: when this boolean field is true, ``target`` must hold ``value``.

    ``target`` is the dotted path of the required field from the document root.
    """

    target: str
    value: object


@dataclass(frozen=True, slots=True)
class RequiredWhen:
    """Annotation marker: a value declared for this field is needed on a computer whose machine flag holds.

    ``machine`` is the dotted path of a boolean field of the machine configuration. On a computer
    where it is true, a ``${NAME}`` declared for this field must have a value in its home's
    ``.env``; elsewhere the value may be absent. A field with nothing declared is not judged.
    """

    machine: str


@dataclass(frozen=True, slots=True)
class FieldRequirement:
    """One resolved ``RequiredWhen`` declaration: the field's document path and the machine flag's path."""

    path: tuple[str, ...]
    machine_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FieldConstraint:
    """One resolved declaration, ready for the schema, the model and the renderer.

    ``target_absent_holds[i]`` says whether the required value still holds when the
    target path's ``i``-th segment is absent from the document, so an absent field
    counts as its declared default.
    """

    requiring_path: tuple[str, ...]
    target_path: tuple[str, ...]
    value: object
    target_absent_holds: tuple[bool, ...]
    message: str


class FieldConstraintRefusal(ValueError):
    """A document breaks a declared field relationship; its text is the schema-owned message."""

    def __init__(self, constraint: FieldConstraint) -> None:
        super().__init__(constraint.message)
        self.constraint = constraint


@cache
def declared_constraints(model: type[ClosedModel]) -> tuple[FieldConstraint, ...]:
    """Collect and resolve every declaration reachable from a tier document's root.

    Raises ``TypeError`` for a declaration that cannot be expressed identically in the
    schema, in validation and at persistence.
    """
    constraints: list[FieldConstraint] = []
    _collect(model, model, (), constraints)
    return tuple(constraints)


def violated_constraints(
    model: type[ClosedModel], document: Mapping[str, object] | BaseModel
) -> tuple[FieldConstraint, ...]:
    """Return the declarations the document breaks, an absent field counting as its default."""
    return tuple(
        constraint
        for constraint in declared_constraints(model)
        if _value_at(model, document, constraint.requiring_path) is True
        and _value_at(model, document, constraint.target_path) != constraint.value
    )


def refuse_violations(model: type[ClosedModel], instance: BaseModel) -> None:
    """Raise a located validation error, one line per broken declaration, at the requiring field."""
    violations = violated_constraints(model, instance)
    if violations:
        raise ValidationError.from_exception_data(
            model.__name__,
            [
                InitErrorDetails(
                    # The declared message is a runtime string, which the LiteralString parameter cannot express.
                    type=PydanticCustomError(_VIOLATION_CODE, violation.message),  # pyright: ignore[reportArgumentType]
                    loc=violation.requiring_path,
                    input=_REFUSED_INPUT,
                )
                for violation in violations
            ],
        )


@cache
def declared_requirements(model: type[ClosedModel]) -> tuple[FieldRequirement, ...]:
    """Collect every ``RequiredWhen`` declaration reachable from a tier document's root."""
    requirements: list[FieldRequirement] = []
    _collect_requirements(model, (), requirements)
    return tuple(requirements)


def refuse_unmet_requirements(model: type[ClosedModel], context: object) -> None:
    """Refuse declared values this computer needs but cannot resolve, one located line per field.

    Judged only when the validation carries this computer's machine configuration; a validation of a
    document whose references were not resolved here has nothing to judge.
    """
    if not isinstance(context, Mapping) or MACHINE_CONTEXT_KEY not in context:
        return
    machine = context[MACHINE_CONTEXT_KEY]
    unresolved = context.get(UNRESOLVED_CONTEXT_KEY)
    if not isinstance(unresolved, Mapping):
        return
    details: list[InitErrorDetails] = []
    for requirement in declared_requirements(model):
        name = unresolved.get(requirement.path)
        if name is None or _machine_flag(machine, requirement) is not True:
            continue
        message = _REQUIREMENT_MESSAGE.format(
            field=_PATH_SEPARATOR.join(requirement.path),
            flag=_PATH_SEPARATOR.join(requirement.machine_path),
            name=name,
        )
        details.append(
            InitErrorDetails(
                # The message is a runtime string, which the LiteralString parameter cannot express.
                type=PydanticCustomError(_REQUIREMENT_CODE, message),  # pyright: ignore[reportArgumentType]
                loc=requirement.path,
                input=_REFUSED_INPUT,
            )
        )
    if details:
        raise ValidationError.from_exception_data(model.__name__, details)


def refuses_only_unmet_requirements(error: ValidationError) -> bool:
    """Whether a validation failed only on values this computer's role needs, so the document itself is valid.

    Requirements are judged after the document validates, so such a failure carries no other finding.
    """
    return all(detail["type"] == _REQUIREMENT_CODE for detail in error.errors(include_input=False))


def refuse_document(model: type[ClosedModel], document: Mapping[str, object]) -> None:
    """Raise ``FieldConstraintRefusal`` for the first declaration a document to be persisted breaks."""
    violations = violated_constraints(model, document)
    if violations:
        raise FieldConstraintRefusal(violations[0])


def append_constraint_rules(schema: dict[str, Any], model: type[BaseModel]) -> None:  # guard: loose-dict - JSON schema
    """Append each declaration to the root schema as a conditional rule that flags the requiring field."""
    if not issubclass(model, ClosedModel):
        return
    rules = [_schema_rule(constraint) for constraint in declared_constraints(model)]
    if rules:
        schema.setdefault(SchemaKeyword.ALL_OF, []).extend(rules)


def _schema_rule(constraint: FieldConstraint) -> SchemaFragment:
    """If the target does not hold the required value, the requiring field must be false, with the message."""
    return {
        SchemaKeyword.IF: {SchemaKeyword.NOT: _target_satisfied(constraint)},
        SchemaKeyword.THEN: _nested_properties(
            constraint.requiring_path,
            {SchemaKeyword.CONST: False, SchemaKeyword.ERROR_MESSAGE: constraint.message},
        ),
    }


def _target_satisfied(constraint: FieldConstraint) -> SchemaFragment:
    """The schema a document meets when the target holds the value, or is absent and defaults to it."""
    schema: SchemaFragment = {SchemaKeyword.CONST: constraint.value}
    for name, absent_holds in zip(
        reversed(constraint.target_path), reversed(constraint.target_absent_holds), strict=True
    ):
        level: SchemaFragment = {SchemaKeyword.PROPERTIES: {name: schema}}
        if not absent_holds:
            level[SchemaKeyword.REQUIRED] = [name]
        schema = level
    return schema


def _nested_properties(path: tuple[str, ...], leaf: SchemaFragment) -> SchemaFragment:
    schema = leaf
    for name in reversed(path):
        wrapped: SchemaFragment = {SchemaKeyword.PROPERTIES: {name: schema}}
        schema = wrapped
    return schema


def _collect(
    root: type[ClosedModel], current: type[ClosedModel], prefix: tuple[str, ...], found: list[FieldConstraint]
) -> None:
    for name, field in current.model_fields.items():
        path = (*prefix, name)
        found.extend(_resolve(root, path, field, marker) for marker in field.metadata if isinstance(marker, Requires))
        nested = nested_model(field.annotation)
        if nested is not None:
            _collect(root, nested, path, found)
            continue
        for member in _container_members(field.annotation):
            if _carries_declaration(member, set()):
                raise TypeError(_CONTAINER_MEMBER.format(path=_PATH_SEPARATOR.join(path)))


def _resolve(root: type[ClosedModel], path: tuple[str, ...], field: FieldInfo, marker: Requires) -> FieldConstraint:
    dotted_path = _PATH_SEPARATOR.join(path)
    if field.annotation is not bool:
        raise TypeError(_NOT_BOOLEAN.format(path=dotted_path))
    if field.get_default(call_default_factory=True) is True:
        raise TypeError(_DEFAULTS_TO_TRUE.format(path=dotted_path))
    target_path = tuple(marker.target.split(_PATH_SEPARATOR))
    levels, target_field = _walk_target(root, target_path)
    if levels is None or target_field is None:
        raise TypeError(_UNRESOLVED_TARGET.format(path=dotted_path, target=marker.target))
    try:
        TypeAdapter(target_field.annotation).validate_python(marker.value, strict=True)
    except ValidationError as error:
        raise TypeError(_VALUE_REJECTED.format(path=dotted_path, target=marker.target)) from error
    return FieldConstraint(
        requiring_path=path,
        target_path=target_path,
        value=marker.value,
        target_absent_holds=tuple(
            _value_at(level, {}, target_path[index:]) == marker.value for index, level in enumerate(levels)
        ),
        message=_MESSAGE.format(
            requiring=dotted_path,
            target=marker.target,
            value=json.dumps(marker.value),
        ),
    )


def _collect_requirements(current: type[ClosedModel], prefix: tuple[str, ...], found: list[FieldRequirement]) -> None:
    for name, field in current.model_fields.items():
        path = (*prefix, name)
        found.extend(
            FieldRequirement(path=path, machine_path=tuple(marker.machine.split(_PATH_SEPARATOR)))
            for marker in field.metadata
            if isinstance(marker, RequiredWhen)
        )
        nested = nested_model(field.annotation)
        if nested is not None:
            _collect_requirements(nested, path, found)


def _machine_flag(machine: object, requirement: FieldRequirement) -> object:
    current = machine
    for name in requirement.machine_path:
        try:
            current = getattr(current, name)
        except AttributeError as error:
            raise TypeError(
                _UNKNOWN_MACHINE_FLAG.format(
                    field=_PATH_SEPARATOR.join(requirement.path),
                    flag=_PATH_SEPARATOR.join(requirement.machine_path),
                )
            ) from error
    return current


def _walk_target(
    root: type[ClosedModel], target_path: tuple[str, ...]
) -> tuple[list[type[ClosedModel]] | None, FieldInfo | None]:
    """Return the model at each level of the target path and the target's field, or ``None`` when unresolved."""
    levels: list[type[ClosedModel]] = []
    current: type[ClosedModel] | None = root
    field: FieldInfo | None = None
    for name in target_path:
        if current is None or name not in current.model_fields:
            return None, None
        levels.append(current)
        field = current.model_fields[name]
        current = nested_model(field.annotation)
    return levels, field


def _value_at(model: type[ClosedModel], source: object, path: tuple[str, ...]) -> object:
    """The effective value at ``path``: absent keys take their declared default, an unreachable path none."""
    current_model: type[ClosedModel] | None = model
    current = source
    for name in path:
        if current_model is None:
            return _UNRESOLVED
        field = current_model.model_fields[name]
        current = _child(current, name, field)
        current_model = nested_model(field.annotation)
    return current


def _child(container: object, name: str, field: FieldInfo) -> object:
    if isinstance(container, BaseModel):
        return getattr(container, name)
    if isinstance(container, Mapping):
        if name in container:
            return container[name]
        return _UNRESOLVED if field.is_required() else field.get_default(call_default_factory=True)
    return _UNRESOLVED


def _container_members(annotation: Any) -> Iterator[type[ClosedModel]]:
    """Yield the closed models an annotation holds inside a list or mapping."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        for argument in get_args(annotation):
            yield from _container_members(argument)
    elif origin in (list, dict):
        for argument in get_args(annotation):
            yield from _models_within(argument)


def _models_within(annotation: Any) -> Iterator[type[ClosedModel]]:
    if isinstance(annotation, type) and issubclass(annotation, ClosedModel):
        yield annotation
        return
    for argument in get_args(annotation):
        yield from _models_within(argument)


def _carries_declaration(model: type[ClosedModel], visited: set[type[ClosedModel]]) -> bool:
    """Whether a model, or any model nested beneath it, declares a constraint."""
    if model in visited:
        return False
    visited.add(model)
    for field in model.model_fields.values():
        if any(isinstance(marker, (Requires, RequiredWhen)) for marker in field.metadata):
            return True
        nested = nested_model(field.annotation)
        members = [nested] if nested is not None else list(_container_members(field.annotation))
        if any(_carries_declaration(member, visited) for member in members):
            return True
    return False
