"""Helper starts recorded on the computer that holds the item, for a session created on another computer.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Helpers of a driver). A claiming group spans
computers, so the session that creates a helper may run where the item does not. The start is recorded on the item
before the session exists, by asking the computer that holds the creator\'s ancestor, and is named or withdrawn there
once the creation has an outcome. The ask is a daemon-to-daemon request under the platform\'s own principal: the
computer that receives it judges the creator\'s membership from its own item and cluster evidence, never from what
the asking computer says about the creator\'s standing.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, cast

from instrukt_ai_logging import get_logger

from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.paths import STATE_DIR

logger = get_logger(__name__)

CREATOR_FIELD: Final = "creator"
CREATOR_COMPUTER_FIELD: Final = "creator_computer"
ANCESTOR_FIELD: Final = "ancestor"
NEW_COMPUTER_FIELD: Final = "new_computer"
ENTRIES_FIELD: Final = "entries"
SESSION_FIELD: Final = "session_id"
SESSION_COMPUTER_FIELD: Final = "session_computer"
PARENT_FIELD: Final = "parent"
COMPUTER_FIELD: Final = "computer"
ROOT_FIELD: Final = "root"
ITEM_FIELD: Final = "item"
KEY_FIELD: Final = "key"

OWNER_UNREACHABLE: Final = (
    "cannot reach {computer}, which holds the item this session's group works on, to record the helper start; "
    "nothing was created. Retry when {computer} answers."
)
SETTLE_FAILED_LOG: Final = "helper_start_settle_failed"
KEYS_FIELD: Final = "keys"
TARGET_FIELD: Final = "target"
DEADLINE_FIELD: Final = "deadline_at"
START_KEY_FIELD: Final = "start_key"
UNRESOLVED_DIRECTORY: Final = STATE_DIR / "helper-start-unresolved"

# The start keys whose creation this computer is performing right now; the creation runs in this process, so a key
# is in progress exactly while its fence is open and never after the process has ended.
_IN_FLIGHT: dict[str, int] = {}


def mark_in_flight(keys: Sequence[str]) -> None:
    for key in keys:
        _IN_FLIGHT[key] = _IN_FLIGHT.get(key, 0) + 1


def release_in_flight(keys: Sequence[str]) -> None:
    for key in keys:
        remaining = _IN_FLIGHT.get(key, 0) - 1
        if remaining > 0:
            _IN_FLIGHT[key] = remaining
        else:
            _IN_FLIGHT.pop(key, None)


def record_unresolved(key: str, target: str, deadline_at: float) -> None:
    """Keep a carried creation as in progress, durably, from before it is handed to the target computer.

    Whether the target ran it, is running it or will still receive it is not known here until the target says so; the
    record survives a restart of this process and is cleared by the creation\'s outcome or by the target\'s answer.
    """
    UNRESOLVED_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (UNRESOLVED_DIRECTORY / key).write_text(
        json.dumps({TARGET_FIELD: target, DEADLINE_FIELD: deadline_at}), encoding="utf-8"
    )


def clear_unresolved(key: str) -> None:
    """Forget a carried creation whose outcome is now known."""
    (UNRESOLVED_DIRECTORY / key).unlink(missing_ok=True)


def _read_unresolved(key: str) -> tuple[str, float] | None:
    path = UNRESOLVED_DIRECTORY / key
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return str(record[TARGET_FIELD]), float(record[DEADLINE_FIELD])
    except (OSError, ValueError, KeyError, TypeError):
        return ("", 0.0)  # a record that cannot be read is a creation not known to be over


def creation_open_here(key: str, deadline_at: float) -> bool:
    """Whether this computer is handling the carried creation, or can still receive it before its deadline."""
    return key in _IN_FLIGHT or time.time() <= deadline_at


async def keys_still_open(keys: Sequence[str]) -> list[str]:
    """The keys among ``keys`` whose creation this computer is performing, or has not learned the outcome of.

    A carried creation of unknown outcome is asked of its target; only the target\'s answer that it neither handles the
    carry nor can still receive it ends the doubt, and ends it for good.
    """
    still_open: list[str] = []
    for key in keys:
        if key in _IN_FLIGHT:
            still_open.append(key)
            continue
        unresolved = _read_unresolved(key)
        if unresolved is None:
            continue
        target, deadline_at = unresolved
        if await creation_closed_at(target, key, deadline_at):
            clear_unresolved(key)
        else:
            still_open.append(key)
    return still_open


class PeerStartRequest(StrEnum):
    """The daemon-to-daemon requests that record a helper start on the computer holding its item."""

    REGISTER = "register_helper_start"
    SETTLE = "settle_helper_start"
    IN_FLIGHT = "helper_start_in_flight"
    CREATION_STATE = "helper_start_creation_state"


@dataclass(frozen=True)
class StartEntry:
    """One helper start recorded on an item: the computer holding it (empty for this computer), project root and key."""

    computer: str
    root: str
    item: str
    key: str

    def to_wire(self) -> JsonDict:
        return {COMPUTER_FIELD: self.computer, ROOT_FIELD: self.root, ITEM_FIELD: self.item, KEY_FIELD: self.key}

    @classmethod
    def from_wire(cls, value: object) -> StartEntry | None:
        if not isinstance(value, dict):
            return None
        fields = [value.get(name) for name in (COMPUTER_FIELD, ROOT_FIELD, ITEM_FIELD, KEY_FIELD)]
        if not all(isinstance(field, str) for field in fields):
            return None
        computer, root, item, key = cast(list[str], fields)
        return cls(computer, root, item, key)


async def _ask(owner: str, command: PeerStartRequest, request: JsonDict) -> JsonValue:
    """One request to the owning computer, answered by that computer alone."""
    from teleclaude.core.command_dispatch import relay_caller_read  # noqa: PLC0415 - deferred cycle
    from teleclaude.core.command_registry import get_command_service  # noqa: PLC0415 - deferred cycle

    client = get_command_service().client
    return await relay_caller_read(client, owner, command.value, principal=SYSTEM_DAEMON_PRINCIPAL, request=request)


async def register_with_owner(
    owner: str,
    creator: str,
    creator_computer: str,
    ancestor: str,
    new_computer: str,
    start_key: str,
    deadline_at: float,
) -> list[StartEntry]:
    """Record the start on every item the creator\'s group holds on ``owner`` (and beyond it), before the creation.

    A refusal of the owner (a closing claim, a changed holder, an earlier group) refuses the creation with its words;
    an owner that cannot be reached refuses it too, since a start that cannot be recorded cannot be allowed.
    """
    from teleclaude.core.command_dispatch import RelayFailure, RemoteDispatchError  # noqa: PLC0415 - deferred cycle
    from teleclaude.core.workflow_machine.helpers import HelperStartRefused  # noqa: PLC0415 - helpers imports this

    request: JsonDict = {
        CREATOR_FIELD: creator,
        CREATOR_COMPUTER_FIELD: creator_computer,
        ANCESTOR_FIELD: ancestor,
        NEW_COMPUTER_FIELD: new_computer,
        START_KEY_FIELD: start_key,
        DEADLINE_FIELD: deadline_at,
    }
    try:
        answer = await _ask(owner, PeerStartRequest.REGISTER, request)
    except RelayFailure as failure:
        if failure.reason.value == "refused_by_target":
            raise HelperStartRefused(failure.detail) from failure
        raise HelperStartRefused(OWNER_UNREACHABLE.format(computer=owner)) from failure
    except (RemoteDispatchError, RuntimeError, ValueError, OSError) as error:
        raise HelperStartRefused(OWNER_UNREACHABLE.format(computer=owner)) from error
    parsed = [StartEntry.from_wire(entry) for entry in answer] if isinstance(answer, list) else []
    return [entry for entry in parsed if entry is not None]


async def settle_with_owners(
    entries: Sequence[StartEntry], session_id: str, session_computer: str, parent: str, local: str
) -> None:
    """Name the created session on each start held by another computer, or withdraw the starts (empty session id).

    A settlement that does not arrive leaves the start recorded and unnamed, which keeps the closing sweep waiting; it
    is never read as the creation not having happened.
    """
    by_owner: dict[str, list[StartEntry]] = {}
    for entry in entries:
        if entry.computer and entry.computer != local:
            by_owner.setdefault(entry.computer, []).append(entry)
    for owner, owned in by_owner.items():
        request: JsonDict = {
            ENTRIES_FIELD: [entry.to_wire() for entry in owned],
            SESSION_FIELD: session_id,
            SESSION_COMPUTER_FIELD: session_computer,
            PARENT_FIELD: parent,
        }
        try:
            await _ask(owner, PeerStartRequest.SETTLE, request)
        except Exception:  # supervision boundary: an unsettled start stays recorded and the creation stands
            logger.warning(SETTLE_FAILED_LOG, computer=owner, session=session_id, exc_info=True)


async def keys_in_flight_at(owner: str, keys: Sequence[str]) -> set[str] | None:
    """The keys among ``keys`` that ``owner`` is still creating sessions for; None when it did not answer."""
    from teleclaude.core.command_dispatch import RemoteDispatchError  # noqa: PLC0415 - deferred cycle

    try:
        answer = await _ask(owner, PeerStartRequest.IN_FLIGHT, {KEYS_FIELD: list(keys)})
    except (RemoteDispatchError, RuntimeError, ValueError, OSError):
        return None
    return {key for key in answer if isinstance(key, str)} if isinstance(answer, list) else None


async def creation_closed_at(target: str, key: str, deadline_at: float) -> bool:
    """True only when ``target`` answers that it neither handles the carried creation ``key`` nor can still receive it."""
    from teleclaude.core.command_dispatch import RemoteDispatchError  # noqa: PLC0415 - deferred cycle

    if not target:
        return False
    try:
        answer = await _ask(target, PeerStartRequest.CREATION_STATE, {KEYS_FIELD: [key], DEADLINE_FIELD: deadline_at})
    except (RemoteDispatchError, RuntimeError, ValueError, OSError):
        return False
    return answer is False
