"""The one error a configuration document raises when it cannot be read or validated."""

from __future__ import annotations

import yaml
from pydantic import ValidationError

_LOCATION_SEPARATOR = "."
_FINDING = "{location}: {message}"
_YAML_FINDING = "line {line}, column {column}: {problem}"
_INVALID_YAML = "invalid YAML"


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
    if isinstance(cause, yaml.MarkedYAMLError) and cause.problem_mark is not None:
        mark = cause.problem_mark
        return [
            _YAML_FINDING.format(line=mark.line + 1, column=mark.column + 1, problem=cause.problem or _INVALID_YAML)
        ]
    if isinstance(cause, yaml.YAMLError):
        return [_INVALID_YAML]
    # Any other cause's text may quote the document; only its kind travels.
    return [type(cause if cause is not None else error).__name__]
