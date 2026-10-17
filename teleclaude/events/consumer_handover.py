"""First-upgrade transfer of the retired internal reader's native Redis progress."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger
from redis.exceptions import ResponseError

from teleclaude.events.consumers import Consumer, consumer_group_name, consumer_reader_name
from teleclaude.transport.internal_event_compat import decode_internal_event_entry

if TYPE_CHECKING:
    from teleclaude.events.db import EventDB

logger = get_logger(__name__)

_GROUP_INFO_MISSING = "Internal event predecessor group lacks last-delivered-id"
_SUCCESSOR_POSITION_CONFLICT = "Successor group has already advanced while predecessor ownership remains"
_RETAINED_ENTRY_MISSING = "internal_event_retention_limit: a predecessor pending entry is no longer retained"
_HANDOVER_INCOMPLETE = "Internal event progress handover verification failed"
_HANDOVER_GROUP_ABSENT = "Internal event predecessor group unexpectedly remains after handover"
_SUCCESSOR_ALREADY_EXECUTED = "Successor consumer already recorded an effect while predecessor ownership remains"
_RETAINED_STREAM_PAGE_SIZE = 256
_PENDING_PAGE_SIZE = 128
_CLAIM_BATCH_SIZE = 64


@dataclass(frozen=True)
class _GroupInfo:
    last_delivered_id: str | None


def predecessor_group_name(computer: str) -> str:
    """The previous daemon EventBus reader group for one computer."""
    return f"event-bus:daemon:{computer}"


async def prepare_internal_event_handover(
    redis_client: Any,
    *,
    stream: str,
    computer: str,
    consumers: Iterable[Consumer],
    event_db: EventDB,
) -> None:
    """Prepare successor groups, import predecessor pending references, then retire local predecessor ownership."""
    names = tuple(consumer.name for consumer in consumers)
    predecessor = predecessor_group_name(computer)
    groups = await _group_info(redis_client, stream)
    old = groups.get(predecessor)
    if old is None:
        for name in names:
            group = consumer_group_name(name, computer)
            if group in groups:
                continue
            await _ensure_group(redis_client, stream, group, "$", computer)
        return

    if old.last_delivered_id is None:
        raise RuntimeError(_GROUP_INFO_MISSING)
    cursor = old.last_delivered_id
    pending_ids = await _pending_ids(redis_client, stream, predecessor)
    event_ids_by_entry = await _retained_event_ids(redis_client, stream, pending_ids)

    for name in names:
        group = consumer_group_name(name, computer)
        reader = consumer_reader_name(name, computer)
        already_handled = await event_db.handled_event_ids(name, tuple(event_ids_by_entry.values()))
        if already_handled:
            first_handled = min(already_handled)
            raise RuntimeError(f"{_SUCCESSOR_ALREADY_EXECUTED}: consumer={name} event_id={first_handled}")
        existing = groups.get(group)
        if existing is None:
            await _ensure_group(redis_client, stream, group, cursor, computer)
        elif existing.last_delivered_id != cursor:
            raise RuntimeError(f"{_SUCCESSOR_POSITION_CONFLICT}: {group}")

        for start in range(0, len(pending_ids), _CLAIM_BATCH_SIZE):
            batch = pending_ids[start : start + _CLAIM_BATCH_SIZE]
            claimed = await redis_client.xclaim(
                stream,
                group,
                reader,
                0,
                batch,
                justid=True,
                force=True,
                retrycount=0,
            )
            claimed_ids = {_decode(message_id) for message_id in claimed}
            missing = set(batch) - claimed_ids
            if missing:
                first_missing = min(missing)
                logger.error(_RETAINED_ENTRY_MISSING, stream=stream, entry_id=first_missing, group=predecessor)
                raise RuntimeError(f"{_RETAINED_ENTRY_MISSING}: {stream}/{first_missing}")

        verified = await _group_info(redis_client, stream)
        successor = verified.get(group)
        if successor is None or successor.last_delivered_id != cursor:
            raise RuntimeError(f"{_HANDOVER_INCOMPLETE}: successor position {group}")
        imported = await _pending_ids(redis_client, stream, group, consumer=reader)
        if not set(pending_ids).issubset(imported):
            raise RuntimeError(f"{_HANDOVER_INCOMPLETE}: retained IDs {group}")

    await _retained_event_ids(redis_client, stream, pending_ids)
    try:
        await redis_client.xgroup_destroy(stream, predecessor)
    except ResponseError as error:
        if "NOGROUP" not in str(error):
            raise
    remaining = await _group_info(redis_client, stream)
    if predecessor in remaining:
        raise RuntimeError(_HANDOVER_GROUP_ABSENT)
    logger.info(
        "internal_event_progress_handover_complete",
        computer=computer,
        predecessor=predecessor,
        last_delivered_id=cursor,
        pending=len(pending_ids),
        successors=len(names),
    )


async def _ensure_group(redis_client: Any, stream: str, group: str, position: str, computer: str) -> None:
    try:
        await redis_client.xgroup_create(stream, group, id=position, mkstream=True)
    except ResponseError as error:
        if "BUSYGROUP" in str(error):
            info = await _group_info(redis_client, stream)
            existing = info.get(group)
            if existing is None or existing.last_delivered_id != position:
                raise RuntimeError(f"{_SUCCESSOR_POSITION_CONFLICT}: {group}") from error
            return
        raise
    logger.info(
        "internal_event_successor_group_created",
        computer=computer,
        group=group,
        last_delivered_id=position,
    )


async def _group_info(redis_client: Any, stream: str) -> dict[str, _GroupInfo]:
    try:
        raw_groups = await redis_client.xinfo_groups(stream)
    except ResponseError as error:
        if "no such key" in str(error).lower():
            return {}
        raise
    result: dict[str, _GroupInfo] = {}
    for raw in raw_groups:
        if not isinstance(raw, Mapping):
            continue
        raw_name = raw.get(b"name", raw.get("name"))
        raw_position = raw.get(b"last-delivered-id", raw.get("last-delivered-id"))
        name = _decode(raw_name)
        if name:
            position = _decode(raw_position) if raw_position is not None else None
            result[name] = _GroupInfo(position)
    return result


async def _pending_ids(
    redis_client: Any,
    stream: str,
    group: str,
    *,
    consumer: str | None = None,
) -> list[str]:
    cursor = "-"
    result: list[str] = []
    seen: set[str] = set()
    while True:
        rows = await redis_client.xpending_range(
            stream,
            group,
            cursor,
            "+",
            _PENDING_PAGE_SIZE,
            consumer,
        )
        if not rows:
            return result
        last_id: str | None = None
        for row in rows:
            if not isinstance(row, dict) or row.get("message_id") is None:
                continue
            message_id = _decode(row["message_id"])
            last_id = message_id
            if message_id not in seen:
                seen.add(message_id)
                result.append(message_id)
        if last_id is None or len(rows) < _PENDING_PAGE_SIZE:
            return result
        cursor = f"({last_id}"


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value) if value is not None else ""


async def _retained_event_ids(redis_client: Any, stream: str, pending_ids: list[str]) -> dict[str, str]:
    """Read retained predecessor payloads in bounded ranges and resolve each consumer identity."""
    if not pending_ids:
        return {}
    wanted = set(pending_ids)
    found: dict[str, str] = {}
    cursor = pending_ids[0]
    end = pending_ids[-1]
    while wanted - found.keys():
        rows = await redis_client.xrange(stream, min=cursor, max=end, count=_RETAINED_STREAM_PAGE_SIZE)
        if not rows:
            break
        last_id: str | None = None
        for raw_id, raw_fields in rows:
            entry_id = _decode(raw_id)
            last_id = entry_id
            if entry_id not in wanted:
                continue
            found[entry_id] = decode_internal_event_entry(raw_fields, entry_id).id
        if last_id is None:
            break
        cursor = f"({last_id}"
    missing = wanted - found.keys()
    if missing:
        first_missing = min(missing)
        logger.error(_RETAINED_ENTRY_MISSING, stream=stream, entry_id=first_missing)
        raise RuntimeError(f"{_RETAINED_ENTRY_MISSING}: {stream}/{first_missing}")
    return found
