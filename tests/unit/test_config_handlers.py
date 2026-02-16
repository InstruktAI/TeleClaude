import fcntl
import os
from pathlib import Path

import pytest

from teleclaude.cli import config_handlers
from teleclaude.config.schema import GlobalConfig, PersonConfig, PersonEntry


@pytest.fixture
def mock_teleclaude_dir(tmp_path, monkeypatch):
    """Override _TELECLAUDE_DIR and related paths for testing."""
    tele_dir = tmp_path / ".teleclaude"
    tele_dir.mkdir()

    monkeypatch.setattr(config_handlers, "_TELECLAUDE_DIR", tele_dir)
    monkeypatch.setattr(config_handlers, "_GLOBAL_CONFIG_PATH", tele_dir / "teleclaude.yml")
    monkeypatch.setattr(config_handlers, "_PEOPLE_DIR", tele_dir / "people")

    return tele_dir


def test_get_global_config_default(mock_teleclaude_dir):
    config = config_handlers.get_global_config()
    assert isinstance(config, GlobalConfig)
    assert len(config.people) == 0


def test_save_and_load_global_config(mock_teleclaude_dir):
    config = GlobalConfig(people=[PersonEntry(name="Alice", role="admin")])
    config_handlers.save_global_config(config)

    loaded = config_handlers.get_global_config()
    assert len(loaded.people) == 1
    assert loaded.people[0].name == "Alice"


def test_get_person_config_default(mock_teleclaude_dir):
    # Should return default if dir/file doesn't exist
    config = config_handlers.get_person_config("Bob")
    assert isinstance(config, PersonConfig)


def test_save_and_load_person_config(mock_teleclaude_dir):
    config = PersonConfig()
    config.creds.telegram = {"token": "test-token", "user_name": "test-user", "user_id": 12345}
    config_handlers.save_person_config("Bob", config)

    loaded = config_handlers.get_person_config("Bob")
    assert loaded.creds.telegram.token == "test-token"
    assert (mock_teleclaude_dir / "people" / "Bob" / "teleclaude.yml").exists()


def test_list_people(mock_teleclaude_dir):
    config = GlobalConfig(people=[PersonEntry(name="Alice", role="admin"), PersonEntry(name="Bob", role="member")])
    people = config_handlers.list_people(config)
    assert len(people) == 2
    assert people[0].name == "Alice"
    assert people[1].name == "Bob"


def test_list_person_dirs(mock_teleclaude_dir):
    (mock_teleclaude_dir / "people" / "Alice").mkdir(parents=True)
    (mock_teleclaude_dir / "people" / "Alice" / "teleclaude.yml").touch()
    (mock_teleclaude_dir / "people" / "Bob").mkdir(parents=True)
    (mock_teleclaude_dir / "people" / "Bob" / "teleclaude.yml").touch()
    # No teleclaude.yml here
    (mock_teleclaude_dir / "people" / "Charlie").mkdir(parents=True)

    dirs = config_handlers.list_person_dirs()
    assert dirs == ["Alice", "Bob"]


def test_atomic_yaml_write_cleanup(mock_teleclaude_dir):
    path = mock_teleclaude_dir / "test.yml"
    # Cause a failure by making the directory a file?
    # Actually let's just test that it works and cleanup happens.
    config_handlers._atomic_yaml_write(path, {"foo": "bar"})
    assert path.exists()
    assert not path.with_suffix(".tmp").exists()
    assert not path.with_suffix(".lock").exists()


def test_discover_config_areas(mock_teleclaude_dir):
    config = GlobalConfig(people=[PersonEntry(name="Alice", role="admin")])
    config_handlers.save_global_config(config)

    areas = config_handlers.discover_config_areas()
    names = [a.name for a in areas]
    assert "people" in names
    assert "environment" in names
    assert "notifications" in names
    # adapters should be there too
    assert any(n.startswith("adapters.") for n in names)
