from __future__ import annotations

import dataclasses

import pytest
from rich.style import Style
from rich.text import Text
from ruamel.yaml import YAML

import teleclaude.cli.config_handlers as handlers
import teleclaude.config as _tc_config_module
import teleclaude.config.loader as loader
from teleclaude.cli.tui.views._config_constants import _SUBTABS, Subtab
from teleclaude.cli.tui.views.config import ConfigContent
from teleclaude.cli.tui.views.config_render import _MASKED_VALUE
from teleclaude.cli.tui.views.reflection import ReflectedField, reflect_schema
from teleclaude.config import (
    ComputerConfig,
    DiscordConfig,
    TelegramConfig,
    WhatsAppConfig,
    parse_tts_config,
    reload_config,
)
from teleclaude.config.schema import (
    CompanyConfig,
    PersonConfig,
)
from teleclaude.config.tiers import Tier
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.runtime.config import RuntimeConfig, get_runtime_config, set_runtime_config

# Named constants for assertion strings to satisfy snapshot-testing linter
COMPUTER_USER = "computer.user"
COMPUTER_DEFAULT_WORKING_DIR = "computer.default_working_dir"
COMPUTER_HELP_DESK_DIR = "computer.help_desk_dir"
COMPUTER_TRUSTED_DIRS = "computer.trusted_dirs"
COMPUTER_TMUX_BINARY = "computer.tmux_binary"
COMPUTER_NAME_KEY = "computer.name"
COMPUTER_ROLE_KEY = "computer.role"
COMPUTER_HOST = "computer.host"
TELEGRAM_QOS_PREFIX = "telegram.qos"
WHATSAPP_QOS_PREFIX = "whatsapp.qos"
WHATSAPP_API_VERSION = "whatsapp.api_version"
WHATSAPP_ENABLED = "whatsapp.enabled"
COMPUTER_IS_INGRESS_NODE = "computer.is_ingress_node"
CHIPTUNES_ENABLED = "chiptunes.enabled"
CHIPTUNES_MUSIC_DIR = "chiptunes.music_dir"
CHIPTUNES_SECTION = "Chiptunes"
MACHINE_SOURCE = "machine"

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
OVERLAY_TELEGRAM_USER_NAME = "overlay.creds.telegram.user_name"
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

TTS_SESSION_START_ENABLED = "tts.events.session_start.enabled"
TTS_SESSION_START_MESSAGES = "tts.events.session_start.messages"
TTS_AGENT_STOP_MESSAGES = "tts.events.agent_stop.messages"
TTS_OPENAI_ENABLED = "tts.services.openai.enabled"
TTS_OPENAI_VOICE_NAME = "tts.services.openai.voices.0.name"
TTS_SESSION_START_GREETINGS = ["Hello", "Hey there"]
TTS_AGENT_STOP_LEGACY = "Done"
TTS_MACOS_PREFIX = "tts.services.macos"
TTS_MACOS_MODEL = "tts.services.macos.model"
TTS_MACOS_PARAMS = "tts.services.macos.params"
TTS_ELEVENLABS_PREFIX = "tts.services.elevenlabs"
TTS_PYTTSX3_VOICES = "tts.services.pyttsx3.voices"
TTS_VOXCPM_MODEL = "tts.services.voxcpm.model"
VOICE_ID_SUFFIX = "voice_id"
TTS_STT_SUBTAB_INDEX = _SUBTABS.index(Subtab.TTS_STT)
STT_OPENAI_ENABLED = "stt.services.openai.enabled"
TTS_VOXCPM_ENABLED = "tts.services.voxcpm.enabled"
DEFAULT_TTS_SERVICES = ("pyttsx3", "macos", "openai", "elevenlabs")
EXPANDED_TTS_HEADER = "▼ TTS"
COLLAPSED_STT_HEADER = "▶ STT"
SERVICES_BRANCH_LABEL = "Services"
NESTED_BRANCH_INDENT = "    "


