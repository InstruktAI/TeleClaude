"""Shared checkpoint flag helpers.

Session-scoped files live under the TeleClaude session TMPDIR base.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.paths import TMP_SESSIONS_DIR
from teleclaude.runtime.config import get_runtime_config

logger = get_logger("teleclaude.hooks.checkpoint_flags")

CHECKPOINT_CLEAR_FLAG = "teleclaude_checkpoint_clear"
CHECKPOINT_RECHECK_FLAG = "teleclaude_checkpoint_recheck"
CHECKPOINT_AUTHORED_MAIN_COMMIT_FLAG = "teleclaude_checkpoint_authored_main_commit"
CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG = "teleclaude_checkpoint_integrator_maintenance"
CHECKPOINT_COMMIT_OBLIGATIONS_FLAG = "teleclaude_checkpoint_commit_obligations"


def session_tmp_base_dir() -> Path:
    """Return the base directory used for session-scoped checkpoint flags."""
    override = get_runtime_config().tmpdir_base
    if override is not None:
        return override.resolve()
    return TMP_SESSIONS_DIR.resolve()


def _safe_session_path_component(value: str) -> str:
    """Convert a session identifier into a filesystem-safe path component."""
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def checkpoint_flag_path(session_id: str, flag_name: str) -> Path:
    """Return the path for a specific session-scoped checkpoint flag."""
    session_dir = session_tmp_base_dir() / _safe_session_path_component(session_id)
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


def record_integrator_maintenance_marker(session_id: str, merge_range: str) -> None:
    """Append a delivered merge range to the integrator-maintenance marker.

    Accumulates ranges across candidates drained in one integrator run.
    Raises OSError on write failure so callers can surface it as a warning —
    a silent failure here means post-merge maintenance is never prompted.
    """
    flag_path = checkpoint_flag_path(session_id, CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    existing = flag_path.read_text(encoding="utf-8") if flag_path.exists() else ""
    lines = [line for line in existing.splitlines() if line]
    lines.append(merge_range)
    flag_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_commit_obligations(session_id: str, actions: list[str]) -> None:
    """Append commit-derived maintenance actions to this turn's obligation ledger."""
    if not actions:
        return
    flag_path = checkpoint_flag_path(session_id, CHECKPOINT_COMMIT_OBLIGATIONS_FLAG)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    existing = flag_path.read_text(encoding="utf-8") if flag_path.exists() else ""
    current_actions = [line for line in existing.splitlines() if line]
    current_actions.extend(action for action in actions if action)
    flag_path.write_text("\n".join(_dedupe_preserving_order(current_actions)) + "\n", encoding="utf-8")
    logger.debug("Checkpoint commit obligations recorded", session_id=session_id, actions=actions)


def read_commit_obligations(session_id: str) -> list[str]:
    """Return outstanding commit-derived maintenance actions."""
    flag_path = checkpoint_flag_path(session_id, CHECKPOINT_COMMIT_OBLIGATIONS_FLAG)
    if not flag_path.exists():
        return []
    content = flag_path.read_text(encoding="utf-8")
    return _dedupe_preserving_order([line for line in content.splitlines() if line])


def discharge_commit_obligation(session_id: str, action: str) -> bool:
    """Remove one satisfied maintenance action from the obligation ledger."""
    flag_path = checkpoint_flag_path(session_id, CHECKPOINT_COMMIT_OBLIGATIONS_FLAG)
    if not flag_path.exists():
        return False
    actions = [line for line in flag_path.read_text(encoding="utf-8").splitlines() if line]
    remaining = [item for item in actions if item != action]
    if len(remaining) == len(actions):
        return False
    if remaining:
        flag_path.write_text("\n".join(_dedupe_preserving_order(remaining)) + "\n", encoding="utf-8")
    else:
        flag_path.unlink()
    logger.debug("Checkpoint commit obligation discharged", session_id=session_id, action=action)
    return True


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


def read_integrator_maintenance_marker(session_id: str) -> str | None:
    """Return the integrator-maintenance marker content, or None if absent."""
    flag_path = checkpoint_flag_path(session_id, CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG)
    if not flag_path.exists():
        return None
    try:
        return flag_path.read_text(encoding="utf-8")
    except OSError:
        return None


def consume_integrator_maintenance_marker(session_id: str) -> str | None:
    """Read and delete the integrator-maintenance marker; return its content or None."""
    content = read_integrator_maintenance_marker(session_id)
    if content is not None:
        consume_checkpoint_flag(session_id, CHECKPOINT_INTEGRATOR_MAINTENANCE_FLAG)
    return content


def is_checkpoint_disabled(session_id: str) -> bool:
    """Return True when checkpoints are manually skipped for the current turn."""
    return has_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)
