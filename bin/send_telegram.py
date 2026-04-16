#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "teleclaude" / "entrypoints" / "send_telegram.py"
    # UV_NO_SYNC=1 blocks uv run's implicit venv sync; ambient sync while
    # the daemon holds modules loaded causes stale-module crashes.
    env = {**os.environ, "UV_NO_SYNC": "1"}
    result = subprocess.run(["uv", "run", str(script), *sys.argv[1:]], env=env, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
