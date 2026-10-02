"""Start a TeleClaude checkout's own guardrail lane, refusing a foreign one.

The graded checkout's ``teleclaude`` package is selected by placing its root
first on this process's ``PYTHONPATH`` (ahead of the editable-install
finder). This entry confirms that the ``teleclaude`` package it imported
actually lives under ``--root`` before running anything, then runs exactly
the guardrail lane over the given targets: no native leg, no capability
check, no workspace scoping.
"""

from __future__ import annotations

import sys
from inspect import signature
from pathlib import Path

from instrukt_ai_logging import get_logger

import teleclaude
from teleclaude.logging_config import setup_logging
from teleclaude.quality.lint import LintRunner
from teleclaude.quality.selection import QualityCheckFamily
from teleclaude.session_identity import get_session_id

# Not `__name__`: run as a script, that is "__main__", a logger `configure_logging`
# below never elevates above root's third-party WARNING floor (it only elevates the
# "teleclaude" prefix), so an INFO record from it would be silently dropped.
_LOGGER_NAME = "teleclaude.quality.checkout_guardrails"
logger = get_logger(_LOGGER_NAME)

_ROOT_FLAG = "--root"
_CONTENT_ROOT_FLAG = "--content-root"
_PLATFORM_HOME_SUBJECT_FLAG = "--platform-home-subject"
_FAMILY_FLAG = "--family"
_FULL_RUN_FLAG = "--full-run"
_ALL_FLAG = "--all"
_USAGE = (
    "usage: checkout_guardrails.py --root <path> [--content-root <path>] "
    "[--platform-home-subject] (--all | <file> [<file> ...])"
)
_TELECLAUDE_PACKAGE_NAME = "teleclaude"
_TELECLAUDE_PACKAGE_INIT = "__init__.py"
_USAGE_EXIT_CODE = 2
_FOREIGN_CHECKOUT_EXIT_CODE = 1
_FOREIGN_CHECKOUT_MESSAGE = "ERROR: loaded {package_name} from {loaded}, expected it under {root}"
_SUCCESS_EXIT_CODE = 0
_DEFAULT_FAILURE_EXIT_CODE = 1
_CONTENT_ROOT_PARAMETER = "content_root"
_PLATFORM_HOME_SUBJECT_PARAMETER = "platform_home_subject"
_OPTION_PREFIX = "-"
_CONTENT_ROOT_UNSUPPORTED = (
    "ERROR: checkout {root} cannot grade staged content with its own guardrails; "
    "reconcile the worktree with origin/main and retry."
)

# This checkout's own grading, run standalone: it never imports the graded checkout's
# `teleclaude.quality.gate`/`checkout_grading` (a pre-delivery checkout carries neither),
# so its runner/reason vocabulary is restated locally rather than imported. Both name the
# same facts `checkout_grading.CheckoutGradingRunner.INSTALLED` and
# `CheckoutGradingReason.INSTALLATION` carry, because from this process's own point of
# view — the graded checkout's code, already confirmed loaded — grading its own root is
# exactly what "installed" means.
_GRADING_EVENT = "quality_gate_checkout_grading"
_RUNNER_INSTALLED = "installed"
_REASON_INSTALLATION = "installation"
_GUARDRAILS_LEG = "guardrails"


def _parse_args(
    argv: list[str],
) -> tuple[Path, list[str] | None, Path | None, bool, frozenset[QualityCheckFamily], bool]:
    """Parse ``--root <path>`` followed by explicit targets or ``--all``."""
    if len(argv) < 2 or argv[0] != _ROOT_FLAG:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)
    root = Path(argv[1])
    rest = argv[2:]
    content_root: Path | None = None
    platform_home_subject = False
    check_families: set[QualityCheckFamily] = set()
    full_run = False
    targets: list[str] = []
    index = 0
    while index < len(rest):
        argument = rest[index]
        if argument == _CONTENT_ROOT_FLAG and index + 1 < len(rest):
            content_root = Path(rest[index + 1])
            index += 2
        elif argument == _PLATFORM_HOME_SUBJECT_FLAG:
            platform_home_subject = True
            index += 1
        elif argument == _FAMILY_FLAG and index + 1 < len(rest):
            try:
                check_families.add(QualityCheckFamily(rest[index + 1]))
            except ValueError:
                print(_USAGE, file=sys.stderr)
                raise SystemExit(_USAGE_EXIT_CODE) from None
            index += 2
        elif argument == _FULL_RUN_FLAG:
            full_run = True
            index += 1
        else:
            targets.append(argument)
            index += 1
    if not targets:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)
    if targets == [_ALL_FLAG]:
        return root, None, content_root, platform_home_subject, frozenset(check_families), True
    if any(target == _ALL_FLAG or target.startswith(_OPTION_PREFIX) for target in targets):
        print(_USAGE, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)
    return root, targets, content_root, platform_home_subject, frozenset(check_families), full_run


def _confirm_checkout_loaded(root: Path) -> None:
    """Refuse to run unless the imported ``teleclaude`` package lives under ``root``."""
    loaded_init = Path(teleclaude.__file__).resolve()
    expected_init = (root / _TELECLAUDE_PACKAGE_NAME / _TELECLAUDE_PACKAGE_INIT).resolve()
    if loaded_init != expected_init:
        print(
            _FOREIGN_CHECKOUT_MESSAGE.format(package_name=_TELECLAUDE_PACKAGE_NAME, loaded=loaded_init, root=root),
            file=sys.stderr,
        )
        raise SystemExit(_FOREIGN_CHECKOUT_EXIT_CODE)


def _log_checkout_grading(root: Path, exit_code: int) -> None:
    """Emit this checkout's own grading record, the child UC-CCS5 promises."""
    logger.info(
        _GRADING_EVENT,
        execution_root=str(root),
        code_root=str(root),
        runner=_RUNNER_INSTALLED,
        reason=_REASON_INSTALLATION,
        selection=[_GUARDRAILS_LEG],
        exit_code=exit_code,
        session_id=get_session_id(),
    )


def _confirm_content_root_supported(root: Path) -> None:
    """Refuse staged grading when this checkout's LintRunner lacks its interface."""
    parameters = signature(LintRunner.__init__).parameters
    required = {_CONTENT_ROOT_PARAMETER, _PLATFORM_HOME_SUBJECT_PARAMETER}
    if not required.issubset(parameters):
        print(_CONTENT_ROOT_UNSUPPORTED.format(root=root), file=sys.stderr)
        raise SystemExit(_FOREIGN_CHECKOUT_EXIT_CODE)


def main(argv: list[str] | None = None) -> None:
    """Run the loaded checkout's guardrail lane over the parsed targets."""
    root, targets, content_root, platform_home_subject, check_families, full_run = _parse_args(
        list(sys.argv[1:] if argv is None else argv)
    )
    resolved_root = root.resolve()
    _confirm_checkout_loaded(resolved_root)
    if content_root is not None:
        _confirm_content_root_supported(resolved_root)
    # A standalone entry, not started through `teleclaude.cli.telec`'s own startup:
    # nothing has attached a handler to this process's loggers yet, so the grading
    # record below would otherwise emit into a void (sdlc/policy/python/logging).
    setup_logging()
    exit_code = _SUCCESS_EXIT_CODE
    try:
        LintRunner(
            project_root=resolved_root,
            content_root=content_root,
            platform_home_subject=platform_home_subject,
            check_families=check_families or frozenset(QualityCheckFamily),
        ).run(files=targets, run_all=full_run or targets is None)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else _DEFAULT_FAILURE_EXIT_CODE
    _log_checkout_grading(resolved_root, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
