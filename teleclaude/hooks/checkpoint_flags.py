"""Shared checkpoint flag helpers.

Session-scoped files live under the TeleClaude session TMPDIR base.
"""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.paths import TMP_SESSIONS_DIR, safe_path_component

logger = get_logger("teleclaude.hooks.checkpoint_flags")

CHECKPOINT_CLEAR_FLAG = "teleclaude_checkpoint_clear"
CHECKPOINT_RECHECK_FLAG = "teleclaude_checkpoint_recheck"
CHECKPOINT_AUTHORED_MAIN_COMMIT_FLAG = "teleclaude_checkpoint_authored_main_commit"


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


def is_checkpoint_disabled(session_id: str) -> bool:
    """Return True when checkpoints are manually skipped for the current turn."""
    return has_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)
