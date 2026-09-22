"""Shared checkpoint flag helpers.

Session-scoped files live under the TeleClaude session TMPDIR base.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.paths import TMP_SESSIONS_DIR, safe_path_component

logger = get_logger("teleclaude.hooks.checkpoint_flags")

CHECKPOINT_CLEAR_FLAG = "teleclaude_checkpoint_clear"
CHECKPOINT_RECHECK_FLAG = "teleclaude_checkpoint_recheck"
CHECKPOINT_AUTHORED_MAIN_COMMIT_FLAG = "teleclaude_checkpoint_authored_main_commit"
CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG = "teleclaude_checkpoint_integrator_maintenance"

_INTEGRATOR_MAINTENANCE_RANGE_PREFIX = "range:"
_INTEGRATOR_MAINTENANCE_ACTION_PREFIX = "action:"
_INTEGRATOR_MAINTENANCE_ACTION_DISCHARGED_LOG = "Integrator maintenance action discharged"
_MARKER_LINE_SEPARATOR = "\n"
_TEXT_ENCODING = "utf-8"
_EMPTY_MARKER_CONTENT = ""


@dataclass(frozen=True)
class IntegratorMaintenanceMarker:
    """Delivered ranges and their still-outstanding maintenance actions."""

    merge_ranges: tuple[str, ...]
    outstanding_action_ids: tuple[str, ...]


def session_tmp_base_dir() -> Path:
    """Return the base directory used for session-scoped checkpoint flags."""
    return TMP_SESSIONS_DIR.resolve()


def checkpoint_flag_path(session_id: str, flag_name: str) -> Path:
    """Return the path for a specific session-scoped checkpoint flag."""
    session_dir = session_tmp_base_dir() / safe_path_component(session_id)
    return session_dir / flag_name


def set_checkpoint_flag(session_id: str, flag_name: str) -> None:
    """Create a session-scoped checkpoint flag file if possible."""
    flag_path = checkpoint_flag_path(session_id, flag_name)
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()
        logger.debug("Checkpoint flag set", session_id=session_id, flag=flag_name)
    except OSError as exc:
        logger.warning(
            "Failed to set checkpoint flag",
            session_id=session_id,
            flag=flag_name,
            path=str(flag_path),
            error=str(exc),
        )


def record_authored_main_commit(session_id: str) -> None:
    """Record that this session authored a main-branch commit."""
    set_checkpoint_flag(session_id, CHECKPOINT_AUTHORED_MAIN_COMMIT_FLAG)


def has_authored_main_commit_flag(session_id: str) -> bool:
    """Return True when this session has authored a main-branch commit."""
    return has_checkpoint_flag(session_id, CHECKPOINT_AUTHORED_MAIN_COMMIT_FLAG)


def consume_authored_main_commit_flag(session_id: str) -> bool:
    """Consume this session's authored-main-commit latch."""
    return consume_checkpoint_flag(session_id, CHECKPOINT_AUTHORED_MAIN_COMMIT_FLAG)


def has_checkpoint_flag(session_id: str, flag_name: str) -> bool:
    """Return True when the session-scoped checkpoint flag exists."""
    return checkpoint_flag_path(session_id, flag_name).exists()


def consume_checkpoint_flag(session_id: str, flag_name: str) -> bool:
    """Remove a session-scoped checkpoint flag and report whether it existed."""
    flag_path = checkpoint_flag_path(session_id, flag_name)
    if not flag_path.exists():
        return False
    try:
        flag_path.unlink()
        logger.debug("Checkpoint flag consumed", session_id=session_id, flag=flag_name)
    except OSError as exc:
        logger.warning(
            "Failed to consume checkpoint flag",
            session_id=session_id,
            flag=flag_name,
            path=str(flag_path),
            error=str(exc),
        )
    return True


def _integrator_maintenance_marker_path(project_root: str | Path) -> Path:
    """Return the canonical-checkout-owned integrator-maintenance marker path."""
    canonical_root = resolve_project_root(project_root)
    return session_tmp_base_dir() / safe_path_component(str(canonical_root)) / CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG


