"""The one error a configuration document raises when it cannot be read or validated."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from teleclaude.config._environment import CompanyCredentialsError, MissingEnvironmentReferenceError

_LOCATION_SEPARATOR = "."
_FINDING = "{location}: {message}"
_YAML_FINDING = "line {line}, column {column}: {problem}"
_INVALID_YAML = "invalid YAML"
_FINDINGS_SEPARATOR = "; "
_DESCRIPTION = "Configuration {document} does not load: {findings}"
_NOT_READY_DESCRIPTION = "Configuration {document} is not ready on this computer: {findings}"
_UNNAMED_DOCUMENT = "document"


class ConfigLoadError(ValueError):
    """A configuration document could not be read or validated; the message names the file and the cause.

    The message may quote the document; ``describe_load_error`` is what is shown or sent anywhere else.
    """

    def __init__(self, message: str, *, document: Path | None = None) -> None:
        super().__init__(message)
        self.document = document


class ConfigNotReadyError(ConfigLoadError):
    """A document that loads lacks a value this computer's role needs; it is refused only as this computer's readiness."""


class InboundSecretDeclarationError(ValueError):
    """A declared inbound source does not declare its secret as a ``${NAME}`` reference; names, never values."""


# Causes whose text is written by the config context and names variables and paths, never values.
_SELF_DESCRIBING_CAUSES = (MissingEnvironmentReferenceError, CompanyCredentialsError, InboundSecretDeclarationError)


def load_error_findings(error: ConfigLoadError) -> list[str]:
    """Where and why a document fails, without any input value, so the findings may travel beyond this computer."""
    return cause_findings(error.__cause__ if error.__cause__ is not None else error)


def cause_findings(cause: BaseException) -> list[str]:
    """Where and why one read, parse or validation failure happened, without any input value.

    A validator's own message is passed through, so config validators name fields, keys and
    variables in their messages and never the value they rejected.
    """
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
    if isinstance(cause, _SELF_DESCRIBING_CAUSES):
        return [str(cause)]
    # Any other cause's text may quote the document; only its kind travels.
    return [type(cause).__name__]


def describe_load_error(error: ConfigLoadError) -> str:
    """One line naming the document and where it fails, safe to print or send: it quotes no document content."""
    document = str(error.document) if error.document is not None else _UNNAMED_DOCUMENT
    description = _NOT_READY_DESCRIPTION if isinstance(error, ConfigNotReadyError) else _DESCRIPTION
    return description.format(document=document, findings=_FINDINGS_SEPARATOR.join(load_error_findings(error)))
