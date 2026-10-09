"""The one error a configuration document raises when it cannot be read or validated."""

from __future__ import annotations

from pydantic import ValidationError

_LOCATION_SEPARATOR = "."
_FINDING = "{location}: {message}"


class ConfigLoadError(ValueError):
    """A configuration document could not be read or validated; the message names the file and the cause."""


def load_error_findings(error: ConfigLoadError) -> list[str]:
    """Where and why a document fails, without any input value, so the findings may travel beyond this computer."""
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        return [
            _FINDING.format(
                location=_LOCATION_SEPARATOR.join(str(part) for part in detail["loc"]), message=detail["msg"]
            )
            for detail in cause.errors(include_input=False, include_url=False)
        ]
    return [str(cause if cause is not None else error)]
