"""Deployment service (git pull + install + restart)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.transport.redis_transport import RedisTransport

logger = get_logger(__name__)


class DeployStatusPayload(TypedDict):
    """Deployment status payload - sent to Redis during deployment lifecycle."""

    status: str
    timestamp: float


class DeployErrorPayload(TypedDict):
    """Deployment error payload - sent to Redis when deployment fails."""

    status: str
    error: str


class DeployService:
    """Execute deployment with status updates."""

    def __init__(self, *, redis_transport: RedisTransport) -> None:
        self._redis_transport = redis_transport

    async def deploy(self) -> None:
        """Execute deployment: git pull + make install + restart via exit code."""
        status_key = f"system_status:{config.computer.name}:deploy"
        redis_client = await self._redis_transport._get_redis()

        async def update_status(payload: DeployStatusPayload | DeployErrorPayload) -> None:
            await redis_client.set(status_key, json.dumps(payload))

        try:
            deploying_payload: DeployStatusPayload = {"status": "deploying", "timestamp": time.time()}
            await update_status(deploying_payload)
            logger.info("Deploy: marked status as deploying")

            logger.info("Deploy: executing git pull...")

            await asyncio.create_subprocess_exec(
                "git",
                "config",
                "pull.rebase",
                "false",
                cwd=Path(__file__).parent.parent,
            )

            result = await asyncio.create_subprocess_exec(
                "git",
                "pull",
                "--no-edit",
                cwd=Path(__file__).parent.parent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode != 0:
                stdout_msg = stdout.decode("utf-8").strip()
                stderr_msg = stderr.decode("utf-8").strip()
                error_msg = f"{stderr_msg}\n{stdout_msg}".strip()
                logger.error("Deploy: git pull failed: %s", error_msg)
                git_error_payload: DeployErrorPayload = {
                    "status": "error",
                    "error": f"git pull failed: {error_msg}",
                }
                await update_status(git_error_payload)
                return

            output = stdout.decode("utf-8")
            logger.info("Deploy: git pull successful - %s", output.strip())

            logger.info("Deploy: running make install...")
            install_result = await asyncio.create_subprocess_exec(
                "make",
                "install",
                cwd=Path(__file__).parent.parent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                install_stdout, install_stderr = await asyncio.wait_for(
                    install_result.communicate(),
                    timeout=60.0,
                )  # type: ignore[misc]
            except asyncio.TimeoutError:
                logger.error("Deploy: make install timed out after 60s")
                timeout_payload: DeployErrorPayload = {
                    "status": "error",
                    "error": "make install timed out after 60s",
                }
                await update_status(timeout_payload)
                return

            if install_result.returncode != 0:
                error_msg = install_stderr.decode("utf-8")
                logger.error("Deploy: make install failed: %s", error_msg)
                install_error_payload: DeployErrorPayload = {
                    "status": "error",
                    "error": f"make install failed: {error_msg}",
                }
                await update_status(install_error_payload)
                return

            install_output = install_stdout.decode("utf-8")
            logger.info("Deploy: make install successful - %s", install_output.strip())

            restarting_payload: DeployStatusPayload = {"status": "restarting", "timestamp": time.time()}
            await update_status(restarting_payload)

            logger.info("Deploy: exiting with code 42 to trigger service manager restart")
            os._exit(42)

        except Exception as exc:
            logger.error("Deploy failed: %s", exc, exc_info=True)
            exception_payload: DeployErrorPayload = {"status": "error", "error": str(exc)}
            await update_status(exception_payload)
