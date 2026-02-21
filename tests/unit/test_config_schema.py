import pytest

from teleclaude.config.loader import load_global_config, load_person_config, load_project_config
from teleclaude.config.schema import (
    JobScheduleConfig,
    JobSubscription,
    JobWhenConfig,
    Subscription,
    SubscriptionNotification,
    TelegramCreds,
    YoutubeSubscription,
)


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
  - type: youtube
    source: "subs.json"
    tags: ["python"]
interests: ["python", "ai"]
""",
        encoding="utf-8",
    )
    config = load_global_config(config_path)
    assert len(config.people) == 1
    assert config.people[0].name == "Alice"
    assert config.ops[0]["username"] == "alice_ops"
    assert len(config.subscriptions) == 1
    assert "python" in config.interests


def test_person_config_valid(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
creds:
  telegram:
    user_name: "alice"
    user_id: 12345
    chat_id: "123456"
subscriptions:
  - type: job
    job: idea-miner
    when:
      every: "1h"
interests: ["ai", "rust"]
""",
        encoding="utf-8",
    )
    config = load_person_config(config_path)
    assert config.creds.telegram.user_name == "alice"
    assert config.creds.telegram.chat_id == "123456"
    assert len(config.subscriptions) == 1
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


# --- Task 1.1: Subscription models and category field ---


def test_job_schedule_config_category_defaults_to_subscription():
    cfg = JobScheduleConfig(when=JobWhenConfig(every="10m"))
    assert cfg.category == "subscription"


def test_job_schedule_config_category_system():
    cfg = JobScheduleConfig(category="system", when=JobWhenConfig(every="1h"))
    assert cfg.category == "system"


def test_telegram_creds_chat_id_optional():
    creds = TelegramCreds(user_name="alice", user_id=123)
    assert creds.chat_id is None

    creds_with = TelegramCreds(user_name="alice", user_id=123, chat_id="999")
    assert creds_with.chat_id == "999"


def test_subscription_enabled_toggle():
    sub = Subscription(enabled=True)
    assert sub.enabled is True
    sub_off = Subscription(enabled=False)
    assert sub_off.enabled is False


def test_subscription_notification_defaults():
    n = SubscriptionNotification()
    assert n.preferred_channel == "telegram"
    assert n.email is None


def test_job_subscription_roundtrip():
    sub = JobSubscription(job="idea-miner", when=JobWhenConfig(at="09:00"))
    assert sub.type == "job"
    assert sub.job == "idea-miner"
    assert sub.when.at == "09:00"
    assert sub.enabled is True


def test_youtube_subscription_roundtrip():
    sub = YoutubeSubscription(source="subs.json", tags=["ai", "python"])
    assert sub.type == "youtube"
    assert sub.source == "subs.json"
    assert sub.tags == ["ai", "python"]


def test_person_config_with_new_subscriptions(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
creds:
  telegram:
    user_name: alice
    user_id: 12345
    chat_id: "999"
subscriptions:
  - type: job
    job: idea-miner
    when:
      every: "1h"
  - type: youtube
    source: subs.json
    tags: ["ai"]
    enabled: false
""",
        encoding="utf-8",
    )
    config = load_person_config(config_path)
    assert isinstance(config.subscriptions, list)
    assert len(config.subscriptions) == 2
    assert isinstance(config.subscriptions[0], JobSubscription)
    assert config.subscriptions[0].job == "idea-miner"
    assert config.subscriptions[0].enabled is True
    assert isinstance(config.subscriptions[1], YoutubeSubscription)
    assert config.subscriptions[1].enabled is False
    assert config.creds.telegram.chat_id == "999"


def test_person_config_empty_subscriptions(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
subscriptions: []
""",
        encoding="utf-8",
    )
    config = load_person_config(config_path)
    assert config.subscriptions == []


def test_job_category_in_project_config(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        """
jobs:
  idea-miner:
    category: subscription
    when:
      every: "1h"
  maintenance:
    category: system
    type: agent
    job: maintenance
""",
        encoding="utf-8",
    )
    config = load_project_config(config_path)
    assert config.jobs["idea-miner"].category == "subscription"
    assert config.jobs["maintenance"].category == "system"
