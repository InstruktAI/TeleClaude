"""Tests for config wizard guidance registry, env-to-field mapping, and TUI rendering."""

from __future__ import annotations

from teleclaude.cli.config_handlers import EnvVarInfo, EnvVarStatus, get_all_env_vars
from teleclaude.cli.tui.config_components.guidance import (
    _ENV_TO_FIELD,
    GuidanceRegistry,
    get_guidance_for_env,
)
from teleclaude.cli.tui.views.config import (
    ConfigContent,
    project_adapter_sections,
)


def _env_status(name: str, adapter: str, is_set: bool) -> EnvVarStatus:
    return EnvVarStatus(
        info=EnvVarInfo(name=name, adapter=adapter, description=f"{name} desc", example="ex"),
        is_set=is_set,
    )


class TestEnvToFieldMapping:
    def test_covers_all_adapter_env_vars(self) -> None:
        all_vars = get_all_env_vars()
        env_names = {info.name for group in all_vars.values() for info in group}
        mapped_names = set(_ENV_TO_FIELD.keys())
        assert env_names == mapped_names, f"Missing: {env_names - mapped_names}, Extra: {mapped_names - env_names}"

    def test_all_field_paths_have_guidance(self) -> None:
        registry = GuidanceRegistry()
        for env_name, field_path in _ENV_TO_FIELD.items():
            guidance = registry.get(field_path)
            assert guidance is not None, f"No guidance for {env_name} (field: {field_path})"


class TestGetGuidanceForEnv:
    def test_returns_guidance_for_known_vars(self) -> None:
        for env_name in _ENV_TO_FIELD:
            result = get_guidance_for_env(env_name)
            assert result is not None, f"get_guidance_for_env({env_name!r}) returned None"
            assert result.description
            assert len(result.steps) > 0

    def test_returns_none_for_unknown_var(self) -> None:
        assert get_guidance_for_env("NONEXISTENT_VAR") is None

    def test_guidance_has_url_for_all_entries(self) -> None:
        for env_name in _ENV_TO_FIELD:
            guidance = get_guidance_for_env(env_name)
            assert guidance is not None
            assert guidance.url is not None, f"{env_name} guidance missing url"

    def test_guidance_has_format_example_for_all_entries(self) -> None:
        for env_name in _ENV_TO_FIELD:
            guidance = get_guidance_for_env(env_name)
            assert guidance is not None
            assert guidance.format_example is not None, f"{env_name} guidance missing format_example"


class TestGuidanceRendering:
    def test_guidance_renders_for_selected_adapter_var(self) -> None:
        content = ConfigContent()
        env_data = [_env_status("TELEGRAM_BOT_TOKEN", "telegram", True)]
        content._env_data = env_data
        content._adapter_sections = project_adapter_sections(env_data)
        content.active_subtab = 0
        content.active_adapter_tab = 0
        content._set_current_cursor(0)

        rendered = content.render().plain
        assert "Guidance" in rendered
        assert "BotFather" in rendered

    def test_guidance_renders_for_selected_environment_var(self) -> None:
        content = ConfigContent()
        env_data = [
            _env_status("TELEGRAM_BOT_TOKEN", "telegram", True),
            _env_status("ANTHROPIC_API_KEY", "ai", False),
        ]
        content._env_data = env_data
        content._adapter_sections = project_adapter_sections(env_data)
        content.active_subtab = 3  # environment tab
        content._set_current_cursor(1)

        rendered = content.render().plain
        assert "Guidance" in rendered
        assert "Anthropic" in rendered

    def test_guidance_not_rendered_for_unselected_var(self) -> None:
        content = ConfigContent()
        env_data = [
            _env_status("TELEGRAM_BOT_TOKEN", "telegram", True),
            _env_status("TELEGRAM_SUPERGROUP_ID", "telegram", False),
        ]
        content._env_data = env_data
        content._adapter_sections = project_adapter_sections(env_data)
        content.active_subtab = 0
        content.active_adapter_tab = 0
        content._set_current_cursor(0)

        rendered = content.render().plain
        # Should show guidance for BOT_TOKEN (selected) but not SUPERGROUP_ID content
        assert "BotFather" in rendered
        # SUPERGROUP_ID guidance keywords should not appear
        assert "RawDataBot" not in rendered

    def test_guidance_renders_osc8_link_in_rich_text(self) -> None:
        content = ConfigContent()
        env_data = [_env_status("DISCORD_BOT_TOKEN", "discord", True)]
        content._env_data = env_data
        content._adapter_sections = project_adapter_sections(env_data)
        content.active_subtab = 0
        content.active_adapter_tab = 1  # discord tab
        content._set_current_cursor(0)

        rich_text = content.render()
        plain = rich_text.plain
        assert "discord.com/developers" in plain
        # Verify the URL has link style applied (Rich Style with link attribute)
        found_link = False
        for span in rich_text._spans:
            style = span.style
            if isinstance(style, str):
                continue
            if style and style.link and "discord.com" in style.link:
                found_link = True
                break
        assert found_link, "Expected OSC 8 link style on discord URL"


class TestGuidedModeAutoExpand:
    def test_guided_step_positions_cursor_on_first_unset_var(self) -> None:
        content = ConfigContent()
        env_data = [
            _env_status("TELEGRAM_BOT_TOKEN", "telegram", True),
            _env_status("TELEGRAM_SUPERGROUP_ID", "telegram", False),
            _env_status("TELEGRAM_USER_IDS", "telegram", False),
        ]
        content._env_data = env_data
        content._adapter_sections = project_adapter_sections(env_data)
        content._guided_mode = True
        content._guided_step_index = 0  # telegram step
        content._apply_guided_step()

        assert content._current_cursor() == 1  # first unset is SUPERGROUP_ID at index 1

    def test_guided_step_stays_at_zero_when_all_set(self) -> None:
        content = ConfigContent()
        env_data = [
            _env_status("TELEGRAM_BOT_TOKEN", "telegram", True),
            _env_status("TELEGRAM_SUPERGROUP_ID", "telegram", True),
            _env_status("TELEGRAM_USER_IDS", "telegram", True),
        ]
        content._env_data = env_data
        content._adapter_sections = project_adapter_sections(env_data)
        content._guided_mode = True
        content._guided_step_index = 0
        content._apply_guided_step()

        assert content._current_cursor() == 0
