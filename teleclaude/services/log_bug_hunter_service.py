"""Daemon-owned scheduler for the log bug hunter job."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.constants import ROLE_SYSTEM
from teleclaude.core.models import Session, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.origins import InputOrigin
from teleclaude.paths import LOG_BUG_HUNTER_STATE_PATH, REPO_ROOT
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

LOG_BUG_HUNTER_JOB = "log_bug_hunter"
LOG_BUG_HUNTER_INTERVAL_S = 300.0
LOG_BUG_HUNTER_LOG_WINDOW = "1h"
LOG_BUG_HUNTER_AGENT = "codex"
LOG_BUG_HUNTER_THINKING_MODE = "fast"

_CANDIDATE_ERROR_SIGNAL_RE = re.compile(
    r"(?:\bERROR\b|\bCRITICAL\b|\bFATAL\b|\bEXCEPTION\b|Traceback \(most recent call last\):|\bcrashed\b)",
    re.IGNORECASE,
)


class LogBugHunterStateDict(TypedDict):
    """Serialized log bug hunter state."""

    last_checked_at: str | None
    last_dispatched_at: str | None
    last_status: str
    last_error: str | None
    last_session_id: str | None


@dataclass
class LogBugHunterState:
    """Persisted daemon-side state for the bug-hunter scheduler."""

    last_checked_at: datetime | None = None
    last_dispatched_at: datetime | None = None
    last_status: str = "never"
    last_error: str | None = None
    last_session_id: str | None = None

    def to_dict(self) -> LogBugHunterStateDict:
        """Serialize state for JSON persistence."""
        return {
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "last_dispatched_at": self.last_dispatched_at.isoformat() if self.last_dispatched_at else None,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_session_id": self.last_session_id,
        }

    @classmethod
    def from_dict(cls, data: LogBugHunterStateDict) -> LogBugHunterState:
        """Deserialize persisted JSON state."""

        def _parse_dt(key: Literal["last_checked_at", "last_dispatched_at"]) -> datetime | None:
            raw = data[key]
            if not raw:
                return None
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                return None

        return cls(
            last_checked_at=_parse_dt("last_checked_at"),
            last_dispatched_at=_parse_dt("last_dispatched_at"),
            last_status=data["last_status"],
            last_error=data["last_error"],
            last_session_id=data["last_session_id"],
        )


class LogBugHunterService:
    """Checks recent daemon logs and dispatches the bug hunter when needed."""

    def __init__(
        self,
        *,
        create_session: Callable[[CreateSessionCommand], Awaitable[dict[str, str]]],
        list_active_sessions: Callable[[], Awaitable[list[Session]]],
        project_root: Path = REPO_ROOT,
        state_path: Path = LOG_BUG_HUNTER_STATE_PATH,
    ) -> None:
        self._create_session = create_session
        self._list_active_sessions = list_active_sessions
        self._project_root = project_root
        self._state_path = state_path
        self._state = self._load_state()

    async def run_loop(self) -> None:
        """Run the scheduler loop until cancelled."""
        while True:
            try:
                await self.maybe_dispatch()
            except asyncio.CancelledError:
                logger.debug("log bug hunter scheduler loop cancelled")
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("log bug hunter scheduler iteration failed: %s", exc, exc_info=True)
            await asyncio.sleep(LOG_BUG_HUNTER_INTERVAL_S)

    async def maybe_dispatch(self, *, now: datetime | None = None) -> bool:
        """Dispatch only when the last hour of logs contains candidate errors."""
        check_time = now or datetime.now(UTC)
        if not self._is_due(check_time):
            return False

        ok, output = await self._fetch_recent_logs()
        self._state.last_checked_at = check_time

        if not ok:
            self._mark_failed(f"log query failed: {output}")
            return False

        if not output.strip():
            self._mark_failed("log query returned no output")
            return False

        if not self.has_candidate_error_signals(output):
            self._state.last_status = "clean"
            self._state.last_error = None
            self._save_state()
            logger.debug("log bug hunter scheduler found no candidate errors")
            return False

        if await self._has_active_job_session():
            self._state.last_status = "already-running"
            self._state.last_error = None
            self._save_state()
            logger.info("log bug hunter session already active; skipping scheduler dispatch")
            return False

        session_id = await self._dispatch_job_session()
        self._state.last_dispatched_at = check_time
        self._state.last_status = "dispatched"
        self._state.last_error = None
        self._state.last_session_id = session_id
        self._save_state()
        logger.info("log bug hunter dispatched", session_id=session_id)
        return True

    @staticmethod
    def has_candidate_error_signals(output: str) -> bool:
        """Return True when log output contains actionable error signals."""
        return bool(_CANDIDATE_ERROR_SIGNAL_RE.search(output))

    def _is_due(self, now: datetime) -> bool:
        last_checked = self._state.last_checked_at
        if last_checked is None:
            return True
        if last_checked.tzinfo is None:
            last_checked = last_checked.replace(tzinfo=UTC)
        return now - last_checked >= timedelta(hours=1)

    async def _fetch_recent_logs(self) -> tuple[bool, str]:
        return await asyncio.to_thread(self._run_recent_log_query)

    def _run_recent_log_query(self) -> tuple[bool, str]:
        try:
            completed = subprocess.run(
                ["instrukt-ai-logs", "teleclaude", "--since", LOG_BUG_HUNTER_LOG_WINDOW],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self._project_root),
            )
        except subprocess.TimeoutExpired:
            return False, "instrukt-ai-logs timed out"
        except OSError as exc:
            return False, str(exc)

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"instrukt-ai-logs exited with code {completed.returncode}"
            return False, detail
        return True, stdout

    async def _has_active_job_session(self) -> bool:
        sessions = await self._list_active_sessions()
        return any((session.job or "").strip() == LOG_BUG_HUNTER_JOB for session in sessions)

    async def _dispatch_job_session(self) -> str:
        result = await self._create_session(
            CreateSessionCommand(
                project_path=str(self._project_root),
                origin=InputOrigin.TERMINAL.value,
                title="Job: log_bug_hunter",
                launch_intent=SessionLaunchIntent(
                    kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                    agent=LOG_BUG_HUNTER_AGENT,
                    thinking_mode=LOG_BUG_HUNTER_THINKING_MODE,
                    message=(
                        "You are running the log_bug_hunter job. Candidate daemon error signals were detected "
                        "in the last hour. Read @docs/project/spec/jobs/log-bug-hunter.md for your full instructions."
                    ),
                ),
                system_role=ROLE_SYSTEM,
                job=LOG_BUG_HUNTER_JOB,
            )
        )
        session_id = result.get("session_id")
        if not session_id:
            raise ValueError("log bug hunter dispatch returned no session_id")
        return str(session_id)

    def _mark_failed(self, error: str) -> None:
        self._state.last_status = "failed"
        self._state.last_error = error
        self._save_state()
        logger.error("log bug hunter scheduler failed: %s", error)

    def _load_state(self) -> LogBugHunterState:
        if not self._state_path.exists():
            return LogBugHunterState()
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return LogBugHunterState()
        if not isinstance(raw, dict):
            return LogBugHunterState()
        return LogBugHunterState.from_dict(cast(LogBugHunterStateDict, raw))

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state.to_dict(), indent=2), encoding="utf-8")
