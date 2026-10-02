"""Record configuration subjects for existing session rows once at startup."""

import time
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.subject_resolution import ConfigSubjectResolver, SubjectResolutionError
from teleclaude.core.db import db
from teleclaude.core.session_utils import resolve_working_dir

logger = get_logger(__name__)

_BACKFILL_SETTING = "session_config_subject_backfill_complete"
_BACKFILL_COMPLETE_VALUE = "true"
_BACKFILL_SUMMARY_EVENT = "session_config_subject_backfill_finished"
_BACKFILL_RESOLUTION_FAILED_EVENT = "session_config_subject_resolution_failed"


async def backfill_session_config_subjects() -> None:
    """Backfill existing session subjects before local snapshots are warmed."""
    if await db.get_system_setting(_BACKFILL_SETTING) is not None:
        return

    started_at = time.perf_counter()
    locations = await db.list_unattributed_session_locations()
    resolver = ConfigSubjectResolver()
    warned_declarations: set[int] = set()
    rows_updated = 0

    for project_path, subdir in locations:
        if not project_path:
            continue
        working_folder = Path(resolve_working_dir(project_path, subdir))
        try:
            subject = resolver.resolve(working_folder)
        except SubjectResolutionError as error:
            error_identity = id(error)
            if error_identity not in warned_declarations:
                logger.warning(
                    _BACKFILL_RESOLUTION_FAILED_EVENT,
                    working_folder=str(working_folder),
                    error=str(error),
                )
                warned_declarations.add(error_identity)
            continue
        if subject is None:
            continue
        rows_updated += await db.set_session_config_subject_if_unset(
            project_path,
            subdir,
            subject.to_token(),
        )

    if not warned_declarations:
        await db.set_system_setting(_BACKFILL_SETTING, _BACKFILL_COMPLETE_VALUE)
    logger.info(
        _BACKFILL_SUMMARY_EVENT,
        folder_locations=len(locations),
        rows_updated=rows_updated,
        unresolved_declarations=len(warned_declarations),
        backfill_complete=not warned_declarations,
        duration_ms=(time.perf_counter() - started_at) * 1000,
    )
