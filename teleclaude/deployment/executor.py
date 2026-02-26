"""Deployment update executor — pull/checkout, migrate, install, restart."""

from __future__ import annotations

import asyncio
import json
import os
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.deployment.migration_runner import run_migrations

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_version_from_pyproject() -> str:
    """Read version from pyproject.toml on disk (reflects post-pull state)."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = data.get("project", {})
        if isinstance(project, dict):
            ver = project.get("version")
            if isinstance(ver, str) and ver:
                return ver
    except Exception:  # noqa: BLE001 - version read is best-effort
        pass
    return "0.0.0"


async def _set_status(redis: "Redis", status_key: str, payload: dict) -> None:  # type: ignore[type-arg]
    try:
        await redis.set(status_key, json.dumps(payload))
    except Exception as exc:  # noqa: BLE001 - status updates are informational
        logger.warning("Failed to update deploy status: %s", exc)


async def execute_update(
    channel: str,
    version_info: dict,  # type: ignore[type-arg]
    *,
    get_redis: Callable[[], Awaitable["Redis"]] | None = None,
) -> None:
    """Execute deployment update: pull/checkout → migrate → install → restart.

    Args:
        channel: Deployment channel (alpha/beta/stable).
        version_info: Dict with ``from_version`` and ``version`` (target).
        get_redis: Optional async callable returning a Redis client for status updates.
    """
    from_version = version_info.get("from_version", "0.0.0")
    target_version = version_info.get("version", "")

    status_key = f"system_status:{config.computer.name}:deploy"

    async def update_status(payload: dict) -> None:  # type: ignore[type-arg]
        if get_redis is None:
            return
        try:
            redis = await get_redis()
            await _set_status(redis, status_key, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Deploy status update failed: %s", exc)

    try:
        await update_status({"status": "updating", "timestamp": time.time()})
        logger.info("Deploy: starting update (channel=%s, from=%s, to=%s)", channel, from_version, target_version)

        if channel == "alpha":
            result = await asyncio.create_subprocess_exec(
                "git",
                "pull",
                "--ff-only",
                "origin",
                "main",
                cwd=_REPO_ROOT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()
            if result.returncode != 0:
                err = stderr.decode().strip() or stdout.decode().strip()
                logger.error("Deploy: git pull --ff-only failed: %s", err)
                await update_status({"status": "update_failed", "error": f"git pull --ff-only failed: {err}"})
                return
            logger.info("Deploy: git pull successful")
            target_version = _read_version_from_pyproject()
        else:
            # beta / stable — checkout tag
            tag = f"v{target_version}" if target_version and not target_version.startswith("v") else target_version
            fetch = await asyncio.create_subprocess_exec(
                "git",
                "fetch",
                "--tags",
                cwd=_REPO_ROOT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, fetch_err = await fetch.communicate()
            if fetch.returncode != 0:
                logger.error("Deploy: git fetch --tags failed: %s", fetch_err.decode().strip())
                await update_status(
                    {"status": "update_failed", "error": f"git fetch failed: {fetch_err.decode().strip()}"}
                )
                return

            checkout = await asyncio.create_subprocess_exec(
                "git",
                "checkout",
                tag,
                cwd=_REPO_ROOT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, checkout_err = await checkout.communicate()
            if checkout.returncode != 0:
                err = checkout_err.decode().strip()
                logger.error("Deploy: git checkout %s failed: %s", tag, err)
                await update_status({"status": "update_failed", "error": f"git checkout {tag} failed: {err}"})
                return
            logger.info("Deploy: checked out %s", tag)

        # Run migrations
        await update_status({"status": "migrating", "timestamp": time.time()})
        logger.info("Deploy: running migrations from %s to %s", from_version, target_version)
        migration_result = await asyncio.to_thread(run_migrations, from_version, target_version)
        if migration_result.get("error"):
            err = migration_result["error"]
            logger.error("Deploy: migration failed: %s", err)
            await update_status({"status": "update_failed", "error": f"migration failed: {err}"})
            return
        logger.info(
            "Deploy: migrations complete (run=%d, skipped=%d)",
            migration_result.get("migrations_run", 0),
            migration_result.get("migrations_skipped", 0),
        )

        # Install
        await update_status({"status": "installing", "timestamp": time.time()})
        logger.info("Deploy: running make install...")
        install = await asyncio.create_subprocess_exec(
            "make",
            "install",
            cwd=_REPO_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, install_err = await asyncio.wait_for(install.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            logger.error("Deploy: make install timed out after 60s")
            await update_status({"status": "update_failed", "error": "make install timed out"})
            return

        if install.returncode != 0:
            err = install_err.decode().strip()
            logger.error("Deploy: make install failed: %s", err)
            await update_status({"status": "update_failed", "error": f"make install failed: {err}"})
            return
        logger.info("Deploy: make install successful")

        # Restart
        await update_status({"status": "restarting", "timestamp": time.time()})
        logger.info("Deploy: exiting with code 42 to trigger service manager restart")
        os._exit(42)

    except Exception as exc:
        logger.error("Deploy: unexpected failure: %s", exc, exc_info=True)
        await update_status({"status": "update_failed", "error": str(exc)})


__all__ = ["execute_update"]
