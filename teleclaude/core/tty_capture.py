"""Best-effort TTY output capture to a log file."""

from __future__ import annotations

import argparse
import os
import select
import sys
import time
from typing import cast


class _Args(argparse.Namespace):
    pty: str
    output: str


def _parse_args() -> _Args:
    parser = argparse.ArgumentParser(description="Capture PTY output to a log file")
    parser.add_argument("--pty", required=True, help="PTY master device path (e.g., /dev/ptys007)")
    parser.add_argument("--output", required=True, help="Output log file path")
    return cast(_Args, parser.parse_args())


def main() -> int:
    args = _parse_args()
    pty_path = args.pty
    output_path = args.output

    try:
        pty_fd = os.open(pty_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        sys.stderr.write(f"Failed to open pty {pty_path}: {exc}\n")
        return 1

    try:
        with open(output_path, "ab", buffering=0) as output:
            while True:
                ready_raw = select.select([pty_fd], [], [], 0.5)
                ready: list[int] = list(ready_raw[0])
                if not ready:
                    continue
                try:
                    chunk = os.read(pty_fd, 4096)
                except OSError:
                    time.sleep(0.1)
                    continue
                if not chunk:
                    break
                output.write(chunk)
    finally:
        os.close(pty_fd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
