"""Sandbox container lifecycle manager — Docker sidecar for experimental cartridges.

Manages start/stop/health-check of the teleclaude-sandbox-runner Docker container.
Also provides cartridge directory scanning and watching.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib import import_module
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.events.sandbox.protocol import SandboxRequest, SandboxResponse, read_frame, request_to_dict, write_frame

if TYPE_CHECKING:
    from teleclaude.events.producer import EventProducer

logger = get_logger(__name__)

_HEALTH_INTERVAL = 30.0  # seconds between health checks
_HEALTH_TIMEOUT = 2.0  # seconds for ping response
_SOCKET_WAIT_TIMEOUT = 5.0  # seconds to wait for socket after container start
_SOCKET_POLL_INTERVAL = 0.1  # seconds between socket polls
_MAX_RESTART_ATTEMPTS = 3
_CARTRIDGE_POLL_INTERVAL = 5.0  # seconds between directory scans


@dataclass
class _SandboxContainerState:
    """Mutable runtime state for the sandbox sidecar lifecycle."""

    container_id: str | None = None
    restart_count: int = 0
    permanently_failed: bool = False
    docker_unavailable: bool = False
    has_cartridges: bool = False


def scan_cartridges(cartridges_dir: str) -> list[str]:
    """Return list of cartridge stems (*.py filenames without extension) in the directory.

    Returns empty list if directory is absent.
    """
    path = Path(cartridges_dir)
    if not path.exists():
        return []
    return sorted(p.stem for p in path.iterdir() if p.suffix == ".py" and p.is_file())


class SandboxContainerManager:
    """Manage the sandbox sidecar container and monitor its health and cartridge directory."""

    def __init__(
        self,
        socket_path: str,
        cartridges_dir: str,
        image: str = "teleclaude-sandbox-runner",
        producer: EventProducer | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._cartridges_dir = str(Path(cartridges_dir).expanduser())
        self._image = image
        self._producer = producer
        self._state = _SandboxContainerState()

    @property
    def socket_path(self) -> str:
        """Return the Unix-socket path used by the sandbox runner."""
        return self._socket_path

    @property
    def is_running(self) -> bool:
        """Return whether the sandbox container currently has a known container id."""
        return self._state.container_id is not None

    @property
    def has_cartridges(self) -> bool:
        """Return whether any sandbox cartridges are currently present on disk."""
        return self._state.has_cartridges

    @property
    def permanently_failed(self) -> bool:
        """Return whether the sandbox sidecar has exceeded its restart budget."""
        return self._state.permanently_failed

    @property
    def docker_unavailable(self) -> bool:
        """Return whether Docker is unavailable on the host."""
        return self._state.docker_unavailable

    @property
    def cartridges_dir(self) -> str:
        """Return the watched sandbox cartridge directory."""
        return self._cartridges_dir

    def _check_docker_available(self) -> bool:
        """Return whether `docker info` succeeds on the host."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    async def start(self) -> None:
        """Start the sandbox sidecar if it is needed and healthy."""
        if self._state.docker_unavailable or self._state.permanently_failed:
            return
        if self.is_running:
            return

        if not self._check_docker_available():
            logger.warning("Docker not available — sandbox container disabled")
            self._state.docker_unavailable = True
            await self._emit_event("system.sandbox-container.docker-unavailable", "Docker not available or not running")
            return

        socket_dir = str(Path(self._socket_path).parent)
        codebase_root = str(Path(__file__).parents[2])
        cartridges_dir = str(Path(self._cartridges_dir).expanduser())

        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--name",
            "teleclaude-sandbox-runner",
            "-v",
            f"{codebase_root}:/repo:ro",
            "-v",
            f"{cartridges_dir}:/sandbox-cartridges:ro",
            "-v",
            f"{socket_dir}:/run/sandbox:rw",
            "-e",
            f"SANDBOX_SOCKET_PATH=/run/sandbox/{Path(self._socket_path).name}",
            "-e",
            "SANDBOX_CARTRIDGES_DIR=/sandbox-cartridges",
        ]

        # Optional: mount AI credentials if present
        ai_creds = Path.home() / ".teleclaude" / "credentials" / "ai.json"
        if ai_creds.exists():
            cmd += ["-v", f"{ai_creds}:/run/credentials/ai.json:ro"]

        cmd.append(self._image)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"docker run failed: {result.stderr.strip()}")
            self._state.container_id = result.stdout.strip()
            logger.info("Sandbox container started: %s", self._state.container_id[:12])
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise RuntimeError(f"Failed to start sandbox container: {exc}") from exc

        # Wait for socket to appear
        deadline = asyncio.get_event_loop().time() + _SOCKET_WAIT_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            if Path(self._socket_path).exists():
                logger.info("Sandbox runner socket ready")
                return
            await asyncio.sleep(_SOCKET_POLL_INTERVAL)

        # Timed out waiting — stop container and fail
        await self.stop()
        raise RuntimeError(f"Timed out waiting for sandbox socket at {self._socket_path}")

    async def stop(self) -> None:
        """Stop the running sandbox sidecar, if any."""
        if self._state.container_id is None:
            return
        container_id = self._state.container_id
        self._state.container_id = None
        try:
            subprocess.run(
                ["docker", "stop", "--time", "5", container_id],
                capture_output=True,
                check=False,
                timeout=10,
            )
            logger.info("Sandbox container stopped: %s", container_id[:12])
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as exc:
            logger.warning("Failed to stop sandbox container %s: %s", container_id[:12], exc)

    async def health_check(self) -> bool:
        """Check whether the sandbox runner responds successfully to a ping."""
        if not self.is_running:
            return False
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket_path),
                timeout=_HEALTH_TIMEOUT,
            )
            request = SandboxRequest(cartridge_name="__ping__", envelope={}, catalog_snapshot=[])
            await write_frame(writer, request_to_dict(request))
            raw = await asyncio.wait_for(read_frame(reader), timeout=_HEALTH_TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            response = SandboxResponse(
                envelope=raw.get("envelope"),  # type: ignore[arg-type]
                error=raw.get("error"),  # type: ignore[arg-type]
                duration_ms=raw.get("duration_ms", 0.0),  # type: ignore[arg-type]
            )
            return response.error is None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Sandbox health check failed: %s", exc)
            return False

    async def restart(self) -> None:
        """Restart the sandbox sidecar and trip permanent failure if retries are exhausted."""
        self._state.restart_count += 1
        logger.warning("Sandbox container restart attempt %d/%d", self._state.restart_count, _MAX_RESTART_ATTEMPTS)

        await self.stop()

        if self._state.restart_count > _MAX_RESTART_ATTEMPTS:
            logger.error("Sandbox container permanently failed after %d restarts", self._state.restart_count - 1)
            self._state.permanently_failed = True
            await self._emit_event(
                "system.sandbox-container.unhealthy",
                f"Sandbox container failed {self._state.restart_count - 1} consecutive health checks",
            )
            return

        try:
            await self.start()
            self._state.restart_count = 0
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Sandbox container restart failed: %s", exc)
            if self._state.restart_count >= _MAX_RESTART_ATTEMPTS:
                self._state.permanently_failed = True
                await self._emit_event(
                    "system.sandbox-container.unhealthy",
                    f"Sandbox container restart failed after {_MAX_RESTART_ATTEMPTS} attempts: {exc}",
                )

    async def watch_health(self, shutdown_event: asyncio.Event) -> None:
        """Monitor the running sandbox container and restart it on failed health checks."""
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(shutdown_event.wait()), timeout=_HEALTH_INTERVAL)
                return  # shutdown requested
            except TimeoutError:
                pass

            if self._state.permanently_failed or self._state.docker_unavailable:
                continue

            if self.is_running and not await self.health_check():
                logger.warning("Sandbox container health check failed — restarting")
                await self.restart()

    async def watch_cartridges_dir(self, shutdown_event: asyncio.Event) -> None:
        """Monitor the cartridge directory and start or stop the sidecar on changes."""
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(asyncio.shield(shutdown_event.wait()), timeout=_CARTRIDGE_POLL_INTERVAL)
                return  # shutdown requested
            except TimeoutError:
                pass

            cartridges = scan_cartridges(self._cartridges_dir)
            had_cartridges = self._state.has_cartridges
            self._state.has_cartridges = len(cartridges) > 0

            if (
                self._state.has_cartridges
                and not self.is_running
                and not self._state.permanently_failed
                and not self._state.docker_unavailable
            ):
                logger.info("Sandbox cartridges detected — starting container")
                try:
                    await self.start()
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to start sandbox container: %s", exc)

            elif not self._state.has_cartridges and had_cartridges and self.is_running:
                logger.info("Sandbox cartridges removed — stopping container")
                await self.stop()

    async def _emit_event(self, event_type: str, description: str) -> None:
        """Emit a system event describing sandbox container health changes."""
        if self._producer is None:
            logger.warning("Sandbox event not emitted (no producer): %s — %s", event_type, description)
            return
        envelope_module = import_module("teleclaude.events.envelope")

        try:
            await self._producer.emit(
                envelope_module.EventEnvelope(
                    event=event_type,
                    source="sandbox-container-manager",
                    level=envelope_module.EventLevel.OPERATIONAL,
                    domain="system",
                    description=description,
                    visibility=envelope_module.EventVisibility.LOCAL,
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to emit sandbox event %s: %s", event_type, exc)
