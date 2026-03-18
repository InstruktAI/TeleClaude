"""Shared stdin parsing helpers for hook adapters."""

from __future__ import annotations

import json
import sys
from typing import cast


def read_stdin_payload() -> tuple[str, dict[str, object]]:
    """Read a JSON object payload from stdin when available."""
    raw_input = ""
    data: dict[str, object] = {}
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read()
        if raw_input.strip():
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object")
            data = cast(dict[str, object], parsed)
    return raw_input, data
