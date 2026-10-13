"""Execute Blueprint refresh as a canonical-main maintenance action."""

from __future__ import annotations

import argparse
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.blueprint.generate import (
    blueprint_generation_lock,
    generate_committed_blueprint,
)
from teleclaude.core.blueprint.manifest import read_published_generation
from teleclaude.core.integration.post_commit_maintenance import selected_maintenance_revision
from teleclaude.core.project_state import resolve_project_state_root

logger = get_logger(__name__)

_TRIGGER_REVISION_OPTION = "--trigger-revision"
_MAINTENANCE_STARTED_EVENT = "blueprint_maintenance_started"
_MAINTENANCE_ALREADY_CURRENT_EVENT = "blueprint_maintenance_already_current"
_MAINTENANCE_COMPLETED_EVENT = "blueprint_maintenance_completed"
_MAINTENANCE_FAILED_EVENT = "blueprint_maintenance_failed"


def run_blueprint_maintenance(project_root: str | Path, *, trigger_revision: str | None) -> None:
    """Converge the owning checkout's shared graph to the selected committed source: committed main, or the commit a release installation runs."""
    root = resolve_project_state_root(project_root)
    selected_revision: str | None = None
    try:
        with blueprint_generation_lock(root, wait=True):
            selected_revision = selected_maintenance_revision(root)
            logger.info(
                _MAINTENANCE_STARTED_EVENT,
                trigger_revision=trigger_revision,
                selected_revision=selected_revision,
            )
            current = read_published_generation(root)
            if current is not None and current[1].baseline_sha == selected_revision:
                logger.info(
                    _MAINTENANCE_ALREADY_CURRENT_EVENT,
                    trigger_revision=trigger_revision,
                    selected_revision=selected_revision,
                )
                return
            manifest = generate_committed_blueprint(root, baseline_sha=selected_revision)
            logger.info(
                _MAINTENANCE_COMPLETED_EVENT,
                trigger_revision=trigger_revision,
                selected_revision=selected_revision,
                generated_revision=manifest.baseline_sha,
            )
    except Exception:
        logger.error(
            _MAINTENANCE_FAILED_EVENT,
            trigger_revision=trigger_revision,
            selected_revision=selected_revision,
            exc_info=True,
        )
        raise


def main() -> None:
    """Run the installed module entrypoint used by the maintenance executor."""
    parser = argparse.ArgumentParser()
    parser.add_argument(_TRIGGER_REVISION_OPTION)
    args = parser.parse_args()
    run_blueprint_maintenance(Path.cwd(), trigger_revision=args.trigger_revision)


if __name__ == "__main__":
    main()
