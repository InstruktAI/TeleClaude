#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml",
#     "youtube-transcript-api",
#     "aiohttp",
#     "dateparser",
#     "munch",
#     "pydantic",
#     "instruktai-python-logger",
# ]
# ///
"""Cron entrypoint: sync YouTube subscriptions into CSV and tag new rows."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.entrypoints.youtube_sync_subscriptions import main

if __name__ == "__main__":
    raise SystemExit(main())
