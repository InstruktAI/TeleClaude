"""Present home-repository activation results during installation."""

from __future__ import annotations

from teleclaude.core.reconciliation.home_activation import HomeActivationStatus, activate_home_repository

_ACTIVATED_MESSAGE = "TeleClaude home history activated"
_REFUSED_MESSAGE = "TeleClaude home history was not activated; these paths are outside the retained set:"
_BREACH_MESSAGE = "Existing history contains paths outside the retained set:"
_SUCCESS_EXIT_CODE = 0
_REFUSAL_EXIT_CODE = 1


def main() -> int:
    """Activate the home history and print the operator-facing outcome."""
    result = activate_home_repository()
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
