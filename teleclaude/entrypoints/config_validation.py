"""Validate every configuration document for installation.

Installation runs as the machine owner, who already holds every file this
reads, so it validates through this module rather than the caller-gated CLI.
"""

from __future__ import annotations

from teleclaude.cli.config_handlers import validate_all

_VALIDATION_AREA_LINE = "  {icon} {area}"
_VALIDATION_ERROR_LINE = "    Error: {message}"
_VALIDATION_FIX_LINE = "    Fix: {message}"
_VALIDATION_NOTE_LINE = "    Note: {message}"
_VALIDATION_PASSED_ICON = "✓"
_VALIDATION_FAILED_ICON = "✗"


def main() -> None:
    """Report each configuration area and exit non-zero when any fails."""
    results = validate_all()
    for result in results:
        icon = _VALIDATION_PASSED_ICON if result.passed else _VALIDATION_FAILED_ICON
        print(_VALIDATION_AREA_LINE.format(icon=icon, area=result.area))
        for error in result.errors:
            print(_VALIDATION_ERROR_LINE.format(message=error))
        for suggestion in result.suggestions:
            print(_VALIDATION_FIX_LINE.format(message=suggestion))
        for note in result.notes:
            print(_VALIDATION_NOTE_LINE.format(message=note))
    if not all(result.passed for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
