"""Entry point for the alpha runner process (runs inside the Docker sidecar)."""

from __future__ import annotations

import asyncio
import os
import signal

from teleclaude_events.alpha.runner import AlphaRunner


def main() -> None:
    socket_path = os.environ["ALPHA_SOCKET_PATH"]
    cartridges_dir = os.environ["ALPHA_CARTRIDGES_DIR"]

    shutdown = asyncio.Event()

    def _signal_handler() -> None:
        shutdown.set()

    loop = asyncio.new_event_loop()
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    loop.add_signal_handler(signal.SIGINT, _signal_handler)

    runner = AlphaRunner(socket_path=socket_path, cartridges_dir=cartridges_dir)
    try:
        loop.run_until_complete(runner.start(shutdown))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
