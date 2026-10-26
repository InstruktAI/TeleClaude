"""Strict scalar coercion for config values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, cast

from pydantic import BeforeValidator

_SCALAR_ERROR = "Expected a scalar configuration value."
_TRUE_TOKENS = frozenset({"true", "yes", "1", "on"})
_FALSE_TOKENS = frozenset({"false", "no", "0", "off", ""})


def as_bool(value: object, *, default: bool = False) -> bool:
    """Parse a config flag strictly into a bool.

    Real bools pass through. Strings are matched case-insensitively against the
    canonical true/false tokens — so a stringified ``"False"`` (which a YAML
    writer can emit) maps to ``False`` instead of ``bool("False") == True``.
    ``None`` falls back to ``default``; anything else raises so corruption is
    loud at config load rather than silently mis-enabling a feature.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    raise ValueError("Invalid boolean config value (expected true/false)")


def declares_true(value: object) -> bool:
    """Whether a raw config value reads as true, treating anything unparseable as not true."""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in _TRUE_TOKENS


def _require_scalar(value: object) -> object:
    """Reject containers before a scalar coercion rule runs."""
    if isinstance(value, (Mapping, list)):
        raise ValueError(_SCALAR_ERROR)
    return value


def _flag(value: object) -> bool:
    """Apply the shared FLAG rule to a scalar value."""
    return as_bool(_require_scalar(value))


def _optional_text(value: object) -> str | None:
    """Strip optional text and map empty results to None."""
    scalar = _require_scalar(value)
    if scalar is None:
        return None
    return str(scalar).strip() or None


def _truthy_text(value: object) -> str | None:
    """Convert truthy scalar values to text without stripping."""
    scalar = _require_scalar(value)
    return str(scalar) if scalar else None


def _text(value: object) -> str:
    """Convert one scalar configuration value to text."""
    return str(_require_scalar(value))


def _optional_int_lenient(value: object) -> int | None:
    """Keep the historical optional integer conversion and silent rejection."""
    scalar = _require_scalar(value)
    if scalar is None:
        return None
    if isinstance(scalar, int):
        return scalar
    if isinstance(scalar, str) and scalar.isdigit():
        return int(scalar)
    return None


def _int_strict(value: object) -> int:
    """Convert integers and integer strings while rejecting booleans."""
    scalar = _require_scalar(value)
    if isinstance(scalar, bool):
        raise ValueError(str(scalar))
    if isinstance(scalar, int):
        return scalar
    if isinstance(scalar, str):
        return int(scalar)
    raise ValueError(str(scalar))


def _optional_int_strict(value: object) -> int | None:
    """Keep None and apply the strict integer rule to any other value."""
    if value is None:
        return None
    return _int_strict(value)


def _float_strict(value: object) -> float:
    """Convert numeric scalars to float while rejecting booleans."""
    scalar = _require_scalar(value)
    if isinstance(scalar, bool):
        raise ValueError(str(scalar))
    if isinstance(scalar, (int, float, str)):
        return float(scalar)
    raise ValueError(str(scalar))


def _int_lenient(value: object) -> int:
    """Use Python's integer conversion, including boolean and float inputs."""
    scalar = cast(int | float | str | bytes | bytearray, _require_scalar(value))
    return int(scalar)


FLAG = Annotated[bool, BeforeValidator(_flag)]
OPT_TEXT = Annotated[str | None, BeforeValidator(_optional_text)]
TRUTHY_TEXT = Annotated[str | None, BeforeValidator(_truthy_text)]
TEXT = Annotated[str, BeforeValidator(_text)]
OPT_INT_LENIENT = Annotated[bool | int | None, BeforeValidator(_optional_int_lenient)]
INT_STRICT = Annotated[int, BeforeValidator(_int_strict)]
OPT_INT_STRICT = Annotated[int | None, BeforeValidator(_optional_int_strict)]
FLOAT_STRICT = Annotated[float, BeforeValidator(_float_strict)]
INT_LENIENT = Annotated[int, BeforeValidator(_int_lenient)]
SCALAR_INPUT = Annotated[object, BeforeValidator(_require_scalar)]
