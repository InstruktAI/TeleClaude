"""Shared checkpoint flag helpers.

Session-scoped files live under the TeleClaude session TMPDIR base.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger("teleclaude.hooks.checkpoint_flags")

CHECKPOINT_CLEAR_FLAG = "teleclaude_checkpoint_clear"
CHECKPOINT_RECHECK_FLAG = "teleclaude_checkpoint_recheck"


def session_tmp_base_dir() -> Path:
    base_override = os.environ.get("TELECLAUDE_SESSION_TMPDIR_BASE")
    if base_override:
        return Path(base_override).expanduser().resolve()
    return Path(os.path.expanduser("~/.teleclaude/tmp/sessions")).resolve()


def _safe_session_path_component(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def checkpoint_flag_path(session_id: str, flag_name: str) -> Path:
    session_dir = session_tmp_base_dir() / _safe_session_path_component(session_id)
    return session_dir / flag_name


def set_checkpoint_flag(session_id: str, flag_name: str) -> None:
    flag_path = checkpoint_flag_path(session_id, flag_name)
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()
    except OSError as exc:
        logger.warning(
            "Failed to set checkpoint flag",
            session_id=session_id[:8],
            flag=flag_name,
            path=str(flag_path),
            error=str(exc),
        )


def has_checkpoint_flag(session_id: str, flag_name: str) -> bool:
    return checkpoint_flag_path(session_id, flag_name).exists()


def consume_checkpoint_flag(session_id: str, flag_name: str) -> bool:
    flag_path = checkpoint_flag_path(session_id, flag_name)
    if not flag_path.exists():
        return False
    try:
        flag_path.unlink()
    except OSError as exc:
        logger.warning(
            "Failed to consume checkpoint flag",
            session_id=session_id[:8],
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
