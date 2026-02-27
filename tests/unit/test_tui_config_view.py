from __future__ import annotations

from pathlib import Path

from teleclaude.cli.config_handlers import EnvVarInfo, EnvVarStatus, ValidationResult
from teleclaude.cli.tui.views import config as config_view
from teleclaude.cli.tui.views.config import (
    _ADAPTER_TABS,
    _SUBTABS,
    ConfigContent,
    NotificationProjection,
    classify_adapter_status,
    completion_summary,
    project_adapter_sections,
)


def _env_status(name: str, adapter: str, is_set: bool) -> EnvVarStatus:
    return EnvVarStatus(
        info=EnvVarInfo(
            name=name,
            adapter=adapter,
            description=f"{name} description",
            example="example",
        ),
        is_set=is_set,
    )


def test_classify_adapter_status() -> None:
    unset = [_env_status("A", "telegram", False), _env_status("B", "telegram", False)]
    partial = [_env_status("A", "telegram", True), _env_status("B", "telegram", False)]
    configured = [_env_status("A", "telegram", True), _env_status("B", "telegram", True)]

    assert classify_adapter_status([]) == "unconfigured"
    assert classify_adapter_status(unset) == "unconfigured"
    assert classify_adapter_status(partial) == "partial"
    assert classify_adapter_status(configured) == "configured"


def test_project_adapter_sections_and_completion_summary() -> None:
    env_data = [
        _env_status("TELEGRAM_BOT_TOKEN", "telegram", True),
        _env_status("DISCORD_BOT_TOKEN", "discord", False),
        _env_status("ANTHROPIC_API_KEY", "ai", True),
        _env_status("ELEVENLABS_API_KEY", "voice", False),
        _env_status("WHATSAPP_ACCESS_TOKEN", "whatsapp", False),
    ]

    sections = project_adapter_sections(env_data)
    by_key = {section.key: section for section in sections}

    assert [section.key for section in sections] == list(_ADAPTER_TABS)
    assert by_key["telegram"].status == "configured"
    assert by_key["discord"].status == "unconfigured"
    assert by_key["ai_keys"].status == "partial"
    assert by_key["whatsapp"].status == "unconfigured"

    configured, total = completion_summary(
        sections,
        has_people=True,
        notifications_configured=False,
        environment_configured=False,
    )
    assert configured == 2
    assert total == 7


def test_save_edit_uses_shared_helper_and_refreshes(monkeypatch) -> None:
    content = ConfigContent()
    status = _env_status("TELEGRAM_BOT_TOKEN", "telegram", False)
    content._env_data = [status]
    content._adapter_sections = project_adapter_sections(content._env_data)
    content.active_subtab = 0
    content.active_adapter_tab = 0

    content._begin_edit(status)
    content._edit_buffer = "new-token"

    calls: list[tuple[str, str]] = []

    def fake_set_env_var(name: str, value: str) -> Path:
        calls.append((name, value))
        return Path("/tmp/.env")

    refreshed = {"count": 0}

    def fake_refresh_data() -> None:
        refreshed["count"] += 1

    monkeypatch.setattr(config_view, "set_env_var", fake_set_env_var)
    monkeypatch.setattr(content, "refresh_data", fake_refresh_data)

    content.save_edit()

    assert calls == [("TELEGRAM_BOT_TOKEN", "new-token")]
    assert refreshed["count"] == 1
    assert content.is_editing is False
    assert "Saved TELEGRAM_BOT_TOKEN" in content._status_message


def test_cancel_edit_does_not_persist_changes(monkeypatch) -> None:
    content = ConfigContent()
    status = _env_status("DISCORD_BOT_TOKEN", "discord", False)
    content._begin_edit(status)
    content._edit_buffer = "discard-me"

    called = {"count": 0}

    def fake_set_env_var(name: str, value: str) -> Path:
        _ = (name, value)
        called["count"] += 1
        return Path("/tmp/.env")

    monkeypatch.setattr(config_view, "set_env_var", fake_set_env_var)

    content.cancel_edit()

    assert called["count"] == 0
    assert content.is_editing is False
    assert "Canceled edit" in content._status_message


def test_save_edit_error_surfaces_feedback(monkeypatch) -> None:
    content = ConfigContent()
    status = _env_status("OPENAI_API_KEY", "ai", False)
    content._begin_edit(status)
    content._edit_buffer = "bad"

    def failing_set_env_var(name: str, value: str) -> Path:
        _ = (name, value)
        raise RuntimeError("disk full")

    monkeypatch.setattr(config_view, "set_env_var", failing_set_env_var)

    content.save_edit()

    assert content.is_editing is True
    assert content._status_is_error is True
    assert "Failed to save OPENAI_API_KEY" in content._status_message


def test_guided_mode_advances_after_save_when_step_completes(monkeypatch) -> None:
    content = ConfigContent()
    initial_env = [
        _env_status("TELEGRAM_BOT_TOKEN", "telegram", False),
        _env_status("DISCORD_BOT_TOKEN", "discord", False),
    ]
    content._env_data = initial_env
    content._adapter_sections = project_adapter_sections(initial_env)

    content._guided_mode = True
    content._guided_step_index = 0
    content._apply_guided_step()

    selected = content._current_selected_env()
    assert selected is not None
    content._begin_edit(selected)
    content._edit_buffer = "token"

    def fake_set_env_var(name: str, value: str) -> Path:
        _ = (name, value)
        return Path("/tmp/.env")

    def fake_refresh_data() -> None:
        updated_env = [
            _env_status("TELEGRAM_BOT_TOKEN", "telegram", True),
            _env_status("DISCORD_BOT_TOKEN", "discord", False),
        ]
        content._env_data = updated_env
        content._adapter_sections = project_adapter_sections(updated_env)

    monkeypatch.setattr(config_view, "set_env_var", fake_set_env_var)
    monkeypatch.setattr(content, "refresh_data", fake_refresh_data)

    content.save_edit()

    assert content.guided_mode is True
    assert content._guided_step_index == 1
    assert _SUBTABS[content.active_subtab] == "adapters"
    assert _ADAPTER_TABS[content.active_adapter_tab] == "discord"


def test_notifications_view_does_not_render_placeholder_literal() -> None:
    content = ConfigContent()
    content.active_subtab = _SUBTABS.index("notifications")
    content._notification_projection = NotificationProjection(
        configured=False,
        total_people=0,
        people_with_subscriptions=0,
        total_subscriptions=0,
        next_action="Run: telec config people add --name <name> --email <email>",
    )

    rendered = content.render().plain
    assert "Not implemented yet" not in rendered


def test_guided_validate_step_advances_on_passing_validation(monkeypatch) -> None:
    content = ConfigContent()
    content._guided_mode = True
    content._guided_step_index = 7
    content._apply_guided_step()

    def fake_run_validation() -> None:
        content._validation_results = [ValidationResult(area="global", passed=True)]

    monkeypatch.setattr(content, "run_validation", fake_run_validation)
    content.activate_current()

    assert content.guided_mode is False
    assert "Guided setup complete" in content._status_message
