from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude import daemon as daemon_mod
from teleclaude.config import TTSConfig
from teleclaude.core.events import AgentHookEvents
from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.tts import manager as manager_mod
from teleclaude.tts.manager import TTSManager

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
