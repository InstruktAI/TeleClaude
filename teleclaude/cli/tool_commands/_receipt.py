"""Shared receipt polling for durable operations."""

from __future__ import annotations

import sys
import time

from teleclaude.cli.tool_client import print_json, tool_api_call

_TERMINAL_STATES = {"completed", "failed", "stale", "cancelled"}


def poll_operation(
    receipt: dict[str, object],  # guard: loose-dict - JSON-deserialized API response
    *,
    estimated_timeout_ms: int = 600_000,
) -> dict[str, object]:  # guard: loose-dict - JSON-deserialized API response
    """Poll a durable operation until it reaches a terminal state or times out.

    Args:
        receipt: Initial receipt dict from the API (must contain operation_id).
        estimated_timeout_ms: Maximum time to wait before giving up.

    Returns:
        Final operation status dict.
    """
    operation_id = receipt.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        print_json(receipt)
        return receipt

    status = receipt
    start = time.monotonic()
    timeout_s = estimated_timeout_ms / 1000.0

    try:
        while status.get("state") not in _TERMINAL_STATES:
            elapsed = time.monotonic() - start
            if elapsed > timeout_s:
                print(
                    f"Timeout after {elapsed:.0f}s waiting for operation {operation_id}",
                    file=sys.stderr,
                )
                _print_recovery(status)
                return status

            poll_after_ms = status.get("poll_after_ms")
            delay_s = 0.25
            if isinstance(poll_after_ms, int) and poll_after_ms > 0:
                delay_s = poll_after_ms / 1000.0
            time.sleep(delay_s)

            polled = tool_api_call("GET", f"/operations/{operation_id}")
            if not isinstance(polled, dict):
                print_json(polled)
                return status
            status = polled
    except KeyboardInterrupt as exc:
        _print_recovery(status)
        raise SystemExit(130) from exc
    except SystemExit:
        _print_recovery(status)
        raise

    return status


def _print_recovery(status: dict[str, object]) -> None:  # guard: loose-dict
    """Print recovery command for interrupted operations."""
    operation_id = status.get("operation_id")
    recovery_command = status.get("recovery_command")
    if isinstance(recovery_command, str) and recovery_command:
        print(f"Recovery: {recovery_command}", file=sys.stderr)
        return
    if isinstance(operation_id, str) and operation_id:
        print(f"Recovery: telec operations get {operation_id}", file=sys.stderr)
