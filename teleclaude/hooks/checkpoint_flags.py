"""Shared checkpoint flag helpers.

Session-scoped files live under the TeleClaude session TMPDIR base.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.paths import TMP_SESSIONS_DIR

logger = get_logger("teleclaude.hooks.checkpoint_flags")

CHECKPOINT_CLEAR_FLAG = "teleclaude_checkpoint_clear"
CHECKPOINT_RECHECK_FLAG = "teleclaude_checkpoint_recheck"
CHECKPOINT_POST_COMMIT_REVIEW_PREFIX = "teleclaude_checkpoint_post_commit_review_"


def session_tmp_base_dir() -> Path:
    """Return the base directory used for session-scoped checkpoint flags."""
    base_override = os.environ.get("TELECLAUDE_SESSION_TMPDIR_BASE")
    if base_override:
        return Path(base_override).expanduser().resolve()
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
    except OSError as exc:
        logger.warning(
            "Failed to set checkpoint flag",
            session_id=session_id,
            flag=flag_name,
            path=str(flag_path),
            error=str(exc),
        )


def post_commit_review_flag_name(head_sha: str) -> str:
    """Return the session flag name for a surfaced post-commit review gate."""
    return f"{CHECKPOINT_POST_COMMIT_REVIEW_PREFIX}{head_sha.strip()}"


def has_post_commit_review_flag(session_id: str, head_sha: str) -> bool:
    """Return True if the post-commit review gate was surfaced for HEAD."""
    normalized_sha = head_sha.strip()
    if not normalized_sha:
        return False
    return has_checkpoint_flag(session_id, post_commit_review_flag_name(normalized_sha))


def replace_post_commit_review_flag(session_id: str, head_sha: str) -> None:
    """Record the surfaced post-commit review gate for HEAD.

    The marker is edge-triggered by commit SHA. Older markers are removed so
    the session directory does not accumulate stale post-commit latches.
    """
    normalized_sha = head_sha.strip()
    if not normalized_sha:
        return

    flag_name = post_commit_review_flag_name(normalized_sha)
    flag_path = checkpoint_flag_path(session_id, flag_name)
    session_dir = flag_path.parent
    try:
        session_dir.mkdir(parents=True, exist_ok=True)
        for existing_flag in session_dir.iterdir():
            if existing_flag.name.startswith(CHECKPOINT_POST_COMMIT_REVIEW_PREFIX) and existing_flag.name != flag_name:
                existing_flag.unlink()
    except OSError as exc:
        logger.warning(
            "Failed to replace post-commit review checkpoint flag",
            session_id=session_id,
            flag=flag_name,
            path=str(flag_path),
            error=str(exc),
        )
    set_checkpoint_flag(session_id, flag_name)


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
    """Persistent checkpoint disable switch.

    While this file exists, checkpoints are skipped.
    Re-enable by removing the file.
    """
    return has_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)
