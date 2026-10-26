"""Decide when the fleet master may send a conversation request to GitHub.

Only the fleet master sends conversation requests, so its record is the fleet's share of GitHub's request budget.
It admits a request only while all of these hold:

- it has been the master for at least an hour, because it holds no record of its predecessor's window;
- no limit response has paused conversation requests;
- the installation's latest response left a fifth of its limit for the pull request and review writes that App
  also makes;
- for an append, the appends it sent over the last minute and the last hour stay within half of GitHub's documented
  content-creation limits.

A request that is not admitted comes back with the time to try again. The share is a bounded part of what GitHub
documents; GitHub's secondary limits change without notice and cannot be inspected, so a response that says
otherwise stops the conversation (see ``note_limit``) rather than being argued with.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.workflow_store.github_conversation_budget_store import ConversationBudgetStore, PauseState
from teleclaude.core.workflow_store.github_io_transport import latest_rate_reading
from teleclaude.github.rate_limit_headers import RateReading

MASTER_SINCE_SETTING: Final = "github_conversation_master_since"
_ONE_MINUTE: Final = timedelta(minutes=1)
_ONE_HOUR: Final = timedelta(hours=1)
# GitHub documents no more than 80 content-generating requests per minute and 500 per hour.
_MINUTE_SHARE: Final = 80 // 2
_HOUR_SHARE: Final = 500 // 2
_RESERVE_DIVISOR: Final = 5
_FIRST_UNNAMED_PAUSE: Final = timedelta(minutes=1)
_NOT_MASTER: Final = ""

type SettingReader = Callable[[str], Awaitable[str | None]]
type SettingWriter = Callable[[str, str], Awaitable[None]]
type ReadingSource = Callable[[int, str], RateReading | None]


@dataclass(frozen=True)
class Admission:
    """Whether a request may be sent now and, when it may not, the time to try again.

    ``retry_at`` is None only for a computer that is not the master and so never sends.
    """

    admitted: bool
    retry_at: datetime | None = None


class MasterTenure:
    """Remember since when this computer has been the fleet master."""

    def __init__(self, read_setting: SettingReader, write_setting: SettingWriter) -> None:
        self._read = read_setting
        self._write = write_setting

    async def since(self, *, is_master: bool, now: datetime) -> datetime | None:
        """When this computer became master; None when it is not. Leaving the role forgets the time."""
        raw = await self._read(MASTER_SINCE_SETTING)
        stored = parse_iso_datetime(raw) if raw else None
        if not is_master:
            if stored is not None:
                await self._write(MASTER_SINCE_SETTING, _NOT_MASTER)
            return None
        if stored is None:
            await self._write(MASTER_SINCE_SETTING, now.isoformat())
            return now
        return stored


class ConversationBudget:
    """Admit, count and pause the conversation requests the fleet master sends."""

    def __init__(
        self,
        store: ConversationBudgetStore,
        tenure: MasterTenure,
        *,
        reading_source: ReadingSource = latest_rate_reading,
    ) -> None:
        self._store = store
        self._tenure = tenure
        self._reading_source = reading_source

    async def admit(
        self, *, app_id: int, repository: str, is_master: bool, creates: bool, now: datetime | None = None
    ) -> Admission:
        """Admit one request: an append when ``creates`` is true, otherwise a read."""
        moment = now or datetime.now(UTC)
        master_since = await self._tenure.since(is_master=is_master, now=moment)
        if master_since is None:
            return Admission(admitted=False)
        if moment < master_since + _ONE_HOUR:
            return Admission(admitted=False, retry_at=master_since + _ONE_HOUR)
        pause = await self._store.pause_state()
        if pause.pause_until is not None and pause.pause_until > moment:
            return Admission(admitted=False, retry_at=pause.pause_until)
        reading = self._reading_source(app_id, repository)
        if (
            reading is not None
            and reading.limit
            and reading.reset_at is not None
            and reading.reset_at > moment
            and reading.remaining * _RESERVE_DIVISOR <= reading.limit
        ):
            return Admission(admitted=False, retry_at=reading.reset_at)
        if creates:
            return await self._admit_append(moment)
        return Admission(admitted=True)

    async def record_send(self, now: datetime | None = None) -> None:
        """Count one append the master sent, and end any run of limit responses that named no time."""
        await self._store.record_send(now or datetime.now(UTC))
        pause = await self._store.pause_state()
        if pause.unnamed_limits:
            await self._store.save_pause_state(PauseState(pause.pause_until, 0))

    async def note_limit(self, resume_at: datetime | None, now: datetime | None = None) -> datetime:
        """Pause every conversation request after a limit response and return when requests may resume.

        A response that names a time pauses until that time, however far off. One that names none pauses a minute,
        doubling on each repeated unnamed limit up to an hour. A pause is never shortened by a later response.
        """
        moment = now or datetime.now(UTC)
        pause = await self._store.pause_state()
        unnamed = pause.unnamed_limits
        if resume_at is None:
            unnamed += 1
            until = moment + min(_FIRST_UNNAMED_PAUSE * (1 << (unnamed - 1)), _ONE_HOUR)
        else:
            until = resume_at
        if pause.pause_until is not None and pause.pause_until > until:
            until = pause.pause_until
        await self._store.save_pause_state(PauseState(until, unnamed))
        return until

    async def _admit_append(self, moment: datetime) -> Admission:
        sends = await self._store.sends_since(moment - _ONE_HOUR)
        last_minute = [sent for sent in sends if sent > moment - _ONE_MINUTE]
        if len(last_minute) >= _MINUTE_SHARE:
            return Admission(admitted=False, retry_at=last_minute[len(last_minute) - _MINUTE_SHARE] + _ONE_MINUTE)
        if len(sends) >= _HOUR_SHARE:
            return Admission(admitted=False, retry_at=sends[len(sends) - _HOUR_SHARE] + _ONE_HOUR)
        return Admission(admitted=True)
