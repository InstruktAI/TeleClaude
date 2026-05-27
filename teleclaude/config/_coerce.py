"""Strict scalar coercion for config values."""

from __future__ import annotations

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
    raise ValueError(f"Invalid boolean config value: {value!r} (expected true/false)")