def _is_struct_list(value: object) -> bool:
    return isinstance(value, list) and any(dataclasses.is_dataclass(item) for item in value)


@pytest.fixture
def machine_tui(tmp_path, monkeypatch):
    """Build a ConfigContent over an isolated machine config; restore runtime config on teardown."""
    old_rc = get_runtime_config()

    def _build(machine_config):
        machine_config_path = tmp_path / "config.yml"
        global_config_path = tmp_path / "teleclaude.yml"
        people_dir = tmp_path / "people"
        people_dir.mkdir(exist_ok=True)
        env_file_path = tmp_path / ".env"
        env_file_path.write_text("", encoding="utf-8")

        yaml = YAML()
        yaml.dump(machine_config, machine_config_path)
        yaml.dump({"people": []}, global_config_path)

        monkeypatch.setattr(handlers, "_GLOBAL_CONFIG_PATH", global_config_path)
        monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
        monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_config_path)
        monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
        monkeypatch.setattr(handlers, "_DEFAULT_ENV_PATH", env_file_path)
        monkeypatch.setattr(handlers, "list_person_dirs", lambda: [])
        monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
        monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)

        set_runtime_config(
            RuntimeConfig(
                home=old_rc.home,
                config_path=machine_config_path,
                env_path=env_file_path,
                project_config_path=old_rc.project_config_path,
                tmpdir_base=old_rc.tmpdir_base,
            )
        )
        reload_config()
        content = ConfigContent()
        monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
        content.refresh_data()
        return content, machine_config_path

    yield _build
    set_runtime_config(old_rc)


