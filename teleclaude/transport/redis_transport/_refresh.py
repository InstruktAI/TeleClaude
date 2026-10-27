"""Remote cache refresh coalescing for RedisTransport."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.core.models import ComputerInfo, JsonDict
from teleclaude.core.reconciliation import decode_capability_set
from teleclaude.core.redis_utils import scan_keys
from teleclaude.core.shell_identity import optional_shell_safe_identifier
from teleclaude.transport.peer_heartbeat import (
    CONVERSATION_ADAPTERS_FIELD,
    PROJECTS_DIGEST_FIELD,
    decode_optional_announced_strings,
)
from teleclaude.types import SystemStats

logger = get_logger(__name__)

_REFRESH_EXCEPTIONS = (RedisError, TimeoutError, OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError)
_PEER_RECORD_FAILED_EVENT = "heartbeat_peer_record_failed"
# One pull answers every one of these, so they share one refresh per peer.
_PROJECTS_DATA_TYPE = "projects"
_SESSIONS_DATA_TYPE = "sessions"
_FIRST_HEARTBEAT_REASON = "first_heartbeat"
_STARTUP_REASON = "startup"
_PROJECTS_DATA_TYPES = frozenset({_PROJECTS_DATA_TYPE, "todos", "preparation"})
_PROJECTS_REFRESH_KEY_TEMPLATE = "{computer}:projects"
DIGEST_CHANGED_REASON = "digest_changed"


if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.models import PeerInfo
    from teleclaude.core.task_registry import TaskRegistry


@dataclass(frozen=True)
class _RefreshRequest:
    """Inputs used to schedule a remote cache refresh."""

    computer: str
    data_type: str
    reason: str
    project_path: str | None = None
    force: bool = False


class _RefreshMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: coalesced remote cache refresh with cooldown and peer loop."""

    if TYPE_CHECKING:
        task_registry: TaskRegistry
        computer_name: str
        heartbeat_interval: int
        _running: bool
        _refresh_last: dict[str, float]
        _refresh_tasks: dict[str, asyncio.Task[object]]
        _bootstrapped: set[tuple[str, str]]
        _pulled_projects_digest: dict[str, str]
        _refresh_cooldown_seconds: float
        _ALLOWED_REFRESH_REASONS: set[str]

        @property
        def cache(self) -> DaemonCache | None:
            """Return the shared daemon cache."""
            raise NotImplementedError

        async def discover_peers(self) -> list[PeerInfo]:
            """Discover peers currently online via Redis heartbeats."""
            raise NotImplementedError

        async def pull_remote_projects_with_todos(self, computer: str) -> bool:
            """Refresh projects and todos for one peer; True only on success."""
            _ = computer
            raise NotImplementedError

        async def pull_remote_sessions(self, computer: str) -> bool:
            """Pull sessions from one peer (bootstrap path); True only on success."""
            _ = computer
            raise NotImplementedError

        async def _get_redis(self) -> Redis:
            """Return an active Redis client."""
            raise NotImplementedError

    async def refresh_remote_snapshot(self) -> None:
        """Refresh remote computers and project/todo cache (best effort)."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping remote snapshot refresh")
            return

        logger.info("Refreshing remote cache snapshot...")

        peers = await self.discover_peers()
        for peer in peers:
            computer_info = ComputerInfo(
                name=peer.name,
                status="online",
                user=peer.user,
                host=peer.host,
                role=peer.role,
                system_stats=peer.system_stats,
                version=peer.version,
                channel=peer.channel,
                capability_set=peer.capability_set,
                is_master=peer.is_master,
                conversation_adapters=peer.conversation_adapters,
            )
            self.cache.update_computer(computer_info)

        for peer in peers:
            try:
                self._schedule_refresh(
                    _RefreshRequest(peer.name, _PROJECTS_DATA_TYPE, _STARTUP_REASON, force=True),
                    on_success=lambda name=peer.name: self._bootstrapped.add((name, _PROJECTS_DATA_TYPE)),
                )
                self._schedule_refresh(
                    _RefreshRequest(peer.name, _SESSIONS_DATA_TYPE, _STARTUP_REASON, force=True),
                    on_success=lambda name=peer.name: self._bootstrapped.add((name, _SESSIONS_DATA_TYPE)),
                )
            except _REFRESH_EXCEPTIONS as e:
                logger.warning("Failed to refresh snapshot from %s: %s", peer.name, e)

        logger.info("Remote cache snapshot refresh complete: %d computers", len(peers))

    def request_refresh(
        self,
        computer: str,
        data_type: str,
        *,
        reason: str,
        project_path: str | None = None,
    ) -> bool:
        """Request a remote refresh if the reason is allowed and cooldown permits it."""
        return self._schedule_refresh(_RefreshRequest(computer, data_type, reason, project_path=project_path))

    def _schedule_refresh(
        self,
        request: _RefreshRequest,
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Coalesce refresh requests by peer+data type and enforce cooldown."""
        if request.reason not in self._ALLOWED_REFRESH_REASONS:
            logger.warning(
                "Skipping refresh for %s:%s: reason not allowed (%s)",
                request.computer,
                request.data_type,
                request.reason,
            )
            return False

        if request.computer in ("local", self.computer_name):
            return False

        key = self._refresh_key(request.computer, request.data_type, request.project_path)
        if not self._can_schedule_refresh(key, force=request.force):
            logger.debug("Refresh skipped for %s (reason=%s, force=%s)", key, request.reason, request.force)
            return False

        coro = self._build_refresh_coro(request.computer, request.data_type, request.project_path)
        if coro is None:
            logger.warning(
                "Skipping refresh for %s:%s (reason=%s): unsupported data type",
                request.computer,
                request.data_type,
                request.reason,
            )
            return False

        self._refresh_last[key] = time.monotonic()

        async def _refresh_wrapper() -> None:
            try:
                succeeded = await coro
            except _REFRESH_EXCEPTIONS as exc:
                logger.warning("Refresh failed for %s (reason=%s): %s", key, request.reason, exc)
            else:
                # on_success records the peer as bootstrapped; only fire it when the
                # pull genuinely answered, so a failed first heartbeat retries on the
                # next one instead of being recorded as a completed warm-up.
                if succeeded and on_success:
                    on_success()

        task = self._spawn_refresh_task(_refresh_wrapper(), key=key)
        self._refresh_tasks[key] = task
        return True

    def _projects_pulled(self, computer: str, digest: str) -> None:
        """Record the digest a peer advertised when its projects were pulled, so an unchanged digest pulls nothing."""
        self._pulled_projects_digest[computer] = digest
        self._bootstrapped.add((computer, _PROJECTS_DATA_TYPE))

    def _refresh_key(self, computer: str, data_type: str, project_path: str | None) -> str:
        if data_type in _PROJECTS_DATA_TYPES:
            return _PROJECTS_REFRESH_KEY_TEMPLATE.format(computer=computer)
        if project_path:
            return f"{computer}:{data_type}:{project_path}"
        return f"{computer}:{data_type}"

    def _can_schedule_refresh(self, key: str, *, force: bool) -> bool:
        task = self._refresh_tasks.get(key)
        if task and not task.done():
            return False
        if force:
            return True
        last = self._refresh_last.get(key)
        if last is None:
            return True
        return (time.monotonic() - last) >= self._refresh_cooldown_seconds

    def _build_refresh_coro(self, computer: str, data_type: str, _project_path: str | None) -> Awaitable[bool] | None:
        if data_type in ("projects", "preparation"):
            return self.pull_remote_projects_with_todos(computer)
        if data_type == "todos":
            return self.pull_remote_projects_with_todos(computer)
        if data_type == "sessions":
            return self.pull_remote_sessions(computer)
        return None

    def _spawn_refresh_task(self, coro: Awaitable[None], *, key: str) -> asyncio.Task[object]:
        task = self.task_registry.spawn(coro, name=f"redis-refresh-{key}")  # type: ignore[var-annotated]

        def _cleanup(_task: asyncio.Task[object]) -> None:
            self._refresh_tasks.pop(key, None)

        task.add_done_callback(_cleanup)
        return task

    async def _peer_refresh_loop(self) -> None:
        """Background task: refresh peer cache from heartbeats."""
        while self._running:
            try:
                await self.refresh_peers_from_heartbeats()
            except asyncio.CancelledError:
                break
            except _REFRESH_EXCEPTIONS as e:
                logger.error("Peer refresh failed: %s", e)

            # Always sleep interval, even on error, to prevent tight loops
            await asyncio.sleep(self.heartbeat_interval)

    async def refresh_peers_from_heartbeats(self) -> None:
        """Refresh peer cache from heartbeat keys."""
        if not self.cache:
            logger.warning("Cache unavailable, skipping peer refresh from heartbeats")
            return

        redis_client = await self._get_redis()
        keys: object = await scan_keys(redis_client, b"computer:*:heartbeat")
        if not keys:
            return

        for key in keys:  # pyright: ignore[reportGeneralTypeIssues]
            try:
                data_bytes: object = await redis_client.get(key)
                # Heartbeat key TTL (60s) can expire between SCAN and GET — skip vanished keys.
                if not data_bytes:
                    continue
                try:
                    data_str: str = data_bytes.decode("utf-8")  # pyright: ignore[reportAttributeAccessIssue]
                    info_obj: object = json.loads(data_str)
                    info = cast(JsonDict, info_obj)

                    computer_name = cast(str, info["computer_name"])
                    if computer_name == self.computer_name:
                        continue

                    computer_info = ComputerInfo(
                        name=computer_name,
                        status="online",
                        user=optional_shell_safe_identifier(info.get("user"), "heartbeat user"),
                        host=optional_shell_safe_identifier(info.get("host"), "heartbeat host"),
                        role=cast("str | None", info.get("role")),
                        system_stats=cast(SystemStats | None, info.get("system_stats")),
                        version=cast("str | None", info.get("version")),
                        channel=cast("str | None", info.get("channel")),
                        capability_set=decode_capability_set(info.get("capability_set")),
                        is_master=(cast(bool, info["is_master"]) if isinstance(info.get("is_master"), bool) else None),
                        conversation_adapters=decode_optional_announced_strings(info.get(CONVERSATION_ADAPTERS_FIELD)),
                    )
                except _REFRESH_EXCEPTIONS:
                    raise
                except Exception:
                    # An unrecognized interpretation failure skips this record, never the pass.
                    logger.exception(_PEER_RECORD_FAILED_EVENT, heartbeat_key=key)
                    continue
                self.cache.update_computer(computer_info)

                advertised_digest = info.get(PROJECTS_DIGEST_FIELD)
                advertises_digest = isinstance(advertised_digest, str) and bool(advertised_digest)
                if advertises_digest and isinstance(advertised_digest, str):
                    if self._pulled_projects_digest.get(computer_name) != advertised_digest:
                        self._schedule_refresh(
                            _RefreshRequest(computer_name, _PROJECTS_DATA_TYPE, DIGEST_CHANGED_REASON, force=True),
                            on_success=lambda p=computer_name, d=advertised_digest: self._projects_pulled(p, d),
                        )

                for data_type in (_PROJECTS_DATA_TYPE, _SESSIONS_DATA_TYPE):
                    if (computer_name, data_type) in self._bootstrapped:
                        continue
                    if data_type == _PROJECTS_DATA_TYPE and advertises_digest:
                        continue
                    self._schedule_refresh(
                        _RefreshRequest(computer_name, data_type, _FIRST_HEARTBEAT_REASON, force=True),
                        on_success=lambda p=computer_name, d=data_type: self._bootstrapped.add((p, d)),
                    )
            except _REFRESH_EXCEPTIONS as exc:
                logger.warning("Heartbeat peer parse failed: %s", exc)
                continue
