"""Run the supported maintenance effects for an associated development checkout."""

from __future__ import annotations

import argparse
import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.config.checkout_association import CheckoutPurpose, checkout_association_for
from teleclaude.core.blueprint.maintenance import run_blueprint_maintenance
from teleclaude.core.integration.development_maintenance_contract import (
    DEVELOPMENT_MAINTENANCE_ACTION_ID,
    DEVELOPMENT_MAINTENANCE_AFTER_SHA_OPTION,
    DEVELOPMENT_MAINTENANCE_BEFORE_SHA_OPTION,
    DEVELOPMENT_MAINTENANCE_ROOT_OPTION,
)
from teleclaude.core.integration.post_commit_maintenance import (
    activation_range_action_paths,
)
from teleclaude.core.next_machine.worktrees import ensure_development_dependencies
from teleclaude.paths import PROJECTS_MANIFEST_PATH, TELECLAUDE_SOURCE_HOME
from teleclaude.sync import PublicationMode, publish_homes

logger = get_logger(__name__)

_LOCK_PATH = Path(".teleclaude/development-maintenance.lock")
_LOCK_APPEND_MODE = "a"
_UTF8_ENCODING = "utf-8"
_CURRENT_DIRECTORY = Path(".")
_PUBLICATION_FAILURE = "development authoring publication failed"
_DEVELOPMENT_MAINTENANCE_COMPLETED_EVENT = "development_maintenance_completed"
_INVALID_TARGET = "development maintenance requires a registered development checkout"
_ACTION_FAILED = "development maintenance range is not eligible"


@contextmanager
def _development_operation_lock(root: Path) -> Iterator[None]:
    """Serialize development effects without entering the installed daemon drain."""
    lock_path = root / _LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_LOCK_APPEND_MODE, encoding=_UTF8_ENCODING) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_development_maintenance(
    project_root: Path,
    activation_range: ActivationRange | None,
) -> int:
    """Prepare dependencies, publish authoring context, and refresh the target Blueprint."""
    root = project_root.expanduser().resolve()
    association = checkout_association_for(root, TELECLAUDE_SOURCE_HOME / PROJECTS_MANIFEST_PATH.name)
    if association is None or association.purpose is not CheckoutPurpose.DEVELOPMENT:
        raise ValueError(_INVALID_TARGET)

    if activation_range is None:
        changed_paths = None
        trigger_revision = None
        publication_mode = PublicationMode.REBUILD
    else:
        changed_paths = activation_range_action_paths(root, activation_range, DEVELOPMENT_MAINTENANCE_ACTION_ID)
        if changed_paths is None:
            raise ValueError(_ACTION_FAILED)
        trigger_revision = activation_range.after_sha
        publication_mode = PublicationMode.OWED

    with _development_operation_lock(root):
        ensure_development_dependencies(root)
        publication = publish_homes(root, publication_mode, directory=_CURRENT_DIRECTORY)
        if publication.exit_code:
            raise RuntimeError(publication.error or _PUBLICATION_FAILURE)
        run_blueprint_maintenance(root, trigger_revision=trigger_revision)
    logger.info(
        _DEVELOPMENT_MAINTENANCE_COMPLETED_EVENT,
        project_root=str(root),
        before_sha=activation_range.before_sha if activation_range is not None else None,
        after_sha=activation_range.after_sha if activation_range is not None else None,
        changed_paths=changed_paths,
    )
    return 0


def main() -> int:
    """Execute one explicitly targeted development maintenance activation."""
    parser = argparse.ArgumentParser()
    parser.add_argument(DEVELOPMENT_MAINTENANCE_ROOT_OPTION, type=Path, required=True)
    parser.add_argument(DEVELOPMENT_MAINTENANCE_AFTER_SHA_OPTION, required=True)
    parser.add_argument(DEVELOPMENT_MAINTENANCE_BEFORE_SHA_OPTION)
    args = parser.parse_args()
    return run_development_maintenance(
        args.root,
        ActivationRange(before_sha=args.before_sha, after_sha=args.after_sha) if args.after_sha else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
