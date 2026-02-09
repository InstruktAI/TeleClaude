import pytest

from teleclaude.config.loader import load_global_config, load_person_config, load_project_config
from teleclaude.config.schema import JobWhenConfig


def test_project_config_valid(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
project_name: "Test Project"
business:
  domains:
    "dev": "docs/dev"
jobs:
  "sync":
    when:
      every: "10m"
git:
  checkout_root: "/tmp/checkout"
""",
        encoding="utf-8",
    )
    config = load_project_config(config_path)
    assert config.project_name == "Test Project"
    assert config.business.domains["dev"] == "docs/dev"
    assert config.jobs["sync"].when.every == "10m"
    assert config.git.checkout_root == "/tmp/checkout"


def test_project_config_disallowed_keys(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text("people: []", encoding="utf-8")
    with pytest.raises(ValueError, match="Keys not allowed at project level"):
        load_project_config(config_path)


def test_global_config_valid(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
people:
  - name: "Alice"
    email: "alice@example.com"
ops:
  - username: "alice_ops"
subscriptions:
  youtube: "subs.json"
interests: ["python", "ai"]
""",
        encoding="utf-8",
    )
    config = load_global_config(config_path)
    assert len(config.people) == 1
    assert config.people[0].name == "Alice"
    assert config.ops[0].username == "alice_ops"
    assert config.subscriptions.youtube == "subs.json"
    assert "python" in config.interests


def test_person_config_valid(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
creds:
  telegram:
    user_name: "alice"
    user_id: 12345
notifications:
  telegram: true
interests: ["ai", "rust"]
""",
        encoding="utf-8",
    )
    config = load_person_config(config_path)
    assert config.creds.telegram.user_name == "alice"
    assert config.notifications.telegram is True
    assert "ai" in config.interests


def test_person_config_disallowed_keys(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text("people: []", encoding="utf-8")
    with pytest.raises(ValueError, match="Keys not allowed at per-person level"):
        load_person_config(config_path)


def test_job_schedule_compatibility(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
jobs:
  "legacy":
    schedule: "daily"
    preferred_hour: 10
""",
        encoding="utf-8",
    )
    config = load_project_config(config_path)
    assert config.jobs["legacy"].schedule == "daily"
    assert config.jobs["legacy"].preferred_hour == 10


def test_job_when_validation():
    # Exactly one of every or at
    with pytest.raises(ValueError, match="Specify exactly one of 'every' or 'at'"):
        JobWhenConfig(every="10m", at="10:00")
    with pytest.raises(ValueError, match="Specify exactly one of 'every' or 'at'"):
        JobWhenConfig()

    # Weekdays requires at
    with pytest.raises(ValueError, match="'weekdays' requires 'at'"):
        JobWhenConfig(every="10m", weekdays=["mon"])


def test_unknown_keys_allowed(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text('unknown_key: "value"', encoding="utf-8")
    # Should not raise error because extra="allow"
    config = load_project_config(config_path)
    assert config.model_extra["unknown_key"] == "value"


def test_empty_config_returns_defaults(tmp_path):
    config_path = tmp_path / "empty.yml"
    config_path.write_text("", encoding="utf-8")
    config = load_project_config(config_path)
    assert config.project_name is None
    assert config.business.domains == {}
    assert config.jobs == {}


def test_job_every_invalid_duration_format(tmp_path):
    """Test that invalid duration formats are rejected."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
jobs:
  "bad":
    when:
      every: "bad"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid duration format"):
        load_project_config(config_path)


def test_job_every_zero_duration(tmp_path):
    """Test that duration < 1 minute is rejected."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
jobs:
  "zero":
    when:
      every: "0m"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duration must be at least 1 minute"):
        load_project_config(config_path)


def test_timezone_key_rejected_project(tmp_path):
    """Test that 'timezone' key is rejected at project level."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text("timezone: UTC", encoding="utf-8")
    with pytest.raises(ValueError, match="Keys not allowed at project level.*timezone"):
        load_project_config(config_path)


def test_timezone_key_rejected_global(tmp_path):
    """Test that 'timezone' key is rejected at global level."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text("timezone: UTC", encoding="utf-8")
    with pytest.raises(ValueError, match="Keys not allowed at global level.*timezone"):
        load_global_config(config_path)


def test_timezone_key_rejected_person(tmp_path):
    """Test that 'timezone' key is rejected at person level."""
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text("timezone: UTC", encoding="utf-8")
    with pytest.raises(ValueError, match="Keys not allowed at per-person level.*timezone"):
        load_person_config(config_path)


def test_nested_unknown_keys_warning(tmp_path, caplog):
    """Test that unknown keys in nested models produce warnings."""
    import logging

    caplog.set_level(logging.WARNING)

    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
business:
  domains:
    "dev": "docs/dev"
  unknown_nested: "value"
git:
  checkout_root: "/tmp"
  unknown_git: "value"
""",
        encoding="utf-8",
    )
    config = load_project_config(config_path)
    assert config.business.domains["dev"] == "docs/dev"
    assert config.git.checkout_root == "/tmp"

    # Check warnings were logged for nested unknown keys
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("unknown_nested" in msg for msg in warning_messages)
    assert any("unknown_git" in msg for msg in warning_messages)
