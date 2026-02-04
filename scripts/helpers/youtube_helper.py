#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "youtube-transcript-api",
#     "aiohttp",
#     "dateparser",
#     "munch",
#     "pydantic",
# ]
# ///
"""CLI wrapper for teleclaude.helpers.youtube_helper."""

import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.helpers.youtube_helper import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
