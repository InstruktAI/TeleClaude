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
