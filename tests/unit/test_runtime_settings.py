"""Unit tests for RuntimeSettings and /settings API endpoints."""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from teleclaude.api_server import APIServer
from teleclaude.config.runtime_settings import (
    RuntimeSettings,
    SettingsPatch,
    SettingsState,
    TTSSettings,
    TTSSettingsPatch,
)

# --- RuntimeSettings unit tests ---


@pytest.fixture
def tts_manager():
    """Mock TTSManager with enabled=True."""
    mgr = MagicMock()
    mgr.enabled = True
    return mgr


@pytest.fixture
def config_yml(tmp_path: Path) -> Path:
    """Create a minimal config.yml for round-trip tests."""
    p = tmp_path / "config.yml"
    p.write_text("# TTS settings\ntts:\n  enabled: true\n  service_priority: [elevenlabs]\n")
    return p


@pytest.fixture
def settings(config_yml: Path, tts_manager: MagicMock) -> RuntimeSettings:
    return RuntimeSettings(config_yml, tts_manager)


def test_get_state_initial(settings: RuntimeSettings, tts_manager: MagicMock) -> None:
    """get_state reflects TTSManager's initial enabled value."""
    state = settings.get_state()
    assert isinstance(state, SettingsState)
    assert state.tts.enabled is True

    tts_manager.enabled = False
    s2 = RuntimeSettings(settings._config_path, tts_manager)
    assert s2.get_state().tts.enabled is False


@pytest.mark.asyncio
async def test_patch_valid_key(settings: RuntimeSettings, tts_manager: MagicMock) -> None:
    """patch() updates in-memory state and TTSManager.enabled."""
    result = settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=False)))
    assert isinstance(result, SettingsState)
    assert result.tts.enabled is False
    assert tts_manager.enabled is False
    assert settings.get_state().tts.enabled is False


@pytest.mark.asyncio
async def test_patch_no_fields_raises(settings: RuntimeSettings) -> None:
    """patch() rejects when no mutable fields are provided."""
    with pytest.raises(ValueError, match="No mutable settings"):
        settings.patch(SettingsPatch())


def test_parse_patch_valid() -> None:
    """parse_patch() converts valid raw JSON to typed SettingsPatch."""
    result = RuntimeSettings.parse_patch({"tts": {"enabled": False}})
    assert isinstance(result, SettingsPatch)
    assert result.tts is not None
    assert result.tts.enabled is False


def test_parse_patch_unknown_top_key() -> None:
    """parse_patch() rejects unknown top-level keys."""
    with pytest.raises(ValueError, match="Unknown settings keys"):
        RuntimeSettings.parse_patch({"database": {"path": "/tmp"}})


def test_parse_patch_unknown_tts_key() -> None:
    """parse_patch() rejects unknown keys within tts section."""
    with pytest.raises(ValueError, match="Unknown tts keys"):
        RuntimeSettings.parse_patch({"tts": {"enabled": True, "voice": "nova"}})


def test_parse_patch_rejects_non_boolean_enabled() -> None:
    """parse_patch() enforces boolean type for tts.enabled."""
    with pytest.raises(ValueError, match="tts.enabled must be a boolean"):
        RuntimeSettings.parse_patch({"tts": {"enabled": "false"}})


def test_parse_patch_rejects_pane_theming_mode() -> None:
    """parse_patch() rejects pane_theming_mode (now TUI-only, not a daemon setting)."""
    with pytest.raises(ValueError, match="Unknown settings keys"):
        RuntimeSettings.parse_patch({"pane_theming_mode": "highlight2"})


@pytest.mark.asyncio
async def test_flush_writes_yaml(settings: RuntimeSettings, config_yml: Path) -> None:
    """_flush_to_disk round-trips the config preserving structure."""
    settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=False)))
    await asyncio.sleep(0.6)
    content = config_yml.read_text()
    assert "enabled: false" in content
    assert "# TTS settings" in content
    assert "service_priority" in content