def _parse_integrator_maintenance_marker(content: str) -> IntegratorMaintenanceMarker:
    """Parse current and legacy marker payloads into their durable state."""
    merge_ranges: list[str] = []
    outstanding_action_ids: list[str] = []
    for line in content.splitlines():
        if not line:
            continue
        if line.startswith(_INTEGRATOR_MAINTENANCE_ACTION_PREFIX):
            outstanding_action_ids.append(line.removeprefix(_INTEGRATOR_MAINTENANCE_ACTION_PREFIX))
        elif line.startswith(_INTEGRATOR_MAINTENANCE_RANGE_PREFIX):
            merge_ranges.append(line.removeprefix(_INTEGRATOR_MAINTENANCE_RANGE_PREFIX))
        else:
            merge_ranges.append(line)
    return IntegratorMaintenanceMarker(
        merge_ranges=tuple(_dedupe_preserving_order(merge_ranges)),
        outstanding_action_ids=tuple(_dedupe_preserving_order(outstanding_action_ids)),
    )


def _write_integrator_maintenance_marker(flag_path: Path, marker: IntegratorMaintenanceMarker) -> None:
    """Persist the marker's ranges and outstanding actions in distinct records."""
    lines = [
        *[_INTEGRATOR_MAINTENANCE_RANGE_PREFIX + merge_range for merge_range in marker.merge_ranges],
        *[_INTEGRATOR_MAINTENANCE_ACTION_PREFIX + action_id for action_id in marker.outstanding_action_ids],
    ]
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(_MARKER_LINE_SEPARATOR.join(lines) + _MARKER_LINE_SEPARATOR, encoding=_TEXT_ENCODING)


def record_integrator_maintenance_marker(project_root: str | Path, merge_range: str, actions: list[str]) -> None:
    """Add a delivered range and its owed actions to the checkout marker.

    Accumulates ranges across candidates drained in one integrator run.
    Raises OSError on write failure so callers can surface it as a warning —
    a silent failure here means post-merge maintenance is never prompted.
    """
    flag_path = _integrator_maintenance_marker_path(project_root)
    content = flag_path.read_text(encoding=_TEXT_ENCODING) if flag_path.exists() else _EMPTY_MARKER_CONTENT
    marker = _parse_integrator_maintenance_marker(content)
    _write_integrator_maintenance_marker(
        flag_path,
        IntegratorMaintenanceMarker(
            merge_ranges=tuple(_dedupe_preserving_order([*marker.merge_ranges, merge_range])),
            outstanding_action_ids=tuple(_dedupe_preserving_order([*marker.outstanding_action_ids, *actions])),
        ),
    )


def _dedupe_preserving_order(items: list[str]) -> list[str]:
    """Return values once, preserving first-seen order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def read_integrator_maintenance_marker(project_root: str | Path) -> IntegratorMaintenanceMarker | None:
    """Return the checkout-owned integrator-maintenance marker, or None if absent."""
    flag_path = _integrator_maintenance_marker_path(project_root)
    if not flag_path.exists():
        return None
    try:
        return _parse_integrator_maintenance_marker(flag_path.read_text(encoding=_TEXT_ENCODING))
    except OSError:
        return None


def consume_integrator_maintenance_marker(project_root: str | Path) -> IntegratorMaintenanceMarker | None:
    """Read and delete the checkout-owned maintenance marker, if present."""
    marker = read_integrator_maintenance_marker(project_root)
    if marker is not None:
        _integrator_maintenance_marker_path(project_root).unlink(missing_ok=True)
    return marker


def discharge_integrator_maintenance_action(project_root: str | Path, action: str) -> bool:
    """Remove one evidenced action and delete the marker after its last discharge."""
    marker = read_integrator_maintenance_marker(project_root)
    if marker is None or action not in marker.outstanding_action_ids:
        return False
    remaining = tuple(action_id for action_id in marker.outstanding_action_ids if action_id != action)
    flag_path = _integrator_maintenance_marker_path(project_root)
    if remaining:
        _write_integrator_maintenance_marker(
            flag_path,
            IntegratorMaintenanceMarker(merge_ranges=marker.merge_ranges, outstanding_action_ids=remaining),
        )
    else:
        flag_path.unlink(missing_ok=True)
    logger.debug(_INTEGRATOR_MAINTENANCE_ACTION_DISCHARGED_LOG, project_root=str(project_root), action=action)
    return True


def is_checkpoint_disabled(session_id: str) -> bool:
    """Return True when checkpoints are manually skipped for the current turn."""
    return has_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)
