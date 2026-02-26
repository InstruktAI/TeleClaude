"""Deployment webhook handler — receives GitHub events and triggers updates."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import HookEvent
from teleclaude.utils import resolve_project_config_path

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

# Well-known Redis Stream key for deployment fan-out across daemons.
DEPLOYMENT_FANOUT_CHANNEL = "deployment:version_available"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Module-level state injected by daemon at startup.
_dispatch: Callable[[HookEvent], Awaitable[None]] | None = None
_get_redis: Callable[[], Awaitable["Redis"]] | None = None


def configure_deployment_handler(
    dispatch: Callable[[HookEvent], Awaitable[None]],
    get_redis: Callable[[], Awaitable["Redis"]] | None = None,
) -> None:
    """Inject dispatcher and Redis accessor at daemon startup."""
    global _dispatch, _get_redis
    _dispatch = dispatch
    _get_redis = get_redis


def _extract_release_version(event: HookEvent) -> str:
    """Extract tag version from a GitHub release event payload."""
    release = event.payload.get("release")
    if isinstance(release, dict):
        tag = release.get("tag_name")
        if isinstance(tag, str) and tag:
            return tag.lstrip("v")
    return ""


def _is_within_pinned_minor(version: str, pinned_minor: str) -> bool:
    """Return True when version falls within the pinned minor series (e.g. '1.2.5' in '1.2')."""
    if not version or not pinned_minor:
        return False
    expected_prefix = f"{pinned_minor}."
    return version.startswith(expected_prefix) and version.count(".") == 2


async def handle_deployment_event(event: HookEvent) -> None:
    """Handle GitHub push/release events and deployment fan-out events.

    Decision matrix:
        alpha  + push to main          → update
        beta   + release published     → update
        stable + release in pinned minor → update
        otherwise                      → skip

    Fan-out:
        github source  → publish version_available to Redis + execute locally
        deployment source → execute locally only (prevents re-broadcast loops)
    """
    from teleclaude.config.loader import load_project_config

    project_cfg_path = resolve_project_config_path(_PROJECT_ROOT)
    try:
        project_config = load_project_config(project_cfg_path)
    except Exception as exc:  # noqa: BLE001 - config load failure is non-fatal
        logger.error("Deployment handler: failed to load project config: %s", exc)
        return

    channel = project_config.deployment.channel
    pinned_minor = project_config.deployment.pinned_minor

    should_update = False
    version_info: dict = {}  # type: ignore[type-arg]

    from teleclaude import __version__

    if event.source == "github":
        if channel == "alpha":
            ref = event.properties.get("ref") or ""
            should_update = event.type == "push" and ref == "refs/heads/main"
            if should_update:
                version_info = {"channel": "alpha", "from_version": __version__, "version": ""}
        elif channel in ("beta", "stable"):
            action = event.properties.get("action") or ""
            if event.type == "release" and action == "published":
                release_version = _extract_release_version(event)
                if channel == "beta":
                    should_update = bool(release_version)
                else:  # stable
                    should_update = _is_within_pinned_minor(release_version, pinned_minor)
                if should_update:
                    version_info = {"channel": channel, "from_version": __version__, "version": release_version}

    elif event.source == "deployment" and event.type == "version_available":
        # Fan-out received from another daemon via Redis.
        version_info_raw = event.properties.get("version_info") or ""
        if isinstance(version_info_raw, str):
            import json

            try:
                version_info = json.loads(version_info_raw)
            except Exception:  # noqa: BLE001
                version_info = {}

        fan_channel = event.properties.get("channel") or ""
        fan_version = event.properties.get("version") or ""
        from_version = event.properties.get("from_version") or __version__

        if not version_info:
            version_info = {"channel": fan_channel, "from_version": str(from_version), "version": str(fan_version)}

        # Re-evaluate should_update based on own channel config.
        if channel == "alpha" and version_info.get("channel") == "alpha":
            should_update = True
        elif channel in ("beta", "stable") and version_info.get("channel") in ("beta", "stable"):
            target_ver = str(version_info.get("version", ""))
            if channel == "beta":
                should_update = bool(target_ver)
            else:
                should_update = _is_within_pinned_minor(target_ver, pinned_minor)
    else:
        logger.debug("Deployment handler: skipping event source=%s type=%s", event.source, event.type)
        return

    if not should_update:
        logger.debug(
            "Deployment handler: no update for channel=%s source=%s type=%s action=%s",
            channel,
            event.source,
            event.type,
            event.properties.get("action"),
        )
        return

    # Fan-out: when receiving directly from GitHub, broadcast to other daemons via Redis.
    if event.source == "github" and _get_redis is not None:
        await _publish_fanout(version_info)

    # Execute update locally.
    from teleclaude.deployment.executor import execute_update

    logger.info("Deployment handler: triggering update (channel=%s)", channel)
    asyncio.create_task(execute_update(channel, version_info, get_redis=_get_redis))


async def _publish_fanout(version_info: dict) -> None:  # type: ignore[type-arg]
    """Publish a version_available event to the Redis fan-out stream."""
    if _get_redis is None:
        logger.debug("Deployment handler: Redis unavailable, skipping fan-out")
        return
    try:
        redis = await _get_redis()
        fanout_event = HookEvent.now(
            source="deployment",
            type="version_available",
            properties={
                "channel": str(version_info.get("channel", "")),
                "version": str(version_info.get("version", "")),
                "from_version": str(version_info.get("from_version", "")),
            },
        )
        await redis.xadd(DEPLOYMENT_FANOUT_CHANNEL, {"event": fanout_event.to_json()})
        logger.info("Deployment handler: published version_available to %s", DEPLOYMENT_FANOUT_CHANNEL)
    except Exception as exc:  # noqa: BLE001 - fan-out is best-effort
        logger.warning("Deployment handler: fan-out publish failed: %s", exc)


__all__ = [
    "configure_deployment_handler",
    "handle_deployment_event",
    "DEPLOYMENT_FANOUT_CHANNEL",
]