@pytest.mark.asyncio
async def test_debounce_coalesces(settings: RuntimeSettings, config_yml: Path) -> None:
    """Rapid patches result in a single disk write."""
    settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=False)))
    settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=True)))
    settings.patch(SettingsPatch(tts=TTSSettingsPatch(enabled=False)))
    await asyncio.sleep(0.6)
    content = config_yml.read_text()
    assert "enabled: false" in content


# --- API endpoint tests ---


@pytest.fixture
def mock_runtime_settings():
    """Mock RuntimeSettings for API tests."""
    rs = MagicMock(spec=RuntimeSettings)
    rs.get_state.return_value = SettingsState(tts=TTSSettings(enabled=True))
    rs.patch.return_value = SettingsState(tts=TTSSettings(enabled=False))
    return rs


@pytest.fixture
def api_with_settings(mock_runtime_settings: MagicMock):
    """APIServer with runtime_settings wired in."""
    client = MagicMock()
    socket_path = f"/tmp/teleclaude-api-test-{uuid.uuid4().hex}.sock"
    mock_commands = MagicMock()
    mock_commands.create_session = AsyncMock()
    with patch("teleclaude.api_server.get_command_service", return_value=mock_commands):
        server = APIServer(client=client, runtime_settings=mock_runtime_settings, socket_path=socket_path)
        yield server


@pytest.fixture
def settings_client(api_with_settings: APIServer):
    return TestClient(api_with_settings.app)


def test_get_settings(settings_client: TestClient, mock_runtime_settings: MagicMock) -> None:
    resp = settings_client.get("/settings")
    assert resp.status_code == 200
    assert resp.json() == {"tts": {"enabled": True}}
    mock_runtime_settings.get_state.assert_called_once()


def test_patch_settings_success(settings_client: TestClient, mock_runtime_settings: MagicMock) -> None:
    resp = settings_client.patch("/settings", json={"tts": {"enabled": False}})
    assert resp.status_code == 200
    assert resp.json() == {"tts": {"enabled": False}}
    mock_runtime_settings.patch.assert_called_once()


def test_patch_settings_rejects_pane_theming_mode(
    settings_client: TestClient, mock_runtime_settings: MagicMock
) -> None:
    """PATCH /settings rejects pane_theming_mode (now TUI-only)."""
    resp = settings_client.patch("/settings", json={"pane_theming_mode": "agent_plus"})
    assert resp.status_code == 400
    mock_runtime_settings.patch.assert_not_called()


def test_patch_settings_invalid_key(settings_client: TestClient, mock_runtime_settings: MagicMock) -> None:
    resp = settings_client.patch("/settings", json={"foo": "bar"})
    assert resp.status_code == 400
    mock_runtime_settings.patch.assert_not_called()


def test_patch_settings_invalid_key_with_valid_tts(
    settings_client: TestClient, mock_runtime_settings: MagicMock
) -> None:
    """PATCH /settings rejects unknown top-level keys even when tts.enabled is present."""
    resp = settings_client.patch("/settings", json={"foo": "bar", "tts": {"enabled": False}})
    assert resp.status_code == 400
    mock_runtime_settings.patch.assert_not_called()


def test_patch_settings_invalid_nested_tts_key(settings_client: TestClient, mock_runtime_settings: MagicMock) -> None:
    """PATCH /settings rejects unknown nested keys inside tts."""
    resp = settings_client.patch("/settings", json={"tts": {"enabled": False, "voice": "nova"}})
    assert resp.status_code == 400
    mock_runtime_settings.patch.assert_not_called()


def test_get_settings_no_runtime_settings() -> None:
    """GET /settings returns 503 when runtime_settings is None."""
    client = MagicMock()
    socket_path = f"/tmp/teleclaude-api-test-{uuid.uuid4().hex}.sock"
    mock_commands = MagicMock()
    mock_commands.create_session = AsyncMock()
    with patch("teleclaude.api_server.get_command_service", return_value=mock_commands):
        server = APIServer(client=client, socket_path=socket_path)
        tc = TestClient(server.app)
        resp = tc.get("/settings")
        assert resp.status_code == 503
