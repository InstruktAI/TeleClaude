"""Execute a provider CLI with a controller-supplied, stdin-only environment allowlist."""

from __future__ import annotations

import json
import os
import sys
from typing import cast

_INVALID_LAUNCH_PAYLOAD = "Inspector launch payload is invalid."
_UTF8_ENCODING = "utf-8"
_STDIN = sys.stdin.buffer


def main() -> int:
    """Read the allowlisted environment from stdin and replace this process with the CLI."""
    if len(sys.argv) < 2:
        print(_INVALID_LAUNCH_PAYLOAD, file=sys.stderr)
        return 2
    try:
        payload = json.loads(_STDIN.readline().decode(_UTF8_ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(_INVALID_LAUNCH_PAYLOAD, file=sys.stderr)
        return 2
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        print(_INVALID_LAUNCH_PAYLOAD, file=sys.stderr)
        return 2
    environment = cast(dict[str, str], payload)
    executable_arguments = sys.argv[1:]
    os.execve(executable_arguments[0], executable_arguments, environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
