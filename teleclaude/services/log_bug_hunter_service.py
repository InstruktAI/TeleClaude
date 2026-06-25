"""Per-project executor for the log bug hunter job.

One :class:`LogBugHunterService` instance is bound to a single project. The
orchestrator that iterates subscribed projects (see the project-jobs
orchestrator) owns cross-project scheduling; this service only decides whether
the given project should dispatch a new session based on its recent logs.
"""

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
from teleclaude.services.log_bug_hunter_suppressions import (
    load,
    suppressions_path_for,
    unsuppressed_lines,
)
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

LOG_BUG_HUNTER_JOB = "log_bug_hunter"
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
    """Checks a single project's recent logs and dispatches the bug hunter when needed."""

    def __init__(
        self,
        *,
        create_session: Callable[[CreateSessionCommand], Awaitable[dict[str, str]]],
        list_active_sessions: Callable[[], Awaitable[list[Session]]],
        project_root: Path,
        project_slug: str,
        state_path: Path,
    ) -> None:
        self._create_session = create_session
        self._list_active_sessions = list_active_sessions
        self._project_root = project_root
        self._project_slug = project_slug
        self._state_path = state_path
        self._state = self._load_state()
        # The ledger path is derived from the project slug, never injected, so the
        # daemon reader and the ``telec bugs`` CLI writer resolve the identical file
        # and suppression can never be silently disabled by a missing parameter.
        self._suppressions = load(suppressions_path_for(project_slug))

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

        candidate_lines = self._candidate_error_lines(output)
        if not candidate_lines:
            self._state.last_status = "clean"
            self._state.last_error = None
            self._save_state()
            logger.debug("log bug hunter scheduler found no candidate errors")
            return False

        if not unsuppressed_lines(candidate_lines, self._suppressions, check_time):
            self._state.last_status = "suppressed"
            self._state.last_error = None
            self._save_state()
            logger.info("log bug hunter window fully suppressed; skipping dispatch")
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
    def _candidate_error_lines(output: str) -> list[str]:
        """Return the individual log lines carrying an actionable error signal.

        The scan extracts lines rather than answering a whole-window yes/no so
        suppression can subtract matched lines per-signal: an all-suppressed
        window dispatches nothing, while any unsuppressed line still dispatches.
        """
        return [line for line in output.splitlines() if _CANDIDATE_ERROR_SIGNAL_RE.search(line)]

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
                ["instrukt-ai-logs", self._project_slug, "--since", LOG_BUG_HUNTER_LOG_WINDOW],
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
        """Return True when ``log_bug_hunter`` is active **for this project**.

        The orchestrator hands every executor the same computer-wide session
        list, so the executor must scope the check to its own ``project_root``.
        Matching only on ``session.job`` would let the first dispatched project
        silently starve every other subscribed project in the catalog.
        """
        sessions = await self._list_active_sessions()
        project_root_str = str(self._project_root)
        return any(
            (session.job or "").strip() == LOG_BUG_HUNTER_JOB and (session.project_path or "") == project_root_str
            for session in sessions
        )

    async def _dispatch_job_session(self) -> str:
        result = await self._create_session(
            CreateSessionCommand(
                project_path=str(self._project_root),
                origin=InputOrigin.TERMINAL.value,
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
