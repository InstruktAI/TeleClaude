"""CLI surface for `telec config tts deprovision`."""

from __future__ import annotations

import pytest

from teleclaude.cli.api_client import APIError
from teleclaude.cli.telec.handlers import config as config_handler
from teleclaude.cli.telec.surface import CLI_SURFACE
from teleclaude.cli.telec.surface_types import _HR_ADMIN, _SYS_ORCH

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/config/runtime-tts-toggle"


def test_deprovision_leaf_resolves_orch_admin_clearance() -> None:
    """The destructive leaf is gated the same way as other admin-only config actions."""
    tts_node = CLI_SURFACE["config"].subcommands["tts"]
    deprovision = tts_node.subcommands["deprovision"]
    assert deprovision.auth is not None
    assert deprovision.auth.system == _SYS_ORCH
    assert deprovision.auth.human == _HR_ADMIN


@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-28")
def test_bare_invocation_guards_and_never_calls_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[None] = []

    async def _unexpected_deprovision() -> None:
        calls.append(None)

    monkeypatch.setattr(config_handler, "_deprovision_tts", _unexpected_deprovision)

    with pytest.raises(SystemExit) as exc_info:
        config_handler._handle_config_tts(["deprovision"])

    assert exc_info.value.code != 0
    assert calls == []


@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-29")
def test_yes_flag_calls_client_once(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[None] = []

    async def _fake_deprovision() -> None:
        calls.append(None)

    monkeypatch.setattr(config_handler, "_deprovision_tts", _fake_deprovision)

    config_handler._handle_config_tts(["deprovision", "--yes"])

    assert calls == [None]
    assert capsys.readouterr().out.strip() == config_handler.TTS_DEPROVISION_CONFIRM


@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-30")
def test_yes_flag_surfaces_daemon_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail_deprovision() -> None:
        raise APIError("boom", status_code=500, detail="boom")

    monkeypatch.setattr(config_handler, "_deprovision_tts", _fail_deprovision)

    with pytest.raises(SystemExit) as exc_info:
        config_handler._handle_config_tts(["deprovision", "--yes"])

    assert exc_info.value.code != 0


@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-31")
def test_top_level_dispatch_routes_tts_to_config_tts_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """`telec config tts ...` is dispatched by `_handle_config`, not the legacy people/env/notify path."""
    seen: list[list[str]] = []
    monkeypatch.setattr(config_handler, "_handle_config_tts", lambda args: seen.append(args))

    config_handler._handle_config(["tts", "deprovision", "--yes"])

    assert seen == [["deprovision", "--yes"]]
