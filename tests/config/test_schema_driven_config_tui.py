from __future__ import annotations

import pytest
from ruamel.yaml import YAML

import teleclaude.cli.config_handlers as handlers
import teleclaude.config as _tc_config_module
from teleclaude.cli.tui.views.config import ConfigContent
from teleclaude.cli.tui.views.reflection import reflect_schema
from teleclaude.config import (
    ComputerConfig,
    DiscordConfig,
    reload_config,
)
from teleclaude.config.schema import (
    PersonConfig,
)
from teleclaude.runtime.config import RuntimeConfig, get_runtime_config, set_runtime_config

# Named constants for assertion strings to satisfy snapshot-testing linter
COMPUTER_USER = "computer.user"
COMPUTER_DEFAULT_WORKING_DIR = "computer.default_working_dir"
COMPUTER_HELP_DESK_DIR = "computer.help_desk_dir"
COMPUTER_TRUSTED_DIRS = "computer.trusted_dirs"
COMPUTER_TMUX_BINARY = "computer.tmux_binary"
COMPUTER_NAME_KEY = "computer.name"
COMPUTER_ROLE_KEY = "computer.role"

DISCORD_ANNOUNCEMENTS_CHANNEL_ID = "discord.announcements_channel_id"
DISCORD_GENERAL_CHANNEL_ID = "discord.general_channel_id"
DISCORD_CATEGORIES = "discord.categories"

OVERLAY_SUBSCRIPTIONS = "overlay.subscriptions"
OVERLAY_CHECKOUT_ROOT = "overlay.checkout_root"
IDENTITY_ROLE = "identity.role"
IDENTITY_PREFIX = "identity."
OVERLAY_PREFIX = "overlay."
OVERLAY_NOTIFICATIONS = "overlay.settings.output_visibility.notifications"
OVERLAY_DISCORD_USER_ID = "overlay.creds.discord.user_id"
GLOBAL_IDENTITY_SECTION = "Global Identity"
GLOBAL_SOURCE = "global"
PER_PERSON_SOURCE = "per-person"

