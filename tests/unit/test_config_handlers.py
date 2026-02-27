import os

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
    config = GlobalConfig(people=[PersonEntry(name="Alice", email="alice@test.com", role="admin")])
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
    config = GlobalConfig(
        people=[
            PersonEntry(name="Alice", email="alice@test.com", role="admin"),
            PersonEntry(name="Bob", email="bob@test.com", role="member"),
        ]
    )
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
    config = GlobalConfig(people=[PersonEntry(name="Alice", email="alice@test.com", role="admin")])
    config_handlers.save_global_config(config)

    areas = config_handlers.discover_config_areas()
    names = [a.name for a in areas]
    assert "people" in names
    assert "environment" in names
    assert "notifications" in names
    # adapters should be there too
    assert any(n.startswith("adapters.") for n in names)


def test_whatsapp_adapter_env_var_registry():
    env_vars = config_handlers.get_adapter_env_vars("whatsapp")
    assert [env.name for env in env_vars] == [
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_WEBHOOK_SECRET",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_TEMPLATE_NAME",
        "WHATSAPP_TEMPLATE_LANGUAGE",
        "WHATSAPP_BUSINESS_NUMBER",
    ]
    assert all(env.adapter == "whatsapp" for env in env_vars)


def test_set_env_var_creates_file_and_updates_process_env(tmp_path):
    env_path = tmp_path / ".env.custom"
    key = "TELECLAUDE_TEST_KEY"
    try:
        written = config_handlers.set_env_var(key, "secret-value", env_path=env_path)
        assert written == env_path
        assert env_path.read_text(encoding="utf-8") == f"{key}=secret-value\n"
        assert os.environ[key] == "secret-value"
    finally:
        os.environ.pop(key, None)


def test_set_env_var_updates_existing_assignment(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=1\nexport TELECLAUDE_EXISTING=old\n", encoding="utf-8")
    key = "TELECLAUDE_EXISTING"
    try:
        config_handlers.set_env_var(key, "new", env_path=env_path)
        assert env_path.read_text(encoding="utf-8") == "KEEP=1\nTELECLAUDE_EXISTING=new\n"
        assert os.environ[key] == "new"
    finally:
        os.environ.pop(key, None)


def test_resolve_env_file_path_honors_override(monkeypatch, tmp_path):
    override = tmp_path / "nested" / ".env.override"
    monkeypatch.setenv("TELECLAUDE_ENV_PATH", str(override))
    assert config_handlers.resolve_env_file_path() == override

    key = "TELECLAUDE_OVERRIDE_KEY"
    try:
        written = config_handlers.set_env_var(key, "override-value")
        assert written == override
        assert override.read_text(encoding="utf-8") == f"{key}=override-value\n"
        assert os.environ[key] == "override-value"
    finally:
        os.environ.pop(key, None)
