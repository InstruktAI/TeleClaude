"""Present home-repository activation results during installation."""

from __future__ import annotations

from teleclaude.core.reconciliation.home_activation import HomeActivationStatus, activate_home_repository
from teleclaude.core.reconciliation.template_installation import HomeTemplateMaterializationConflict

_ACTIVATED_MESSAGE = "TeleClaude home history activated"
_REFUSED_MESSAGE = "TeleClaude home history was not activated; these paths are outside the retained set:"
_BREACH_MESSAGE = "Existing history contains paths outside the retained set:"
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
    if result.status is HomeActivationStatus.REFUSED:
        print(_REFUSED_MESSAGE)
        for path in result.refused_paths:
            print(path.as_posix())
        return _REFUSAL_EXIT_CODE
    print(_ACTIVATED_MESSAGE)
    if result.breach_paths:
        print(_BREACH_MESSAGE)
        for path in result.breach_paths:
            print(path.as_posix())
    return _SUCCESS_EXIT_CODE
