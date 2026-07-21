"""Functional tests for daemon-connection resilience (UC-TDR1)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import textual.timer as timer_mod
from textual.timer import Timer, TimerCallback

import teleclaude.cli.tui.app as app_mod
import teleclaude.cli.tui.state_store as state_store
from teleclaude.api_models import TuiBootstrapDTO, TuiBootstrapPillar
from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.tui.app import TelecApp
from tests.tui.conftest import StubPaneBridge, build_bootstrap_response

pytestmark = pytest.mark.functional

SPEC_ID = "project/spec/feature/tui/daemon-connection-resilience"


async def _accept_then_disconnect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Read the in-flight request, then close the socket without a response."""
    await reader.read(65536)
    writer.close()
    await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.spec(SPEC_ID, "UC-TDR1")
async def test_client_surfaces_mid_request_disconnect_as_api_error() -> None:
    # AF_UNIX paths are capped well below pytest's nested tmp_path length (and
    # below the sandboxed TMPDIR), so bind directly under /tmp instead.
    socket_path = Path("/tmp") / f"tc-{uuid.uuid4().hex[:8]}.sock"
    server = await asyncio.start_unix_server(_accept_then_disconnect, path=str(socket_path))
    try:
        async with server:
            client = TelecAPIClient(socket_path=str(socket_path))
            await client.connect()
            try:
                with pytest.raises(APIError):
                    await client.list_computers()
            finally:
                await client.close()
    finally:
        if socket_path.exists():
            socket_path.unlink()


class _FlakyBootstrapAPI:
    """Stub API client whose first bootstrap call fails like a mid-request daemon disconnect."""

    def __init__(self) -> None:
        self.bootstrap_calls = 0

    async def connect(self) -> None:
        return None

    def start_websocket(self, **_kwargs: object) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_tui_bootstrap(
        self, pillars: list[TuiBootstrapPillar], include_removed: bool = True
    ) -> TuiBootstrapDTO:
        self.bootstrap_calls += 1
        if self.bootstrap_calls == 1:
            raise APIError("Connection to API server interrupted mid-request. Daemon may be restarting.")
        return build_bootstrap_response(pillars)


@pytest.mark.asyncio
@pytest.mark.spec(SPEC_ID, "UC-TDR1")
async def test_tui_survives_mid_request_disconnect_and_retries_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tmp_path / "tui_state.json")
    monkeypatch.setattr(app_mod, "PaneManagerBridge", StubPaneBridge)

    # Drive Textual's timer deterministically without touching the production
    # retry delay: `set_timer` and its requested interval are untouched, so
    # the real scheduling path (`_arm_bootstrap_retry_timer`) runs unchanged;
    # only the underlying sleep primitive that `Timer._run` awaits is
    # replaced with an immediate return, so the real timer fires without
    # waiting out real wall-clock time.
    async def _no_op_sleep(secs: float) -> None:
        del secs

    monkeypatch.setattr(timer_mod, "sleep", _no_op_sleep)

    # The immediate-return sleep affects every recurring Textual timer. Disable
    # intervals so they cannot spin during teardown; this scenario exercises
    # the one-shot bootstrap retry scheduled through set_timer.
    def _skip_set_interval(
        interval: float,
        callback: TimerCallback | None = None,
        *,
        name: str | None = None,
        repeat: int = 0,
        pause: bool = False,
    ) -> Timer | None:
        del interval, callback, name, repeat, pause
        return None

    api = _FlakyBootstrapAPI()
    app = TelecApp(api=api)
    monkeypatch.setattr(app, "set_interval", _skip_set_interval)

    async with app.run_test(size=(120, 40)) as pilot:
        # Wait on the observable condition — a second bootstrap call — with
        # a bounded timeout that raises a clear error, rather than sleeping
        # a guessed real-clock margin. The stub only raises APIError on its
        # first call, so reaching two calls proves the first one failed and
        # the retry both fired and succeeded.
        async def _second_bootstrap_call() -> None:
            while api.bootstrap_calls < 2:
                await pilot.pause()

        await asyncio.wait_for(_second_bootstrap_call(), timeout=2.0)
        await app.workers.wait_for_complete()

        # The failed first bootstrap surfaced as a handled APIError (caught
        # by APP_DATA_ERRORS) instead of an unhandled exception: the app
        # kept running rather than the process dying.
        assert app.is_running
        assert api.bootstrap_calls == 2