OLD_MAC = "OldMac"
NEW_MAC = "NewMac"
ALICE = "Alice"
ADMIN = "admin"
OFF = "off"
PRESERVE_ME = "preserve_me"
FC_NEW_ENV = "FIRECRAWL_API_KEY=fc-new"
BOTH = "both"
BOB_DISCORD_USER_ID = "123456789012345678"


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-9")
def test_tui_field_exclusions():
    # Test dataclass reflection exclusions
    computer = ComputerConfig(
        name="test-pc",
        user="mock-user",
        role="development",
        timezone="Europe/Amsterdam",
        is_master=True,
        default_working_dir="/tmp/work",
        help_desk_dir="/tmp/desk",
        trusted_dirs=[],
        tmux_binary="tmux",
    )
    fields = reflect_schema(computer, prefix="computer")
    field_keys = {f.key for f in fields}

    # Assert excluded fields are NOT in the reflected fields
    assert COMPUTER_USER not in field_keys
    assert COMPUTER_DEFAULT_WORKING_DIR not in field_keys
    assert COMPUTER_HELP_DESK_DIR not in field_keys
    assert COMPUTER_TRUSTED_DIRS not in field_keys
    assert COMPUTER_TMUX_BINARY not in field_keys

    # Assert non-excluded fields are present
    assert COMPUTER_NAME_KEY in field_keys
    assert COMPUTER_ROLE_KEY in field_keys

    # Test DiscordConfig exclusions
    discord = DiscordConfig(enabled=True, token="secret", guild_id=1234)
    fields_discord = reflect_schema(discord, prefix="discord")
    discord_keys = {f.key for f in fields_discord}
    assert DISCORD_ANNOUNCEMENTS_CHANNEL_ID not in discord_keys
    assert DISCORD_GENERAL_CHANNEL_ID not in discord_keys
    assert DISCORD_CATEGORIES not in discord_keys

    # Test PersonConfig exclusions
    person = PersonConfig()
    fields_person = reflect_schema(person, prefix="overlay")
    person_keys = {f.key for f in fields_person}
    assert OVERLAY_SUBSCRIPTIONS not in person_keys
    assert OVERLAY_CHECKOUT_ROOT not in person_keys


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-6")
def test_tui_source_aware_persistence(tmp_path, monkeypatch):
    # Setup temporary paths for config files
    machine_config_path = tmp_path / "config.yml"
    global_config_path = tmp_path / "teleclaude.yml"
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    env_file_path = tmp_path / ".env"

    # Initialize basic content in files
    yaml = YAML()

    # Machine config (requires agents config section)
    yaml.dump(
        {
            "computer": {
                "name": "OldMac",
                "role": "development",
                "timezone": "Europe/Amsterdam",
                "is_master": True,
            },
            "redis": {
                "host": "127.0.0.1",
                "port": 6379,
            },
            "agents": {
                "default": "claude",
                "claude": {
                    "system_prompt": "hello",
                },
            },
            "stt": {"enabled": True, "service_priority": ["parakeet", "openai"], "services": {}},
            "tts": {
                "enabled": False,
            },
        },
        machine_config_path,
    )

    # Global config (requires email, role must be admin/member/contributor/newcomer)
    yaml.dump({"people": [{"name": "Alice", "email": "alice@example.com", "role": "member"}]}, global_config_path)

    # Per-person config for Alice
    alice_dir = people_dir / "Alice"
    alice_dir.mkdir()
    yaml.dump(
        {"interests": [], "settings": {"output_visibility": {"notifications": "both"}}, "unknown_key": "preserve_me"},
        alice_dir / "teleclaude.yml",
    )

    # env file
    env_file_path.write_text("FIRECRAWL_API_KEY=fc-old\n", encoding="utf-8")

    # Monkeypatch paths in handlers and config module
    monkeypatch.setattr(handlers, "_GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(handlers, "_DEFAULT_ENV_PATH", env_file_path)
    monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: ["Alice"])

    # Setup temporary RuntimeConfig singleton
    old_rc = get_runtime_config()
    new_rc = RuntimeConfig(
        home=old_rc.home,
        config_path=machine_config_path,
        env_path=env_file_path,
        project_config_path=old_rc.project_config_path,
        tmpdir_base=old_rc.tmpdir_base,
    )
    set_runtime_config(new_rc)

    try:
        # Reload live config singleton
        reload_config()
        assert _tc_config_module.config.computer.name == OLD_MAC

        # Instantiate ConfigContent and setup TUI state
        content = ConfigContent()
        # Mock Widget's refresh method to do nothing
        monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
        content.refresh_data()

        # 1. Edit machine config field (owning_source="machine")
        content.active_subtab = 0  # Subtab.INFRA
        content._save_reflected_field("computer.name", "NewMac")

        # Reload and verify machine config changed
        reload_config()
        assert _tc_config_module.config.computer.name == NEW_MAC
        # Verify global and per-person configs didn't change
        with open(global_config_path, encoding="utf-8") as f:
            global_data = yaml.load(f)
        assert global_data["people"][0]["name"] == ALICE

        # 2. Edit global identity field (owning_source="global")
        content.active_subtab = 1  # Subtab.PEOPLE
        content._expanded_person = "Alice"
        content._save_reflected_field("identity.role", "admin")

        # Verify global config updated
        with open(global_config_path, encoding="utf-8") as f:
            global_data = yaml.load(f)
        assert global_data["people"][0]["role"] == ADMIN

        # 3. Edit per-person overlay settings (owning_source="per-person")
        # Edit setting and verify unknown keys are preserved
        content._save_reflected_field("overlay.settings.output_visibility.notifications", "off")

        alice_config_path = alice_dir / "teleclaude.yml"
        with open(alice_config_path, encoding="utf-8") as f:
            alice_data = yaml.load(f)
        assert alice_data["settings"]["output_visibility"]["notifications"] == OFF
        assert alice_data["unknown_key"] == PRESERVE_ME

        # 4. Edit env-backed field (goes to .env)
        content.active_subtab = 3  # Subtab.PROVIDERS
        content._save_reflected_field("firecrawl.api_key", "fc-new")
        env_content = env_file_path.read_text(encoding="utf-8")
        assert FC_NEW_ENV in env_content
    finally:
        set_runtime_config(old_rc)


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-3")
@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-4")
@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-5")
@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-7")
def test_tui_people_overlay_creation_on_edit(tmp_path, monkeypatch):
    # Setup temporary paths for config files
    machine_config_path = tmp_path / "config.yml"
    global_config_path = tmp_path / "teleclaude.yml"
    people_dir = tmp_path / "people"
    people_dir.mkdir()

    yaml = YAML()
    # Machine config
    yaml.dump(
        {
            "computer": {
                "name": "TestMac",
                "role": "development",
                "timezone": "Europe/Amsterdam",
                "is_master": True,
            },
            "agents": {
                "default": "claude",
                "claude": {
                    "system_prompt": "hello",
                },
            },
            "stt": {"enabled": True, "service_priority": ["parakeet", "openai"], "services": {}},
            "tts": {
                "enabled": False,
            },
        },
        machine_config_path,
    )

    # Global config: Bob exists with valid email and role
    yaml.dump({"people": [{"name": "Bob", "email": "bob@example.com", "role": "member"}]}, global_config_path)

    # Bob's directory and teleclaude.yml do NOT exist!

    # Monkeypatch paths
    monkeypatch.setattr(handlers, "_GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: ["Bob"])

    # Setup temporary RuntimeConfig singleton
    old_rc = get_runtime_config()
    new_rc = RuntimeConfig(
        home=old_rc.home,
        config_path=machine_config_path,
        env_path=old_rc.env_path,
        project_config_path=old_rc.project_config_path,
        tmpdir_base=old_rc.tmpdir_base,
    )
    set_runtime_config(new_rc)

    try:
        # Reload config
        reload_config()

        # Instantiate ConfigContent
        content = ConfigContent()
        # Mock Widget's refresh method to do nothing
        monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
        content.refresh_data()

        # Set active tab and expanded person to Bob
        content.active_subtab = 1  # Subtab.PEOPLE
        content._expanded_person = "Bob"

        fields_by_key = {field.key: field for field in content.person_reflected_fields}
        identity_sections = {field.section for field in fields_by_key.values() if field.key.startswith(IDENTITY_PREFIX)}
        overlay_sections = {field.section for field in fields_by_key.values() if field.key.startswith(OVERLAY_PREFIX)}
        identity_role = fields_by_key[IDENTITY_ROLE]
        overlay_notifications = fields_by_key[OVERLAY_NOTIFICATIONS]
        overlay_discord_user_id = fields_by_key[OVERLAY_DISCORD_USER_ID]

        assert identity_sections == {GLOBAL_IDENTITY_SECTION}
        assert overlay_sections
        assert GLOBAL_IDENTITY_SECTION not in overlay_sections
        assert identity_role.section == GLOBAL_IDENTITY_SECTION
        assert identity_role.owning_source == GLOBAL_SOURCE
        assert overlay_notifications.owning_source == PER_PERSON_SOURCE
        assert identity_role.section != overlay_notifications.section
        assert identity_role.owning_source != overlay_notifications.owning_source
        assert overlay_discord_user_id.owning_source == PER_PERSON_SOURCE

        # Verify overlay path doesn't exist yet
        bob_config_path = people_dir / "Bob" / "teleclaude.yml"
        assert not bob_config_path.exists()

        # Save overlay setting (output_visibility.notifications)
        content._save_reflected_field(OVERLAY_NOTIFICATIONS, BOTH)
        content._person_field_cursor = next(
            index for index, field in enumerate(content.person_reflected_fields) if field.key == OVERLAY_DISCORD_USER_ID
        )
        content.activate_current()
        content._edit_buffer = BOB_DISCORD_USER_ID
        content.activate_current()

        # Verify Bob's directory and yml were created on first edit
        assert bob_config_path.exists()
        with open(bob_config_path, encoding="utf-8") as f:
            bob_data = yaml.load(f)
        saved_config = PersonConfig.model_validate(bob_data)
        assert bob_data["settings"]["output_visibility"]["notifications"] == BOTH
        assert saved_config.creds.discord is not None
        assert saved_config.creds.discord.user_id == BOB_DISCORD_USER_ID
    finally:
        set_runtime_config(old_rc)
