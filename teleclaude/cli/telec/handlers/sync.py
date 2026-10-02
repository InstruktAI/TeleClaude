"""Publish the invocation home's committed documentation and agent context."""

from __future__ import annotations

import sys
from pathlib import Path

from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._code_git_state import working_tree_snapshot
from teleclaude.cli.telec.surface import SYNC
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.paths import ConfigFileName
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.sync import (
    HomePublicationOutcome,
    PublicationMode,
    PublicationRunFailure,
    publish_homes,
)

__all__ = ["handle_sync"]

_SYNC_HOME_REQUIRED = "telec sync runs only from a directory holding its own teleclaude.yml: {directory}"
_SYNC_OWNING_CHECKOUT_UNAVAILABLE = "Could not resolve the owning checkout for {directory}: {error}"
_NO_OWNING_CHECKOUT = "no checkout owns this directory"
_SYNC_HOME_NOT_COMMITTED = "The invocation home is not present in the committed main tip: {directory}"
_SYNC_RUN_FAILED = "telec sync failed: {error}"
_SYNC_POSITIONALS_REFUSED = "telec sync accepts no positional arguments."
_UNCOMMITTED_HOME_NOTICE = "Uncommitted changes under the invocation home were not published."
_PUBLISHED_HOME_LINE = "{home}: published"
_UNCHANGED_HOME_LINE = "{home}: unchanged"
_SKIPPED_HOME_LINE = "{home}: skipped ({error})"
_FAILED_HOME_LINE = "{home}: failed ({error})"
_DIAGNOSTIC_ERROR_LINE = "  {cause}"
_FAILED_EXIT_CODE = 1
_USAGE_EXIT_CODE = 2
_OUTCOME_LINES = {
    HomePublicationOutcome.PUBLISHED: _PUBLISHED_HOME_LINE,
    HomePublicationOutcome.UNCHANGED: _UNCHANGED_HOME_LINE,
    HomePublicationOutcome.SKIPPED: _SKIPPED_HOME_LINE,
    HomePublicationOutcome.FAILED: _FAILED_HOME_LINE,
}


def handle_sync(args: list[str]) -> None:
    """Rebuild the directly declared invocation home and its nested homes."""
    parsed = parse_command_args(SYNC, args)
    if parsed.positionals:
        print(_SYNC_POSITIONALS_REFUSED, file=sys.stderr)
        raise SystemExit(_USAGE_EXIT_CODE)

    roots = resolve_invocation_roots()
    invocation_directory = roots.invocation_dir.expanduser().resolve()
    if not (invocation_directory / ConfigFileName.OVERLAY).is_file():
        print(_SYNC_HOME_REQUIRED.format(directory=invocation_directory), file=sys.stderr)
        raise SystemExit(_FAILED_EXIT_CODE)

    active_checkout = roots.repository_root.expanduser().resolve()
    checkout_error = _NO_OWNING_CHECKOUT
    try:
        canonical_root = resolve_owning_checkout(active_checkout)
    except (OSError, ValueError) as exc:
        canonical_root = None
        checkout_error = str(exc)
    if canonical_root is None:
        print(
            _SYNC_OWNING_CHECKOUT_UNAVAILABLE.format(directory=invocation_directory, error=checkout_error),
            file=sys.stderr,
        )
        raise SystemExit(_FAILED_EXIT_CODE)
    home_relative_path = invocation_directory.relative_to(active_checkout)

    dirty_paths = working_tree_snapshot(active_checkout).dirty
    if any(Path(path).is_relative_to(home_relative_path) for path in dirty_paths):
        print(_UNCOMMITTED_HOME_NOTICE)

    run = publish_homes(
        canonical_root,
        PublicationMode.REBUILD,
        directory=home_relative_path,
        required_home=home_relative_path,
    )
    if run.failure is PublicationRunFailure.HOME_NOT_COMMITTED:
        print(_SYNC_HOME_NOT_COMMITTED.format(directory=invocation_directory), file=sys.stderr)
        raise SystemExit(_FAILED_EXIT_CODE)
    if run.error is not None:
        print(_SYNC_RUN_FAILED.format(error=run.error), file=sys.stderr)
        raise SystemExit(_FAILED_EXIT_CODE)

    for result in run.homes:
        message = _OUTCOME_LINES[result.outcome]
        if result.outcome in (HomePublicationOutcome.SKIPPED, HomePublicationOutcome.FAILED):
            message = message.format(home=result.home.root.as_posix(), error=result.error)
        else:
            message = message.format(home=result.home.root.as_posix())
        print(message)
        if result.diagnostic_error is not None:
            print(_DIAGNOSTIC_ERROR_LINE.format(cause=result.diagnostic_error))
    if run.exit_code:
        raise SystemExit(_FAILED_EXIT_CODE)
