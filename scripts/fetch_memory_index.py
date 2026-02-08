#!/usr/bin/env -S uv run --quiet

"""Fetch memory index from the memory worker API."""

import json
import os
import sys
import urllib.request
from typing import Any, Dict, List

MEM_BASE_URL = os.getenv("MEM_BASE_URL", "http://127.0.0.1:37777")


def fetch_observations(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent observations from the memory API."""
    url = f"{MEM_BASE_URL}/api/observations?limit={limit}"
    try:
        with urllib.request.urlopen(url) as response:
            if response.status != 200:
                return []
            data = json.loads(response.read().decode())
            return data.get("observations", [])
    except Exception:
        return []


def format_index(observations: List[Dict[str, Any]]) -> str:
    """Format observations as an XML index."""
    if not observations:
        return ""

    lines = ["<memory_index>"]
    for obs in observations:
        title = obs.get("title", "Untitled")
        obs_id = obs.get("id", "")
        lines.append(f'  <entry id="{obs_id}">{title}</entry>')
    lines.append("</memory_index>")
    return "
".join(lines)


def main() -> None:
    observations = fetch_observations()
    if observations:
        print(format_index(observations))


if __name__ == "__main__":
    main()
