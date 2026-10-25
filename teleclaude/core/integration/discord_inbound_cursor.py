"""Integration-owned contract of the per-place Discord inbound recovery cursor.

A place is a session thread in a project forum or a Team channel. Its cursor is the newest Discord message in
that place whose handling has concluded (``local/projects/teleclaude/spec/domain/integration``). Messages are
identified by Discord snowflakes, which order by posting time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from teleclaude.constants import RUNTIME_RECORD_RETENTION_WINDOW
from teleclaude.core.dates import ensure_utc

# The identity under which the inbound queue accepts one attachment of a message. A message's parts are not
# duplicates of each other, so each carries the message id completed by its own part id.
PART_IDENTITY_SEPARATOR: Final = ":"
PART_IDENTITY_TEMPLATE: Final = "{message_id}" + PART_IDENTITY_SEPARATOR + "{part_id}"

# A Discord snowflake is the milliseconds since the Discord epoch, shifted above the worker, process and sequence bits.
_DISCORD_EPOCH_MS: Final = 1_420_070_400_000
_SNOWFLAKE_TIME_SHIFT: Final = 22
_MS_PER_SECOND: Final = 1000

# A place that has no message yet is read from its beginning.
EMPTY_PLACE_CURSOR: Final = 0


def snowflake_at(moment: datetime) -> int:
    """The smallest snowflake a message posted at ``moment`` can have."""
    milliseconds = int(ensure_utc(moment).timestamp() * _MS_PER_SECOND)
    return max(milliseconds - _DISCORD_EPOCH_MS, 0) << _SNOWFLAKE_TIME_SHIFT


def retention_horizon_snowflake(now: datetime) -> int:
    """The snowflake before which the inbound queue no longer retains what it accepted.

    Input accepted after the horizon is still retained, so a place with nothing retained after it has had
    nothing processed after it.
    """
    return snowflake_at(now - RUNTIME_RECORD_RETENTION_WINDOW)


def message_id_of_source_identity(source_message_id: str) -> int | None:
    """The Discord message id inside an accepted input's source identity, whole message or one of its parts."""
    message_id = source_message_id.split(PART_IDENTITY_SEPARATOR, maxsplit=1)[0]
    return int(message_id) if message_id.isdecimal() else None


def seed_for_place(newest_retained_message_id: int | None, *, bound_at: datetime | None, now: datetime) -> int:
    """Where the cursor of a place without one starts.

    The place's own acceptance record gives the newest message the queue still retains as accepted, and that
    is the start whatever its age: everything after it was not processed. Only a place with no retained
    acceptance starts at the retention horizon, since nothing before it can be told apart. A place bound
    recently starts no earlier than its binding.
    """
    seed = newest_retained_message_id if newest_retained_message_id is not None else retention_horizon_snowflake(now)
    if bound_at is None:
        return seed
    return max(seed, snowflake_at(bound_at))
