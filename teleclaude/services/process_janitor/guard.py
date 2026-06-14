"""Never-kill guard for irreversible process reaping."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psutil

from teleclaude.core import tmux_bridge
from teleclaude.core.db import Db

from .matcher import ProcessMatch


class ProcessJanitorDb(Protocol):
    """DB surface the never-kill guard needs."""

    async def get_active_sessions(self) -> object: ...

    async def list_valid_process_spawn_registry_entries(self, now: str) -> object: ...


@dataclass(frozen=True)
class GuardDecision:
    """Decision from the never-kill guard."""

    allowed: bool
    reason: str


class NeverKillGuard:
    """Reject process candidates that overlap protected daemon/session identities."""

    def __init__(self, db: Db) -> None:
        self._db = db
        self._own_pid = os.getpid()
        self._own_uid = os.getuid()
        self._own_pgrp = os.getpgrp()

    async def admit(self, match: ProcessMatch) -> GuardDecision:
        """Return whether a matched process may be reaped."""
        pid = match.pid
        if pid == self._own_pid:
            return GuardDecision(False, "daemon-pid")
        try:
            proc = psutil.Process(pid)
            if proc.uids().real != self._own_uid:
                return GuardDecision(False, "uid-mismatch")
            if os.getpgid(pid) == self._own_pgrp:
                return GuardDecision(False, "daemon-process-group")
        except (OSError, psutil.Error):
            return GuardDecision(False, "process-identity-unresolved")

        if self._is_descendant(pid, self._own_pid):
            return GuardDecision(False, "daemon-child-tree")
        if await self._has_valid_lease(pid):
            return GuardDecision(False, "valid-lease")
        session_decision = await self._session_guard(pid)
        if not session_decision.allowed:
            return session_decision
        return GuardDecision(True, "signature-allowed")

    async def _has_valid_lease(self, pid: int) -> bool:
        now = datetime.now(UTC).isoformat()
        entries = await self._db.list_valid_process_spawn_registry_entries(now)
        return any(getattr(entry, "pid", None) == pid for entry in entries)

    async def _session_guard(self, pid: int) -> GuardDecision:
        sessions = await self._db.get_active_sessions()
        for session in sessions:
            tmux_name = getattr(session, "tmux_session_name", None)
            if not tmux_name:
                continue
            pane_pid = await tmux_bridge.get_pane_pid(tmux_name)
            if pane_pid is None:
                return GuardDecision(False, "session-pane-unresolved")
            if pid == pane_pid or self._is_descendant(pid, pane_pid):
                return GuardDecision(False, "live-session-tree")
        return GuardDecision(True, "no-live-session-overlap")

    @staticmethod
    def _is_descendant(pid: int, ancestor_pid: int) -> bool:
        try:
            ancestor = psutil.Process(ancestor_pid)
            return any(child.pid == pid for child in ancestor.children(recursive=True))
        except psutil.Error:
            return True
