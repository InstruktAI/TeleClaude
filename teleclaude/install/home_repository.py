"""Present home-repository activation results during installation."""

from __future__ import annotations

from teleclaude.core.reconciliation.home_activation import (
    HomeActivationResult,
    HomeActivationStatus,
    activate_home_repository,
)
from teleclaude.core.reconciliation.template_installation import HomeTemplateMaterializationConflict

_ACTIVATED_MESSAGE = "TeleClaude home history activated"
_REFUSED_MESSAGE = "TeleClaude home history was not activated; these paths are outside the retained set:"
_GATE_REFUSED_MESSAGE = (
    "TeleClaude home history was not activated because the commit gate was unavailable or refused the record:"
)
_BREACH_MESSAGE = "Existing history contains paths outside the retained set:"
_HELD_MESSAGE = "Template targets were held because of unrecorded changes:"
_HELD_REMEDY_MESSAGE = "Record or discard each change, then rerun install."
_UNRESTORED_MESSAGE = "Activation-written files changed before restoration and were left untouched:"
_SUCCESS_EXIT_CODE = 0
_REFUSAL_EXIT_CODE = 0
_MATERIALIZATION_CONFLICT_EXIT_CODE = 2


def main() -> int:
    """Activate the home history and print the operator-facing outcome."""
    try:
        result = activate_home_repository()
    except HomeTemplateMaterializationConflict as error:
        print(error)
        return _MATERIALIZATION_CONFLICT_EXIT_CODE
    if result.status is HomeActivationStatus.GATE_REFUSED:
        print(_GATE_REFUSED_MESSAGE)
        for finding in result.gate_findings:
            print(finding)
        _print_activation_paths(result)
        return _REFUSAL_EXIT_CODE
    if result.status is HomeActivationStatus.REFUSED:
        print(_REFUSED_MESSAGE)
        for path in result.refused_paths:
            print(path.as_posix())
        _print_activation_paths(result)
        return _REFUSAL_EXIT_CODE
    print(_ACTIVATED_MESSAGE)
    _print_activation_paths(result)
    if result.breach_paths:
        print(_BREACH_MESSAGE)
        for path in result.breach_paths:
            print(path.as_posix())
    return _SUCCESS_EXIT_CODE


def _print_activation_paths(result: HomeActivationResult) -> None:
    if result.held_paths:
        print(_HELD_MESSAGE)
        for path in result.held_paths:
            print(path.as_posix())
        print(_HELD_REMEDY_MESSAGE)
    if result.unrestored_paths:
        print(_UNRESTORED_MESSAGE)
        for path in result.unrestored_paths:
            print(path.as_posix())
