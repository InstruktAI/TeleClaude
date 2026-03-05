from __future__ import annotations

from pathlib import Path

import teleclaude.cli.config_handlers as config_handlers_mod
from teleclaude.cli.config_handlers import EnvVarInfo, EnvVarStatus, ValidationResult
from teleclaude.cli.tui.views import config as config_view
from teleclaude.cli.tui.views.config import (
    _ADAPTER_TABS,
    _PERSON_EDITABLE_FIELDS,
    _SUBTABS,
    _VALID_ROLES,
    ConfigContent,
    NotificationProjection,
    classify_adapter_status,
    completion_summary,
    project_adapter_sections,
)
from teleclaude.config.schema import PersonEntry


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
        if content._guided_mode:
            content._apply_guided_step()
            content._auto_advance_completed_steps()

    monkeypatch.setattr(config_view, "set_env_var", fake_set_env_var)
    monkeypatch.setattr(content, "refresh_data", fake_refresh_data)

    content.save_edit()

    assert content.guided_mode is True
    assert content._guided_step_index == 1
    assert _SUBTABS[content.active_subtab] == "adapters"
    assert _ADAPTER_TABS[content.active_adapter_tab] == "discord"


def test_guided_environment_step_is_incomplete_when_env_data_missing() -> None:
    content = ConfigContent()
    content._guided_mode = True
    content._env_data = []
    content._guided_step_index = next(
        index for index, step in enumerate(config_view._GUIDED_STEPS) if step.subtab == "environment"
    )

    assert content._is_current_guided_step_complete() is False


def test_save_edit_triggers_guided_auto_advance_once_via_refresh(monkeypatch) -> None:
    content = ConfigContent()
    status = _env_status("TELEGRAM_BOT_TOKEN", "telegram", False)
    content._env_data = [status]
    content._adapter_sections = project_adapter_sections(content._env_data)
    content._guided_mode = True
    content._guided_step_index = 0
    content._apply_guided_step()
    content._begin_edit(status)
    content._edit_buffer = "token"

    def fake_set_env_var(name: str, value: str) -> Path:
        _ = (name, value)
        return Path("/tmp/.env")

    auto_advance_calls = {"count": 0}

    def fake_auto_advance_completed_steps() -> None:
        auto_advance_calls["count"] += 1

    def fake_refresh_data() -> None:
        if content._guided_mode:
            content._apply_guided_step()
            content._auto_advance_completed_steps()

    monkeypatch.setattr(config_view, "set_env_var", fake_set_env_var)
    monkeypatch.setattr(content, "_auto_advance_completed_steps", fake_auto_advance_completed_steps)
    monkeypatch.setattr(content, "refresh_data", fake_refresh_data)

    content.save_edit()

    assert auto_advance_calls["count"] == 1


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


# ── Validate tab removed ─────────────────────────────────────────────────────


def test_validate_tab_is_not_in_subtabs() -> None:
    """Requirement: validate tab must not appear in the wizard tab bar."""
    assert "validate" not in _SUBTABS


def test_guided_steps_do_not_include_validate() -> None:
    """Requirement: guided mode must not navigate to the removed validate tab."""
    from teleclaude.cli.tui.views.config import _GUIDED_STEPS

    assert all(step.subtab != "validate" for step in _GUIDED_STEPS)


# ── Daemon-free startup ───────────────────────────────────────────────────────


def test_config_content_renders_without_daemon(monkeypatch) -> None:
    """Requirement: config wizard must work before the daemon is running.

    This is a first-boot use case. ConfigContent.refresh_data uses only
    file-based config handlers — no API socket access.
    """
    monkeypatch.setattr(config_handlers_mod, "check_env_vars", lambda: [])
    monkeypatch.setattr(config_handlers_mod, "list_people", lambda **_: [])

    content = ConfigContent()
    content.refresh_data()
    rendered = content.render().plain

    assert "adapters" in rendered.lower()
    assert "people" in rendered.lower()
    assert content._env_data == []
    assert content._people_data == []


def test_config_handlers_do_not_import_api_client() -> None:
    """Requirement: config_handlers must have no daemon/socket dependency.

    Verified structurally: the module must not import TelecAPIClient or
    reference the API socket path.
    """
    import inspect

    source = inspect.getsource(config_handlers_mod)
    assert "TelecAPIClient" not in source
    assert "teleclaude-api.sock" not in source


# ── People tab — cursor navigation ───────────────────────────────────────────


def _people(names: list[str]) -> list[PersonEntry]:
    return [PersonEntry(name=n, email=f"{n}@example.com") for n in names]


def _people_content(names: list[str]) -> ConfigContent:
    content = ConfigContent()
    content.active_subtab = _SUBTABS.index("people")
    content._people_data = _people(names)
    return content


