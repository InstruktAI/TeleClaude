"""Validation for identifiers interpolated into remote shell commands."""

from __future__ import annotations

import re

_SHELL_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")


def require_shell_safe_identifier(value: object, field_name: str) -> str:
    """Return a safe shell identifier or raise for boundary-invalid input."""
    if not isinstance(value, str) or not value or not _SHELL_SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must match {_SHELL_SAFE_IDENTIFIER.pattern}")
    return value


def optional_shell_safe_identifier(value: object, field_name: str) -> str | None:
    """Validate an optional shell identifier."""
    if value is None or value == "":
        return None
    return require_shell_safe_identifier(value, field_name)