FIRECRAWL_API_KEY_FIELD = "firecrawl.api_key"
FIRECRAWL_API_KEY_VAR = "FIRECRAWL_API_KEY"
SECRET_TOKEN = "super-secret-token-value"
API_KEY_LABEL = "Api Key"


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-10")
def test_nested_dict_structures_render_recursively_to_leaves():
    raw_tts = {
        "enabled": True,
        "events": {
            "session_start": {"enabled": True, "messages": TTS_SESSION_START_GREETINGS},
            "agent_stop": {"enabled": False, "message": TTS_AGENT_STOP_LEGACY},  # legacy single message
        },
        "services": {
            "openai": {"enabled": True, "model": "tts-1", "voices": [{"name": "alloy", "voice_id": "v-1"}]},
        },
    }
    tts_obj = parse_tts_config(raw_tts)
    assert tts_obj is not None

    fields = reflect_schema(tts_obj, prefix="tts", section="TTS", owning_source=MACHINE_SOURCE)
    keys_to_values = {f.key: f.value for f in fields}

    # Every nested leaf is reachable by its full dotted path.
    assert TTS_SESSION_START_ENABLED in keys_to_values
    assert TTS_SESSION_START_MESSAGES in keys_to_values
    assert TTS_AGENT_STOP_MESSAGES in keys_to_values
    assert TTS_OPENAI_ENABLED in keys_to_values

    # A list of structs expands to indexed leaves, never a single struct-list blob.
    assert TTS_OPENAI_VOICE_NAME in keys_to_values
    assert all(not isinstance(value, dict) for value in keys_to_values.values())
    assert all(not _is_struct_list(value) for value in keys_to_values.values())

    # The loader round-trips the event messages list, and folds a legacy single
    # `message` into the same list so nothing is lost.
    assert keys_to_values[TTS_SESSION_START_MESSAGES] == TTS_SESSION_START_GREETINGS
    assert keys_to_values[TTS_AGENT_STOP_MESSAGES] == [TTS_AGENT_STOP_LEGACY]


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-11")
def test_env_sourced_value_masked_unless_editing(monkeypatch):
    content = ConfigContent()
    monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)

    field = ReflectedField(
        key=FIRECRAWL_API_KEY_FIELD,
        name=API_KEY_LABEL,
        field_type=str,
        value=SECRET_TOKEN,
        env_var=FIRECRAWL_API_KEY_VAR,
        owning_source=MACHINE_SOURCE,
    )

    not_editing = Text()
    content._render_reflected_field(not_editing, field, selected=False, prefix=" ", row_style=Style())
    assert _MASKED_VALUE in not_editing.plain
    assert SECRET_TOKEN not in not_editing.plain

    content._editing_var_name = field.key
    content._edit_buffer = SECRET_TOKEN
    editing = Text()
    content._render_reflected_field(editing, field, selected=False, prefix=" ", row_style=Style())
    assert SECRET_TOKEN in editing.plain


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-10")
def test_nested_leaf_persists_to_its_dotted_path(machine_tui):
    content, machine_config_path = machine_tui(
        {
            "computer": {"name": "PC", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
            "tts": {"enabled": True, "events": {"session_start": {"messages": TTS_SESSION_START_GREETINGS}}},
        }
    )

    content.active_subtab = TTS_STT_SUBTAB_INDEX
    # The nested event leaf is reachable through the schema-driven renderer.
    assert TTS_SESSION_START_ENABLED in {field.key for field in content.reflected_fields}

    # Saving a non-default value persists it to the leaf's dotted path.
    content._save_reflected_field(TTS_SESSION_START_ENABLED, True)

    with open(machine_config_path, encoding="utf-8") as f:
        data = YAML().load(f)
    assert data["tts"]["events"]["session_start"]["enabled"] is True


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-1")
@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-6")
@pytest.mark.parametrize(
    ("stored", "expected"),
    [(True, True), (False, False)],
)
def test_is_ingress_node_reflects_stored_value_in_infra(machine_tui, stored, expected):
    """Read (config -> TUI): the Infra subtab reflects the stored is_ingress_node value."""
    content, _ = machine_tui(
        {
            "computer": {
                "name": "PC",
                "role": "development",
                "timezone": "Europe/Amsterdam",
                "is_master": True,
                "is_ingress_node": stored,
            },
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
        }
    )

    content.active_subtab = 0  # Subtab.INFRA
    fields_by_key = {field.key: field for field in content.reflected_fields}
    assert COMPUTER_IS_INGRESS_NODE in fields_by_key
    assert fields_by_key[COMPUTER_IS_INGRESS_NODE].value is expected


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-1")
def test_is_ingress_node_defaults_false_when_omitted_in_infra(machine_tui):
    """Read (config -> TUI): an omitted is_ingress_node reflects as False, not absent."""
    content, _ = machine_tui(
        {
            "computer": {"name": "PC", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
        }
    )

    content.active_subtab = 0  # Subtab.INFRA
    fields_by_key = {field.key: field for field in content.reflected_fields}
    assert COMPUTER_IS_INGRESS_NODE in fields_by_key
    assert fields_by_key[COMPUTER_IS_INGRESS_NODE].value is False


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-6")
def test_is_ingress_node_edit_persists_to_machine_config(machine_tui):
    """Write (TUI -> config): toggling is_ingress_node from the Infra subtab persists to config.yml."""
    content, _ = machine_tui(
        {
            "computer": {"name": "PC", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
        }
    )

    content.active_subtab = 0  # Subtab.INFRA
    content._save_reflected_field(COMPUTER_IS_INGRESS_NODE, True)

    reload_config()
    assert _tc_config_module.config.computer.is_ingress_node is True


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-13")
def test_default_nested_entries_shown_when_user_omits_them(monkeypatch):
    content = ConfigContent()
    monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
    content._raw_config = {"tts": {"enabled": True, "services": {"voxcpm": {"enabled": True}}}}
    content.active_subtab = TTS_STT_SUBTAB_INDEX

    keys = {f.key for f in content.reflected_fields}
    # The user's own service is present alongside the default-only services.
    assert TTS_VOXCPM_ENABLED in keys
    for service in DEFAULT_TTS_SERVICES:
        assert f"tts.services.{service}.enabled" in keys


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-13")
def test_tts_engine_inapplicable_fields_hidden_and_defaults_surface(monkeypatch):
    content = ConfigContent()
    monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
    content._raw_config = {
        "tts": {
            "enabled": True,
            "events": {"session_start": {"enabled": True}},
            "services": {
                "macos": {"enabled": True, "voices": [{"name": "Samantha"}]},
                "elevenlabs": {"enabled": True, "voices": [{"name": "Rachel", "voice_id": "abc"}]},
                "pyttsx3": {"enabled": True},
                "voxcpm": {"enabled": True, "model": "m"},
            },
        }
    }
    content.active_subtab = TTS_STT_SUBTAB_INDEX
    keys = {f.key: f.value for f in content.reflected_fields}

    # Name-based engine: voice_id and model/params do not apply, so they are not shown.
    assert not any(k.startswith(TTS_MACOS_PREFIX) and k.endswith(VOICE_ID_SUFFIX) for k in keys)
    assert TTS_MACOS_MODEL not in keys
    assert TTS_MACOS_PARAMS not in keys
    # Id-based engine keeps voice_id.
    assert any(k.startswith(TTS_ELEVENLABS_PREFIX) and k.endswith(VOICE_ID_SUFFIX) for k in keys)
    # Engine without a voice list shows no voices leaf.
    assert TTS_PYTTSX3_VOICES not in keys
    # Model-bearing (MLX) engine keeps its model.
    assert TTS_VOXCPM_MODEL in keys
    # The built-in greeting pool surfaces as the editable session_start default.
    assert keys[TTS_SESSION_START_MESSAGES] == list(SESSION_START_MESSAGES)


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-12")
def test_nested_tree_renders_indented_without_collision(monkeypatch):
    content = ConfigContent()
    monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
    content._raw_config = {
        "stt": {"enabled": True, "services": {"openai": {"enabled": True}}},
        "tts": {"enabled": True, "services": {"openai": {"enabled": True}}},
    }
    content.active_subtab = TTS_STT_SUBTAB_INDEX

    fields = content.reflected_fields
    keys = {f.key for f in fields}
    # Same-named leaves under different roots stay distinct (no collision).
    assert STT_OPENAI_ENABLED in keys
    assert TTS_OPENAI_ENABLED in keys

    tts_index = next(i for i, f in enumerate(fields) if f.key.split(".", 1)[0] == "tts")
    content._cursor_by_context[content._current_context_key()] = tts_index
    lines = content.render().plain.splitlines()

    # The active root expands, the other collapses — they never merge.
    assert any(line.strip() == EXPANDED_TTS_HEADER for line in lines)
    assert any(line.strip().startswith(COLLAPSED_STT_HEADER) for line in lines)
    # The nested branch renders indented beneath its root.
    services_line = next(line for line in lines if line.strip() == SERVICES_BRANCH_LABEL)
    assert services_line.startswith(NESTED_BRANCH_INDENT)


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-14")
def test_value_reset_to_default_is_pruned_from_config(machine_tui):
    # session_start.enabled defaults to False; store a non-default True to start.
    content, machine_config_path = machine_tui(
        {
            "computer": {"name": "PC", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
            "tts": {"enabled": True, "events": {"session_start": {"enabled": True}}},
        }
    )
    content.active_subtab = TTS_STT_SUBTAB_INDEX

    # Reset the field to its default (False): it should be pruned from the file.
    content._save_reflected_field(TTS_SESSION_START_ENABLED, False)

    with open(machine_config_path, encoding="utf-8") as f:
        data = YAML().load(f)
    events = (data.get("tts") or {}).get("events") or {}
    assert "session_start" not in events

    # But it still renders (via the default) on the next build.
    content.refresh_data()
    content.active_subtab = TTS_STT_SUBTAB_INDEX
    assert TTS_SESSION_START_ENABLED in {field.key for field in content.reflected_fields}


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
    # host is loader-honored (override of the auto-detected LAN IP), so it stays editable.
    assert COMPUTER_HOST in field_keys

    # Test DiscordConfig exclusions
    discord = DiscordConfig(enabled=True, token="secret", guild_id=1234)
    fields_discord = reflect_schema(discord, prefix="discord")
    discord_keys = {f.key for f in fields_discord}
    assert DISCORD_ANNOUNCEMENTS_CHANNEL_ID not in discord_keys
    assert DISCORD_GENERAL_CHANNEL_ID not in discord_keys
    assert DISCORD_CATEGORIES not in discord_keys

    # QoS blocks and the pinned WhatsApp API version are not read from config, so
    # they are not exposed for editing (consistent with Discord's qos exclusion).
    telegram_keys = {f.key for f in reflect_schema(TelegramConfig(enabled=True), prefix="telegram")}
    assert not any(key.startswith(TELEGRAM_QOS_PREFIX) for key in telegram_keys)
    whatsapp_keys = {f.key for f in reflect_schema(WhatsAppConfig(enabled=True), prefix="whatsapp")}
    assert not any(key.startswith(WHATSAPP_QOS_PREFIX) for key in whatsapp_keys)
    assert WHATSAPP_API_VERSION not in whatsapp_keys

    # Test PersonConfig exclusions
    person = PersonConfig()
    fields_person = reflect_schema(person, prefix="overlay")
    person_keys = {f.key for f in fields_person}
    assert OVERLAY_SUBSCRIPTIONS not in person_keys
    assert OVERLAY_CHECKOUT_ROOT not in person_keys


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-15")
def test_visibility_is_opt_in_via_per_field_tier():
    # Only fields declared tier=tui render; internal and public do not, and the
    # decision is read from the field's tier declaration, not a TUI-local name list.
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
    computer_keys = {f.key for f in reflect_schema(computer, prefix="computer")}
    assert COMPUTER_NAME_KEY in computer_keys  # tier=tui renders
    assert COMPUTER_USER not in computer_keys  # tier=internal hidden
    assert COMPUTER_TRUSTED_DIRS not in computer_keys  # tier=public is sampled, not rendered

    # The tier defaults to internal when no declaration is present: an unmarked
    # field stays hidden until deliberately declared tui.
    whatsapp_keys = {f.key for f in reflect_schema(WhatsAppConfig(enabled=True), prefix="whatsapp")}
    assert WHATSAPP_ENABLED not in whatsapp_keys


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
    yaml.dump(
        {"people": [{"name": "Alice", "email": "alice@example.com", "role": "member", "slug": "alice"}]},
        global_config_path,
    )

    # Per-person config for Alice, in her slug-named folder
    alice_dir = people_dir / "alice"
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
    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(handlers, "_DEFAULT_ENV_PATH", env_file_path)
    monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: ["alice"])

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
        fields_by_key = {field.key: field for field in content.reflected_fields}
        assert fields_by_key[CHIPTUNES_ENABLED].section == CHIPTUNES_SECTION
        assert fields_by_key[CHIPTUNES_ENABLED].owning_source == MACHINE_SOURCE
        assert fields_by_key[CHIPTUNES_MUSIC_DIR].section == CHIPTUNES_SECTION
        content._save_reflected_field("computer.name", "NewMac")

        # Reload and verify machine config changed
        reload_config()
        assert _tc_config_module.config.computer.name == NEW_MAC
        # Verify global and per-person configs didn't change
        with open(global_config_path, encoding="utf-8") as f:
            global_data = yaml.load(f)
        assert global_data["people"][0]["name"] == ALICE

        # 2. Edit global identity field (owning_source="global")
        content.active_subtab = _SUBTABS.index(Subtab.PEOPLE)
        content._expanded_person = "alice"
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
        content.active_subtab = _SUBTABS.index(Subtab.PROVIDERS)
        content._save_reflected_field("firecrawl.api_key", "fc-new")
        env_content = env_file_path.read_text(encoding="utf-8")
        assert FC_NEW_ENV in env_content

        # 5. Edit machine-backed chiptunes gate from the Infra tab.
        content.active_subtab = 0  # Subtab.INFRA
        content._save_reflected_field(CHIPTUNES_ENABLED, True)
        reload_config()
        assert _tc_config_module.config.chiptunes is not None
        assert _tc_config_module.config.chiptunes.enabled is True
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

    # Global config: Bob exists with valid email, role, and slug
    yaml.dump(
        {"people": [{"name": "Bob", "email": "bob@example.com", "role": "member", "slug": "bob"}]},
        global_config_path,
    )

    # Bob's directory and teleclaude.yml do NOT exist!

    # Monkeypatch paths
    monkeypatch.setattr(handlers, "_GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: ["bob"])

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
        content.active_subtab = _SUBTABS.index(Subtab.PEOPLE)
        content._expanded_person = "bob"

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
        bob_config_path = people_dir / "bob" / "teleclaude.yml"
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

        # Editing one required credential leaf on a fresh submodel must persist a
        # schema-valid overlay: telegram requires both user_name and user_id, so
        # the missing sibling is seeded with a placeholder rather than deadlocking
        # or writing an invalid file.
        content._person_field_cursor = next(
            index
            for index, field in enumerate(content.person_reflected_fields)
            if field.key == OVERLAY_TELEGRAM_USER_NAME
        )
        content.activate_current()
        content._edit_buffer = ALICE
        content.activate_current()

        assert not content._status_is_error
        with open(bob_config_path, encoding="utf-8") as f:
            bob_after = yaml.load(f)
        saved_after = PersonConfig.model_validate(bob_after)
        assert saved_after.creds.telegram is not None
        assert saved_after.creds.telegram.user_name == ALICE
        assert saved_after.creds.telegram.user_id == 0
    finally:
        set_runtime_config(old_rc)


_COMPANY_NAME_KEY = "company.name"
_COMPANY_GIT_KEY = "company.git"
_DISCOVERED_COMPANY_NAME_KEY = "company:acme.name"
_PERSON_COMPANIES_KEY = "overlay.companies"
_INFRA_TAB_INDEX = 0
_COMPANIES_TAB_INDEX = 1


def test_companies_tab_is_second_and_renders_company_schema():
    """The Companies tab sits right after Infra and renders the CompanyConfig schema fields."""
    assert _SUBTABS.index(Subtab.INFRA) == _INFRA_TAB_INDEX
    assert _SUBTABS.index(Subtab.COMPANIES) == _COMPANIES_TAB_INDEX

    content = ConfigContent()
    content.active_subtab = _COMPANIES_TAB_INDEX
    keys = {field.key for field in content.reflected_fields}

    assert _COMPANY_NAME_KEY in keys
    assert _COMPANY_GIT_KEY in keys


def test_companies_tab_renders_discovered_company():
    """A folder-discovered company renders schema-driven, keyed by its slug."""
    content = ConfigContent()
    content._companies_data = [("acme", CompanyConfig(name="Acme", slug="acme"))]
    content.active_subtab = _COMPANIES_TAB_INDEX

    keys = {field.key for field in content.reflected_fields}

    assert _DISCOVERED_COMPANY_NAME_KEY in keys


def test_person_overlay_surfaces_company_multireference():
    """The People overlay schema surfaces the person's company multi-reference for editing."""
    fields = reflect_schema(
        PersonConfig(companies=["acme"]),
        prefix="overlay",
        section="Overlay Settings",
        owning_source="per-person",
        inherited_tier=Tier.TUI,
    )

    assert _PERSON_COMPANIES_KEY in {field.key for field in fields}


_ACME = "acme"
_NEW_COMPANY_DESC = "Updated by the operator"
_COMPANY_DESC_FIELD = "company:acme.description"
_EDITED_PERSON_COMPANIES = ["acme", "beta-co"]


def _isolated_config_content(tmp_path, monkeypatch):
    """Build a ConfigContent over isolated machine/global/people/company config files."""
    machine_config_path = tmp_path / "config.yml"
    global_config_path = tmp_path / "teleclaude.yml"
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    env_file_path = tmp_path / ".env"
    env_file_path.write_text("", encoding="utf-8")
    companies_root = tmp_path / "companies"

    yaml = YAML()
    yaml.dump(
        {
            "computer": {"name": "Mac", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
        },
        machine_config_path,
    )
    yaml.dump(
        {"people": [{"name": "Alice", "email": "alice@example.com", "role": "member", "slug": "alice"}]},
        global_config_path,
    )
    (people_dir / "alice").mkdir()
    yaml.dump({"interests": []}, people_dir / "alice" / "teleclaude.yml")
    acme_dir = companies_root / _ACME
    acme_dir.mkdir(parents=True)
    yaml.dump({"name": "Acme", "slug": _ACME, "description": "original"}, acme_dir / "teleclaude.yml")

    monkeypatch.setattr(handlers, "_GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(handlers, "_PEOPLE_DIR", people_dir)
    monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_config_path)
    monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
    monkeypatch.setattr(loader, "COMPANIES_ROOT", companies_root)
    monkeypatch.setattr(handlers, "_DEFAULT_ENV_PATH", env_file_path)
    monkeypatch.setattr(handlers, "list_person_dirs", lambda: ["alice"])
    monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)

    old_rc = get_runtime_config()
    set_runtime_config(
        RuntimeConfig(
            home=old_rc.home,
            config_path=machine_config_path,
            env_path=env_file_path,
            project_config_path=old_rc.project_config_path,
            tmpdir_base=old_rc.tmpdir_base,
        )
    )
    reload_config()
    content = ConfigContent()
    monkeypatch.setattr(content, "refresh", lambda *args, **kwargs: None)
    content.refresh_data()
    return content, people_dir, companies_root, old_rc


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-6")
def test_company_field_edit_persists_through_tui(tmp_path, monkeypatch):
    """Editing a CompanyConfig field through the real TUI save path writes the company overlay."""
    content, _people_dir, companies_root, old_rc = _isolated_config_content(tmp_path, monkeypatch)
    try:
        content.active_subtab = _SUBTABS.index(Subtab.COMPANIES)
        assert _COMPANY_DESC_FIELD in {field.key for field in content.reflected_fields}

        content._save_reflected_field(_COMPANY_DESC_FIELD, _NEW_COMPANY_DESC)

        saved = YAML().load((companies_root / _ACME / "teleclaude.yml").read_text(encoding="utf-8"))
        assert saved["description"] == _NEW_COMPANY_DESC
    finally:
        set_runtime_config(old_rc)


@pytest.mark.spec("project/spec/feature/config/schema-driven-config-tui", "UC-CFG-TUI-SCHEMA-6")
def test_person_company_multireference_edit_persists_through_tui(tmp_path, monkeypatch):
    """Editing the People company multi-reference through the real TUI save path writes the overlay."""
    content, people_dir, _companies_root, old_rc = _isolated_config_content(tmp_path, monkeypatch)
    try:
        content.active_subtab = _SUBTABS.index(Subtab.PEOPLE)
        content._expanded_person = "alice"

        content._save_reflected_field(_PERSON_COMPANIES_KEY, _EDITED_PERSON_COMPANIES)

        saved = YAML().load((people_dir / "alice" / "teleclaude.yml").read_text(encoding="utf-8"))
        assert list(saved["companies"]) == _EDITED_PERSON_COMPANIES
    finally:
        set_runtime_config(old_rc)