def test_people_cursor_moves_through_list() -> None:
    content = _people_content(["alice", "bob", "carol"])
    content._set_current_cursor(0)

    content.move_cursor(1)
    assert content._current_cursor() == 1

    content.move_cursor(1)
    assert content._current_cursor() == 2

    content.move_cursor(1)  # clamp at end
    assert content._current_cursor() == 2

    content.move_cursor(-3)  # clamp at 0
    assert content._current_cursor() == 0


def test_people_activate_expands_selected_person() -> None:
    content = _people_content(["alice"])
    content._set_current_cursor(0)

    assert content._expanded_person is None
    content.activate_current()
    assert content._expanded_person == "alice"


def test_people_field_cursor_navigates_within_expanded_person() -> None:
    content = _people_content(["alice"])
    content._set_current_cursor(0)
    content._expanded_person = "alice"
    content._person_field_cursor = 0

    content.move_cursor(1)
    assert content._person_field_cursor == 1

    content.move_cursor(1)
    assert content._person_field_cursor == 2

    content.move_cursor(1)  # clamp at last field
    assert content._person_field_cursor == len(_PERSON_EDITABLE_FIELDS) - 1


# ── People tab — field editing ────────────────────────────────────────────────


def test_people_activate_on_text_field_starts_edit() -> None:
    content = _people_content(["alice"])
    content._set_current_cursor(0)
    content._expanded_person = "alice"
    content._person_field_cursor = _PERSON_EDITABLE_FIELDS.index("email")

    content.activate_current()

    assert content._editing_person_field == "email"
    assert content.is_editing is True


def test_people_cancel_field_edit_does_not_save(monkeypatch) -> None:
    content = _people_content(["alice"])
    content._expanded_person = "alice"
    person = content._people_data[0]
    content._begin_person_field_edit(person, "email")
    content._edit_buffer = "changed@example.com"

    saved = {"called": False}
    monkeypatch.setattr(config_handlers_mod, "save_global_config", lambda _: saved.__setitem__("called", True))

    content.cancel_edit()

    assert content.is_editing is False
    assert saved["called"] is False
    assert "Canceled edit for email" in content._status_message


def test_people_collapse_person_clears_expanded_state() -> None:
    content = _people_content(["alice"])
    content._expanded_person = "alice"
    content._editing_person_field = "email"
    content._edit_buffer = "partial"

    content.collapse_person()

    assert content.is_person_expanded is False
    assert content._editing_person_field is None
    assert content._edit_buffer == ""


# ── People tab — role cycling ─────────────────────────────────────────────────


def test_role_cycles_through_valid_values_on_activate(monkeypatch) -> None:
    """Role field must cycle through enum values — never accept arbitrary text."""
    content = _people_content(["alice"])
    person = content._people_data[0]
    person.role = "member"  # type: ignore[assignment]
    content._set_current_cursor(0)
    content._expanded_person = "alice"
    content._person_field_cursor = _PERSON_EDITABLE_FIELDS.index("role")

    class _FakeCfg:
        people = [person]

    monkeypatch.setattr(config_handlers_mod, "get_global_config", lambda: _FakeCfg())
    monkeypatch.setattr(config_handlers_mod, "save_global_config", lambda _: None)
    monkeypatch.setattr(content, "refresh_data", lambda: None)

    content.activate_current()

    expected_next = _VALID_ROLES[(_VALID_ROLES.index("member") + 1) % len(_VALID_ROLES)]
    assert person.role == expected_next
    assert expected_next in content._status_message


def test_role_wraps_from_last_to_first(monkeypatch) -> None:
    content = _people_content(["alice"])
    person = content._people_data[0]
    person.role = _VALID_ROLES[-1]  # type: ignore[assignment]
    content._set_current_cursor(0)
    content._expanded_person = "alice"
    content._person_field_cursor = _PERSON_EDITABLE_FIELDS.index("role")

    class _FakeCfg:
        people = [person]

    monkeypatch.setattr(config_handlers_mod, "get_global_config", lambda: _FakeCfg())
    monkeypatch.setattr(config_handlers_mod, "save_global_config", lambda _: None)
    monkeypatch.setattr(content, "refresh_data", lambda: None)

    content.activate_current()

    assert person.role == _VALID_ROLES[0]


# ── People tab — render ───────────────────────────────────────────────────────


def test_people_render_shows_expanded_fields() -> None:
    content = _people_content(["alice"])
    person = content._people_data[0]
    person.role = "admin"  # type: ignore[assignment]
    content._set_current_cursor(0)
    content._expanded_person = "alice"

    rendered = content.render().plain

    assert "alice" in rendered
    assert "email" in rendered
    assert "role" in rendered
    assert "username" in rendered
    assert "admin" in rendered


def test_people_render_shows_role_options_inline() -> None:
    """Role row must display all valid options — never a free-text prompt."""
    content = _people_content(["alice"])
    content._set_current_cursor(0)
    content._expanded_person = "alice"
    content._person_field_cursor = _PERSON_EDITABLE_FIELDS.index("role")

    rendered = content.render().plain

    for opt in _VALID_ROLES:
        assert opt in rendered
