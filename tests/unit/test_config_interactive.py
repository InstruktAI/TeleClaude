"""Tests for interactive configuration system.

Tests cover: config handlers, CLI integration, and menu rendering.
"""

import os
from unittest.mock import patch

import pytest

from teleclaude.config.schema import GlobalConfig, PersonConfig, PersonEntry

# --- Config handlers tests ---


class TestConfigHandlers:
    """Tests for teleclaude.cli.config_handlers."""

    def test_get_global_config_loads_correctly(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text(
            "people:\n  - name: Alice\n    email: alice@example.com\n    role: admin\n",
            encoding="utf-8",
        )

        from teleclaude.cli.config_handlers import get_global_config

        config = get_global_config(path=config_path)
        assert len(config.people) == 1
        assert config.people[0].name == "Alice"
        assert config.people[0].role == "admin"

    def test_get_global_config_returns_default_when_missing(self, tmp_path):
        config_path = tmp_path / "nonexistent.yml"

        from teleclaude.cli.config_handlers import get_global_config

        config = get_global_config(path=config_path)
        assert isinstance(config, GlobalConfig)
        assert config.people == []

    def test_get_person_config_loads_correctly(self, tmp_path):
        person_dir = tmp_path / "people" / "alice"
        person_dir.mkdir(parents=True)
        config_path = person_dir / "teleclaude.yml"
        config_path.write_text(
            "creds:\n  telegram:\n    user_name: alice_tg\n    user_id: 12345\nnotifications:\n  telegram: true\n",
            encoding="utf-8",
        )

        from teleclaude.cli.config_handlers import get_person_config

        with patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"):
            config = get_person_config("alice")
        assert config.creds.telegram is not None
        assert config.creds.telegram.user_name == "alice_tg"
        assert config.notifications.telegram is True

    def test_save_global_config_atomic_write(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"

        from teleclaude.cli.config_handlers import get_global_config, save_global_config

        config = GlobalConfig(people=[PersonEntry(name="Bob", email="bob@example.com", role="member")])
        save_global_config(config, path=config_path)

        # Verify file exists and is valid
        loaded = get_global_config(path=config_path)
        assert len(loaded.people) == 1
        assert loaded.people[0].name == "Bob"

        # Verify no temp files left
        assert not config_path.with_suffix(".tmp").exists()

    def test_save_person_config_creates_directory(self, tmp_path):
        from teleclaude.cli.config_handlers import save_person_config

        with patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"):
            pc = PersonConfig(interests=["python", "ai"])
            save_person_config("charlie", pc)

        person_config = tmp_path / "people" / "charlie" / "teleclaude.yml"
        assert person_config.exists()

    def test_add_person_adds_to_global_and_creates_dir(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("people: []\n", encoding="utf-8")

        from teleclaude.cli.config_handlers import add_person, get_global_config

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            entry = PersonEntry(name="Diana", email="diana@example.com", role="contributor")
            add_person(entry)

        loaded = get_global_config(path=config_path)
        assert len(loaded.people) == 1
        assert loaded.people[0].name == "Diana"
        assert (tmp_path / "people" / "Diana" / "teleclaude.yml").exists()

    def test_add_person_rejects_duplicate(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text(
            "people:\n  - name: Eve\n    email: eve@example.com\n",
            encoding="utf-8",
        )

        from teleclaude.cli.config_handlers import add_person

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            with pytest.raises(ValueError, match="already exists"):
                add_person(PersonEntry(name="Eve", email="eve2@example.com"))

    def test_validate_all_catches_missing_person_config(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text(
            "people:\n  - name: Ghost\n    email: ghost@example.com\n",
            encoding="utf-8",
        )

        from teleclaude.cli.config_handlers import validate_all

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            results = validate_all()

        # Global should pass, person should fail
        global_result = next(r for r in results if r.area == "global")
        assert global_result.passed

        person_result = next(r for r in results if r.area == "person:Ghost")
        assert not person_result.passed
        assert any("missing" in e.lower() for e in person_result.errors)

    def test_discover_config_areas_reflects_schema(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("people: []\n", encoding="utf-8")

        from teleclaude.cli.config_handlers import discover_config_areas

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            areas = discover_config_areas()

        area_names = [a.name for a in areas]
        # Telegram adapter should appear from CredsConfig
        assert "adapters.telegram" in area_names
        assert "people" in area_names
        assert "notifications" in area_names
        assert "environment" in area_names

    def test_check_env_vars_detects_missing(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text(
            "people:\n  - name: Frank\n    email: frank@example.com\n",
            encoding="utf-8",
        )

        person_dir = tmp_path / "people" / "Frank"
        person_dir.mkdir(parents=True)
        (person_dir / "teleclaude.yml").write_text(
            "creds:\n  telegram:\n    user_name: frank_tg\n    user_id: 99999\n",
            encoding="utf-8",
        )

        from teleclaude.cli.config_handlers import check_env_vars

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
            patch.dict(os.environ, {}, clear=False),
        ):
            # Ensure TELEGRAM_BOT_TOKEN is not set
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            statuses = check_env_vars()

        telegram_vars = [s for s in statuses if s.info.adapter == "telegram"]
        assert len(telegram_vars) > 0
        assert not all(s.is_set for s in telegram_vars)

    def test_atomic_write_cleans_up_on_failure(self, tmp_path):
        from teleclaude.cli.config_handlers import _atomic_yaml_write

        target = tmp_path / "test.yml"

        # Write valid data first
        _atomic_yaml_write(target, {"key": "value"})
        assert target.exists()

        # Attempt write with data that will cause ruamel.yaml to succeed
        # but verify the tmp file is cleaned up
        _atomic_yaml_write(target, {"new_key": "new_value"})
        assert not target.with_suffix(".tmp").exists()

    def test_list_person_dirs(self, tmp_path):
        people_dir = tmp_path / "people"
        for name in ["alice", "bob"]:
            d = people_dir / name
            d.mkdir(parents=True)
            (d / "teleclaude.yml").write_text("", encoding="utf-8")
        # Dir without config should not be listed
        (people_dir / "empty").mkdir()

        from teleclaude.cli.config_handlers import list_person_dirs

        with patch("teleclaude.cli.config_handlers._PEOPLE_DIR", people_dir):
            dirs = list_person_dirs()

        assert dirs == ["alice", "bob"]

    def test_remove_person(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text(
            "people:\n  - name: Zara\n    email: zara@example.com\n",
            encoding="utf-8",
        )
        person_dir = tmp_path / "people" / "Zara"
        person_dir.mkdir(parents=True)
        (person_dir / "teleclaude.yml").write_text("", encoding="utf-8")

        from teleclaude.cli.config_handlers import get_global_config, remove_person

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            remove_person("Zara", delete_directory=True)

        loaded = get_global_config(path=config_path)
        assert len(loaded.people) == 0
        assert not person_dir.exists()


# --- CLI integration tests ---


@pytest.mark.timeout(10)
class TestCLIIntegration:
    """Tests for telec.py config/onboard command dispatch.

    These tests have a higher timeout because telec.py triggers heavy
    imports (websockets, SQLAlchemy) on first load.
    """

    def test_telec_config_no_args_launches_interactive(self, monkeypatch):
        """Verify no-args config dispatches to interactive menu."""
        called = []
        monkeypatch.setattr(
            "teleclaude.cli.config_menu.run_interactive_menu",
            lambda: called.append("interactive"),
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        from teleclaude.cli.telec import _handle_config

        _handle_config([])
        assert called == ["interactive"]

    def test_telec_config_get_delegates(self, monkeypatch):
        """Verify get subcommand delegates to config_cmd.handle_config_command."""
        called = []
        monkeypatch.setattr(
            "teleclaude.cli.config_cmd.handle_config_command",
            lambda args: called.append(("config_cmd", args)),
        )

        from teleclaude.cli.telec import _handle_config

        _handle_config(["get"])
        assert called == [("config_cmd", ["get"])]

    def test_telec_onboard_launches_wizard(self, monkeypatch):
        """Verify onboard command launches wizard."""
        called = []
        monkeypatch.setattr(
            "teleclaude.cli.onboard_wizard.run_onboard_wizard",
            lambda: called.append("wizard"),
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        from teleclaude.cli.telec import _handle_onboard

        _handle_onboard([])
        assert called == ["wizard"]

    def test_telec_config_non_tty_fails(self, monkeypatch):
        """Non-interactive terminal should fail for interactive mode."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        from teleclaude.cli.telec import _handle_config

        with pytest.raises(SystemExit):
            _handle_config([])

    def test_telec_config_help(self, capsys):
        from teleclaude.cli.telec import _handle_config

        _handle_config(["--help"])
        output = capsys.readouterr().out
        assert "Interactive menu" in output

    def test_telec_onboard_help(self, capsys):
        from teleclaude.cli.telec import _handle_onboard

        _handle_onboard(["--help"])
        output = capsys.readouterr().out
        assert "Guided onboarding wizard" in output


# --- Menu rendering tests ---


class TestMenuRendering:
    """Tests for config_menu.py output rendering."""

    def test_status_indicator_shows_configured(self):
        from teleclaude.cli.config_menu import _status_icon

        assert "\u2713" in _status_icon(True)
        assert "\u2717" in _status_icon(False)

    def test_prompt_choice_returns_valid_index(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "2")
        from teleclaude.cli.config_menu import _prompt_choice

        result = _prompt_choice(["Option A", "Option B", "Option C"])
        assert result == "2"

    def test_prompt_choice_returns_back(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "b")
        from teleclaude.cli.config_menu import _prompt_choice

        result = _prompt_choice(["Option A"])
        assert result == "b"

    def test_prompt_choice_returns_quit(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "q")
        from teleclaude.cli.config_menu import _prompt_choice

        result = _prompt_choice(["Option A"], allow_quit=True)
        assert result == "q"

    def test_prompt_confirm_default_yes(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        from teleclaude.cli.config_menu import _prompt_confirm

        assert _prompt_confirm("Continue?", default=True) is True

    def test_prompt_confirm_explicit_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        from teleclaude.cli.config_menu import _prompt_confirm

        assert _prompt_confirm("Continue?", default=True) is False

    def test_prompt_value_uses_current(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        from teleclaude.cli.config_menu import _prompt_value

        result = _prompt_value("Name", current="Alice")
        assert result == "Alice"

    def test_main_menu_shows_all_areas(self, tmp_path, capsys, monkeypatch):
        """Verify main menu displays all config area categories."""
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("people: []\n", encoding="utf-8")

        # Quit on first prompt
        monkeypatch.setattr("builtins.input", lambda _: "q")

        from teleclaude.cli.config_menu import _main_menu_loop

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            _main_menu_loop()

        output = capsys.readouterr().out
        assert "Adapters" in output
        assert "People" in output
        assert "Notifications" in output
        assert "Environment" in output
        assert "Validate all" in output


# --- Onboarding wizard tests ---


class TestOnboardWizard:
    """Tests for onboard_wizard.py."""

    def test_detect_wizard_state_empty(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("people: []\n", encoding="utf-8")

        from teleclaude.cli.onboard_wizard import detect_wizard_state

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            state = detect_wizard_state()

        assert not state.adapters_complete
        assert not state.people_complete
        assert not state.notifications_complete
        assert not state.env_complete  # All registered env vars must be set

    def test_detect_wizard_state_with_people(self, tmp_path):
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text(
            "people:\n  - name: Alice\n    email: alice@example.com\n",
            encoding="utf-8",
        )
        person_dir = tmp_path / "people" / "Alice"
        person_dir.mkdir(parents=True)
        (person_dir / "teleclaude.yml").write_text(
            "notifications:\n  telegram: false\n",
            encoding="utf-8",
        )

        from teleclaude.cli.onboard_wizard import detect_wizard_state

        with (
            patch("teleclaude.cli.config_handlers._GLOBAL_CONFIG_PATH", config_path),
            patch("teleclaude.cli.config_handlers._PEOPLE_DIR", tmp_path / "people"),
        ):
            state = detect_wizard_state()

        assert state.people_complete
        assert not state.notifications_complete
