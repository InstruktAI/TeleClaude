"""Request/response pattern and observation signalling for RedisTransport."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict, MessageMetadata
from teleclaude.core.origins import InputOrigin

logger = get_logger(__name__)

if TYPE_CHECKING:
    from redis.asyncio import Redis


class _RequestResponseMixin:  # pyright: ignore[reportUnusedClass]
    """Mixin: request/response pattern, observation, and system commands."""

    if TYPE_CHECKING:
        computer_name: str
        message_stream_maxlen: int
        output_stream_maxlen: int

        async def _get_redis(self) -> Redis: ...

    # === Session Observation (Interest Window) ===

    async def signal_observation(
        self,
        target_computer: str,
        session_id: str,
        duration_seconds: int,
    ) -> None:
        """Signal interest in observing a session on target computer.

        Creates a Redis key with TTL that tells the target computer
        to broadcast session output to Redis stream during the observation window.

        Args:
            target_computer: Computer hosting the session
            session_id: Session to observe
            duration_seconds: How long to observe (TTL for Redis key)
        """

        key = f"observation:{target_computer}:{session_id}"
        observation_data: JsonDict = {
            "observer": self.computer_name,
            "started_at": time.time(),
        }
        data = json.dumps(observation_data)

        # Set key with TTL - auto-expires after duration
        redis_client = await self._get_redis()
        await redis_client.setex(key, duration_seconds, data)
        logger.info(
            "Signaled observation: %s observing %s on %s for %ds",
            self.computer_name,
            session_id,
            target_computer,
            duration_seconds,
        )

    async def is_session_observed(self, session_id: str) -> bool:
        """Check if any observer is watching this session.

        Args:
            session_id: Session ID to check

        Returns:
            True if someone is observing this session
        """

        key = f"observation:{self.computer_name}:{session_id}"
        redis_client = await self._get_redis()
        exists = await redis_client.exists(key)
        return bool(exists)

    # === Request/Response pattern for ephemeral queries (list_projects, etc.) ===

    async def send_request(
        self,
        computer_name: str,
        command: str,
        metadata: MessageMetadata,
        session_id: str | None = None,
        args: list[str] | None = None,
    ) -> str:
        """Send request to remote computer's message stream.

        Used for ephemeral queries (list_projects, etc.) and session commands.

        Args:
            computer_name: Target computer name
            command: Command to send
            session_id: Optional TeleClaude session ID (for session commands)
            metadata: Optional metadata (title, project_path for session creation)
            args: Optional command arguments (e.g., project_path for list_todos)

        Returns:
            Redis stream entry ID (used for response correlation)
        """

        message_stream = f"messages:{computer_name}"

        # Build message data
        data: dict[bytes, bytes] = {
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"initiator": self.computer_name.encode("utf-8"),
        }

        # Add session_id if provided (for session commands)
        if session_id:
            data[b"session_id"] = session_id.encode("utf-8")

        # Add command arguments if provided
        if args:
            data[b"args"] = json.dumps(args).encode("utf-8")

        # Add optional session creation metadata
        if metadata.title:
            data[b"title"] = metadata.title.encode("utf-8")
        if metadata.project_path:
            data[b"project_path"] = metadata.project_path.encode("utf-8")
        if metadata.channel_metadata:
            data[b"channel_metadata"] = json.dumps(metadata.channel_metadata).encode("utf-8")
        if metadata.launch_intent:
            data[b"launch_intent"] = json.dumps(metadata.launch_intent.to_dict()).encode("utf-8")
        origin = metadata.origin or InputOrigin.REDIS.value
        data[b"origin"] = origin.encode("utf-8")

        # Send to Redis stream - XADD returns unique message_id
        # This message_id is used for response correlation (receiver sends response to output:{computer}:{message_id})
        redis_client = await self._get_redis()
        message_id_bytes: bytes = await redis_client.xadd(message_stream, data, maxlen=self.message_stream_maxlen)  # pyright: ignore[reportArgumentType]  # pyright: ignore[reportArgumentType]
        message_id = message_id_bytes.decode("utf-8")

        logger.trace("Redis request enqueued", stream=message_stream, message_id=message_id)
        logger.debug(
            "Redis request sent",
            target=computer_name,
            request_id=message_id[:15],
            command=command[:50],
        )
        return message_id

    async def send_response(self, message_id: str, data: str) -> str:
        """Send response for an ephemeral request directly to Redis stream.

        Used by command handlers (list_projects, etc.) to respond without DB session.

        Args:
            message_id: Redis stream entry ID from the original request
            data: Response data (typically JSON)

        Returns:
            Redis stream entry ID of the response
        """

        output_stream = f"output:{self.computer_name}:{message_id}"
        logger.debug(
            "send_response() sending to stream=%s for message_id=%s (data_length=%d)",
            output_stream,
            message_id,
            len(data),
        )

        redis_client = await self._get_redis()
        response_id_bytes: bytes = await redis_client.xadd(
            output_stream,
            {
                b"chunk": data.encode("utf-8"),
                b"timestamp": str(time.time()).encode("utf-8"),
                b"message_id": message_id.encode("utf-8"),
            },
            maxlen=self.output_stream_maxlen,
        )

        logger.debug(
            "send_response() completed for message_id=%s, stream=%s, response_id=%s",
            message_id,
            output_stream,
            response_id_bytes,
        )
        return response_id_bytes.decode("utf-8")

    async def read_response(self, message_id: str, timeout: float = 3.0, target_computer: str | None = None) -> str:
        """Read response from ephemeral request (non-streaming).

        Used for one-shot request/response like list_projects, get_computer_info.
        Reads once from the Redis stream instead of continuous polling.

        Args:
            message_id: Redis stream entry ID from the original request
            timeout: Maximum time to wait for response (seconds, default 3.0)

        Returns:
            Response data as string

        Raises:
            TimeoutError: If no response received within timeout
        """

        if target_computer:
            output_stream = f"output:{target_computer}:{message_id}"
        else:
            output_stream = f"output:{message_id}"
        start_time = time.time()
        logger.trace("Redis response wait", stream=output_stream, timeout_s=timeout)

        try:
            poll_count = 0
            while True:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(
                        "read_response() timed out after %d polls (%.1fs) for message %s",
                        poll_count,
                        elapsed,
                        message_id,
                    )
                    raise TimeoutError(f"No response received for message {message_id} within {timeout}s")

                # Read from stream (blocking with 100ms timeout)
                poll_count += 1
                logger.trace(
                    "Redis response poll",
                    request_id=message_id,
                    poll=poll_count,
                    elapsed_s=round(elapsed, 1),
                )
                redis_client = await self._get_redis()
                messages = await redis_client.xread({output_stream.encode("utf-8"): b"0"}, block=100, count=1)

                if messages:
                    # Got response - extract and return
                    for _stream_name, stream_messages in messages:
                        for _entry_id, data in stream_messages:
                            chunk_bytes: bytes = data.get(b"chunk", b"")
                            chunk: str = chunk_bytes.decode("utf-8")
                            if chunk:
                                logger.debug(
                                    "Redis response received",
                                    request_id=message_id,
                                    polls=poll_count,
                                    length=len(chunk),
                                )
                                return chunk

                # No message yet, continue polling
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("read_response cancelled for message %s", message_id)
            raise

    async def send_system_command(self, computer_name: str, command: str, args: JsonDict | None = None) -> str:
        """Send system command to remote computer (not session-specific).

        System commands are handled by the daemon itself, not routed to tmux.
        Examples: restart, health_check

        Args:
            computer_name: Target computer name
            command: System command (e.g., "health_check")
            args: Optional command arguments

        Returns:
            Redis stream entry ID
        """

        message_stream = f"messages:{computer_name}"

        # Build system message data
        data = {
            b"type": b"system",
            b"command": command.encode("utf-8"),
            b"timestamp": str(time.time()).encode("utf-8"),
            b"from_computer": self.computer_name.encode("utf-8"),
            b"origin": InputOrigin.REDIS.value.encode("utf-8"),
        }

        # Add args as JSON if provided
        if args:
            data[b"args"] = json.dumps(args).encode("utf-8")

        # Send to Redis stream
        logger.debug("Sending system command to %s: %s", computer_name, command)
        redis_client = await self._get_redis()
        message_id_bytes: bytes = await redis_client.xadd(message_stream, data, maxlen=self.message_stream_maxlen)  # pyright: ignore[reportArgumentType]  # pyright: ignore[reportArgumentType]

        logger.info("Sent system command to %s: %s", computer_name, command)
        return message_id_bytes.decode("utf-8")

    async def get_system_command_status(self, computer_name: str, command: str) -> JsonDict:
        """Get status of system command execution.

        Args:
            computer_name: Target computer name
            command: System command name

        Returns:
            Status dict with keys: status, timestamp, error (if failed)
        """

        status_key = f"system_status:{computer_name}:{command}"
        redis_client = await self._get_redis()
        data = await redis_client.get(status_key)

        if not data:
            return {"status": "unknown"}

        result_obj: object = json.loads(data.decode("utf-8"))
        if not isinstance(result_obj, dict):
            return {"status": "error", "error": "Invalid result format"}
        result: JsonDict = result_obj
        return result

    def poll_output_stream(self, request_id: str, timeout: float = 300.0) -> AsyncIterator[str]:
        """Redis transport does not stream session output; use get_session_data polling."""
        _ = (request_id, timeout)
        raise NotImplementedError("Redis output streaming is disabled; use get_session_data polling.")
