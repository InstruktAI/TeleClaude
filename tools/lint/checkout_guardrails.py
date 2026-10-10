"""Run one grading operation with a TeleClaude checkout's own code, refusing a foreign one.

The graded checkout's ``teleclaude`` package is selected by placing its root
first on this process's ``PYTHONPATH`` (ahead of the editable-install
finder). This entry confirms that the ``teleclaude`` package it imported
actually lives under ``--root`` before running the selected operation.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from inspect import signature
from pathlib import Path

from instrukt_ai_logging import get_logger

import teleclaude
import teleclaude.config.loader as config_loader
from teleclaude.git_tree import TreeSource, read_tree_path
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ConfigFileName
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
_OPERATION_FLAG = "--operation"
_OPTION_TERMINATOR = "--"
_ALL_FLAG = "--all"
_PARENT_PATH_COMPONENT = ".."
_DECLARATION_FILE_NAME = ConfigFileName.OVERLAY.value
_USAGE = (
    "usage: checkout_guardrails.py --root <path> [--operation <guardrails|staged-declarations>] "
    "[--content-root <path>] "
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


class CheckoutGradingOperation(StrEnum):
    """Closed set of operations this installed entry can perform."""

    GUARDRAILS = "guardrails"
    STAGED_DECLARATIONS = "staged-declarations"


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
) -> tuple[
    CheckoutGradingOperation,
    Path,
    list[str] | None,
    Path | None,
    bool,
    frozenset[QualityCheckFamily],
    bool,
]:
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
    operation = CheckoutGradingOperation.GUARDRAILS
    operation_seen = False
    option_terminator_seen = False
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
        elif argument == _OPERATION_FLAG:
            if operation_seen or index + 1 >= len(rest):
                print(_USAGE, file=sys.stderr)
                raise SystemExit(_USAGE_EXIT_CODE)
            try:
                operation = CheckoutGradingOperation(rest[index + 1])
            except ValueError:
                print(_USAGE, file=sys.stderr)
                raise SystemExit(_USAGE_EXIT_CODE) from None
            operation_seen = True
            index += 2
        elif argument == _OPTION_TERMINATOR:
            option_terminator_seen = True
            targets.extend(rest[index + 1 :])
            break
        else:
            targets.append(argument)
            index += 1
    if not targets:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)
    if targets == [_ALL_FLAG]:
        if operation is CheckoutGradingOperation.STAGED_DECLARATIONS:
            print(_USAGE, file=sys.stderr)
            raise SystemExit(_USAGE_EXIT_CODE)
        return operation, root, None, content_root, platform_home_subject, frozenset(check_families), True
    if operation is CheckoutGradingOperation.STAGED_DECLARATIONS and (
        content_root is not None or platform_home_subject or check_families or full_run
    ):
        print(_USAGE, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)
    if not option_terminator_seen and any(
        target == _ALL_FLAG or target.startswith(_OPTION_PREFIX) for target in targets
    ):
        print(_USAGE, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)
    return operation, root, targets, content_root, platform_home_subject, frozenset(check_families), full_run


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


def _run_staged_declaration_validation(root: Path, targets: list[str]) -> int:
    """Validate only the supplied staged declarations with this checkout's config owner."""
    source = TreeSource.active_index(root)
    findings: list[str] = []
    for target in targets:
        relative_path = Path(target)
        if (
            relative_path.is_absolute()
            or _PARENT_PATH_COMPONENT in relative_path.parts
            or relative_path.name != _DECLARATION_FILE_NAME
        ):
            print(_USAGE, file=sys.stderr)
            raise SystemExit(_USAGE_EXIT_CODE)
        content = read_tree_path(source, target)
        findings.extend(config_loader.validate_staged_declaration(root / relative_path, content))
    if not findings:
        return _SUCCESS_EXIT_CODE
    for finding in findings:
        print(finding, file=sys.stderr)
    return _DEFAULT_FAILURE_EXIT_CODE


def main(argv: list[str] | None = None) -> None:
    """Run the loaded checkout's guardrail or staged-declaration operation."""
    operation, root, targets, content_root, platform_home_subject, check_families, full_run = _parse_args(
        list(sys.argv[1:] if argv is None else argv)
    )
    resolved_root = root.resolve()
    _confirm_checkout_loaded(resolved_root)
    if operation is CheckoutGradingOperation.STAGED_DECLARATIONS:
        if targets is None:
            print(_USAGE, file=sys.stderr)
            raise SystemExit(_USAGE_EXIT_CODE)
        setup_logging()
        sys.exit(_run_staged_declaration_validation(resolved_root, targets))
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
