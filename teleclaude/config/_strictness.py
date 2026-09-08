"""Structural validation for machine configuration input.

The runtime configuration is assembled by several small parsers rather than a
single model.  This module gives those parsers a shared way to describe the
raw shapes they consume, so unknown keys fail before defaults or transforms can
hide them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True)
class ClosedMapping:
    """A mapping with an explicit, closed set of keys."""

    fields: Mapping[str, InputShape]


@dataclass(frozen=True)
class NamedMapping:
    """A mapping whose names are dynamic but whose values share one shape."""

    value: InputShape


@dataclass(frozen=True)
class InputList:
    """A list whose members share one shape."""

    item: InputShape


@dataclass(frozen=True)
class Scalar:
    """A scalar leaf consumed directly by a parser."""


@dataclass(frozen=True)
class Open:
    """An intentionally opaque parser-owned input leaf."""


type InputShape = ClosedMapping | NamedMapping | InputList | Scalar | Open
SCALAR: Final = Scalar()
OPEN: Final = Open()


class MachineConfigInputError(ValueError):
    """A raw machine-config shape does not match its parser declarations."""


def validate_machine_input(value: object, shape: InputShape, source: Path) -> None:
    """Reject unknown paths and incompatible containers in ``source``.

    This is intentionally structural: parser-owned conversion and semantic
    validation happen afterwards in their existing owners.
    """
    problems: list[str] = []
    _validate(value, shape, "", problems)
    if problems:
        rendered = "; ".join(sorted(problems))
        raise MachineConfigInputError(f"Invalid configuration input in {source}: {rendered}")


def _validate(value: object, shape: InputShape, path: str, problems: list[str]) -> None:
    display_path = path or "root"
    if value is None and path:
        return
    if isinstance(shape, Open):
        return
    if isinstance(shape, Scalar):
        if isinstance(value, (dict, list)):
            problems.append(f"{display_path}: expected a scalar")
        return
    if isinstance(shape, InputList):
        if not isinstance(value, list):
            problems.append(f"{display_path}: expected a list")
            return
        for index, item in enumerate(value):
            _validate(item, shape.item, f"{path}[{index}]", problems)
        return
    if not isinstance(value, dict):
        problems.append(f"{display_path}: expected a mapping")
        return
    if isinstance(shape, NamedMapping):
        for key in sorted(value, key=str):
            _validate(value[key], shape.value, _child_path(path, str(key)), problems)
        return
    for key in sorted(value, key=str):
        key_text = str(key)
        child_path = _child_path(path, key_text)
        child_shape = shape.fields.get(key_text)
        if child_shape is None:
            problems.append(f"unknown key `{child_path}`")
            continue
        _validate(value[key], child_shape, child_path, problems)


def _child_path(parent: str, child: str) -> str:
    """Return a dotted path while preserving list indexes in the parent."""
    return child if not parent else f"{parent}.{child}"
