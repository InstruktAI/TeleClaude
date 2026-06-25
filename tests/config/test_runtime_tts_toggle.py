from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from teleclaude import daemon as daemon_mod
from teleclaude.api import settings_routes
from teleclaude.api.settings_routes import TTS_PROVISION_503_DETAIL
from teleclaude.config import TTSConfig
from teleclaude.config import runtime_settings as rs_mod
from teleclaude.config.runtime_settings import RuntimeSettings, SettingsPatch, TTSSettingsPatch
from teleclaude.core.events import AgentHookEvents
from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.tts import manager as manager_mod
from teleclaude.tts.manager import TTSManager
from teleclaude.tts.provision import TTSDepsInstallError, TTSUnsupportedPlatformError

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/config/runtime-tts-toggle"


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-16")
async def test_tts_section_reload_preserves_runtime_mute(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = TTSManager()
    # The runtime-settings layer has muted TTS; this is the live source of truth.
    manager.enabled = False

    # YAML now has tts.enabled = True and a changed config-derived field
    # (service_priority), modelling an operator editing an unrelated tts field.
    new_yaml_tts = TTSConfig(enabled=True, service_priority=["macos"], events={}, services={})
    monkeypatch.setattr(manager_mod.config, "tts", new_yaml_tts)

    # Drive the real config-reload trigger: only the tts section changed, no restart,
    # and the event producer is neutralised so the test does not depend on it.
    monkeypatch.setattr(daemon_mod, "reload_config", lambda: ["tts"])
    monkeypatch.setattr(daemon_mod, "restart_required_sections", lambda _changed: [])

    async def _no_emit(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(daemon_mod, "emit_event", _no_emit)

    daemon = SimpleNamespace(
        tts_manager=manager,
        chiptunes_manager=SimpleNamespace(reload=lambda: None),
        request_shutdown=lambda _reason: None,
    )

    await TeleClaudeDaemon._on_config_files_changed(daemon)

    # The runtime-owned mute survives the reload...
    assert manager.enabled is False
    # ...while config-derived state still refreshes from YAML.
    assert manager.tts_config.service_priority == ["macos"]
    # ...and no session-start speech is queued while TTS is muted.
    assert await manager.trigger_event(AgentHookEvents.AGENT_SESSION_START, "session-id") is False


def _runtime_settings(tmp_path: Path, *, enabled: bool) -> object:
    manager = TTSManager()
    manager.enabled = enabled
    settings_path = tmp_path / "runtime-settings.json"
    return RuntimeSettings(settings_path, manager)


def _enable_patch() -> object:
    return SettingsPatch(tts=TTSSettingsPatch(enabled=True))


def _mute_patch() -> object:
    return SettingsPatch(tts=TTSSettingsPatch(enabled=False))


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-17")
async def test_enable_provisions_before_flag_flips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _runtime_settings(tmp_path, enabled=False)
    provisioned: list[int] = []

    async def _ok(_tts_cfg: object) -> None:
        provisioned.append(1)

    monkeypatch.setattr(rs_mod, "ensure_tts_provisioned_async", _ok)
    state = await settings.apply_patch_async(_enable_patch())

    assert provisioned == [1]
    assert settings._tts_manager.enabled is True
    assert state.tts.enabled is True


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-18")
async def test_failed_provision_keeps_tts_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported-platform gating leaves the flag off (the enable transition fails closed)."""
    settings = _runtime_settings(tmp_path, enabled=False)

    async def _fail(_tts_cfg: object) -> None:
        raise TTSUnsupportedPlatformError("nope")

    monkeypatch.setattr(rs_mod, "ensure_tts_provisioned_async", _fail)
    with pytest.raises(TTSUnsupportedPlatformError):
        await settings.apply_patch_async(_enable_patch())

    assert settings._tts_manager.enabled is False
    assert settings.get_state().tts.enabled is False


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-19")
async def test_mute_never_provisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _runtime_settings(tmp_path, enabled=True)

    async def _unexpected(_tts_cfg: object) -> None:
        raise AssertionError("provisioning must not run on mute")

    monkeypatch.setattr(rs_mod, "ensure_tts_provisioned_async", _unexpected)
    state = await settings.apply_patch_async(_mute_patch())

    assert settings._tts_manager.enabled is False
    assert state.tts.enabled is False


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-18")
async def test_route_maps_provision_failure_to_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _runtime_settings(tmp_path, enabled=False)

    async def _fail(_tts_cfg: object) -> None:
        raise TTSDepsInstallError("install failed")

    monkeypatch.setattr(rs_mod, "ensure_tts_provisioned_async", _fail)
    settings_routes.configure(settings)

    with pytest.raises(HTTPException) as exc_info:
        await settings_routes.patch_settings({"tts": {"enabled": True}})

    assert exc_info.value.status_code == 503
    assert TTS_PROVISION_503_DETAIL in str(exc_info.value.detail)
    assert settings._tts_manager.enabled is False


@pytest.mark.spec(_SPEC, "UC-CFG-RUNTIME-20")
def test_boot_reconcile_forces_off_when_unprovisioned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_path = tmp_path / "runtime-settings.json"
    settings_path.write_text(json.dumps({"tts": {"enabled": True}}), encoding="utf-8")
    manager = TTSManager()
    settings = RuntimeSettings(settings_path, manager)
    assert manager.enabled is True  # replayed from persisted state

    monkeypatch.setattr(rs_mod, "supported_services", lambda _cfg: ["macos"])
    monkeypatch.setattr(rs_mod, "tts_deps_present", lambda _cfg: False)
    provisioned: list[int] = []

    async def _sentinel(_tts_cfg: object) -> None:
        provisioned.append(1)

    monkeypatch.setattr(rs_mod, "ensure_tts_provisioned_async", _sentinel)

    settings.reconcile_tts_provisioning()

    assert manager.enabled is False
    assert settings.get_state().tts.enabled is False
    on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
    assert on_disk["tts"]["enabled"] is False
    assert provisioned == []


def test_boot_reconcile_propagates_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_path = tmp_path / "runtime-settings.json"
    settings_path.mkdir()  # a directory: the forced-off persistence write fails with OSError
    manager = TTSManager()
    manager.enabled = True
    settings = RuntimeSettings(settings_path, manager)

    monkeypatch.setattr(rs_mod, "supported_services", lambda _cfg: ["macos"])
    monkeypatch.setattr(rs_mod, "tts_deps_present", lambda _cfg: False)

    with pytest.raises(OSError):
        settings.reconcile_tts_provisioning()

    # The in-memory off state is applied before the failed persist (fail closed in memory).
    assert manager.enabled is False
    assert settings.get_state().tts.enabled is False
