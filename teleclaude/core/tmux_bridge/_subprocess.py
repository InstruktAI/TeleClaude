"""Subprocess timeout utilities for tmux operations."""

import asyncio

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

# Subprocess timeout constants
SUBPROCESS_TIMEOUT_DEFAULT = 30.0  # Default timeout for subprocess operations
SUBPROCESS_TIMEOUT_QUICK = 5.0  # Timeout for quick operations (list, status checks)
SUBPROCESS_TIMEOUT_LONG = 60.0  # Timeout for long operations (complex commands)


class SubprocessTimeoutError(Exception):
    """Raised when a subprocess operation exceeds its timeout.

    Attributes:
        operation: Description of the operation that timed out
        timeout: Timeout value in seconds
        pid: Process ID (None if process was not started)
    """

    def __init__(self, operation: str, timeout: float, pid: int | None = None) -> None:
        """
        Initialize subprocess timeout error with structured data.

        Args:
            operation: Description of the operation that timed out
            timeout: Timeout value in seconds
            pid: Process ID (None if process was not started)
        """
        self.operation = operation
        self.timeout = timeout
        self.pid = pid
        super().__init__(f"{operation} timed out after {timeout}s")


async def wait_with_timeout(
    process: asyncio.subprocess.Process,
    timeout: float = SUBPROCESS_TIMEOUT_DEFAULT,
    operation: str = "subprocess",
) -> None:
    """
    Wait for a subprocess to complete with a timeout.

    If the timeout is exceeded, the process is killed and a SubprocessTimeoutError
    is raised. This prevents indefinite blocking if a subprocess hangs.

    Args:
        process: The subprocess to wait for
        timeout: Maximum time to wait in seconds
        operation: Description of the operation for error messages

    Raises:
        SubprocessTimeoutError: If the process doesn't complete within timeout
    """
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "%s timeout after %.1fs, killing process %d",
            operation,
            timeout,
            process.pid if process.pid else -1,
        )
        try:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            logger.error("Process %d failed to terminate after SIGKILL", process.pid or -1)
        except ProcessLookupError:
            pass  # Process already terminated
        raise SubprocessTimeoutError(operation, timeout, process.pid)


async def communicate_with_timeout(
    process: asyncio.subprocess.Process,
    input_data: bytes | None = None,
    timeout: float = SUBPROCESS_TIMEOUT_DEFAULT,
    operation: str = "subprocess",
) -> tuple[bytes, bytes]:
    """
    Communicate with a subprocess with a timeout.

    If the timeout is exceeded, the process is killed and a SubprocessTimeoutError
    is raised. This prevents indefinite blocking if a subprocess hangs.

    Args:
        process: The subprocess to communicate with
        input_data: Optional input to send to the process
        timeout: Maximum time to wait in seconds
        operation: Description of the operation for error messages

    Returns:
        Tuple of (stdout, stderr) as bytes

    Raises:
        SubprocessTimeoutError: If communication doesn't complete within timeout
    """
    try:
        return await asyncio.wait_for(process.communicate(input_data), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "%s timeout after %.1fs, killing process %d",
            operation,
            timeout,
            process.pid if process.pid else -1,
        )
        try:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            logger.error("Process %d failed to terminate after SIGKILL", process.pid or -1)
        except ProcessLookupError:
            pass  # Process already terminated
        raise SubprocessTimeoutError(operation, timeout, process.pid)
