"""Unit tests for discover_job_recipients."""

from pathlib import Path

from teleclaude.cron.job_recipients import discover_job_recipients


def _setup_people(tmp_path: Path) -> Path:
    """Create a test ~/.teleclaude directory with people and subscriptions."""
    root = tmp_path / ".teleclaude"
    (root / "people" / "alice").mkdir(parents=True)
    (root / "people" / "bob").mkdir(parents=True)
    (root / "people" / "carol").mkdir(parents=True)

    (root / "teleclaude.yml").write_text(
        """
people:
  - name: alice
    email: alice@example.com
    role: admin
  - name: bob
    email: bob@example.com
    role: member
  - name: carol
    email: carol@example.com
    role: member
""",
        encoding="utf-8",
    )

    (root / "people" / "alice" / "teleclaude.yml").write_text(
        """
creds:
  telegram:
    user_name: alice
    user_id: 111
    chat_id: "111"
subscriptions:
  - type: job
    job: idea-miner
    when:
      every: "1h"
""",
        encoding="utf-8",
    )

    (root / "people" / "bob" / "teleclaude.yml").write_text(
        """
creds:
  telegram:
    user_name: bob
    user_id: 222
    chat_id: "222"
subscriptions:
  - type: job
    job: idea-miner
    when:
      every: "2h"
  - type: job
    job: maintenance
    enabled: false
""",
        encoding="utf-8",
    )

    (root / "people" / "carol" / "teleclaude.yml").write_text(
        """
creds:
  telegram:
    user_name: carol
    user_id: 333
    chat_id: "333"
subscriptions:
  - type: youtube
    source: subs.json
    tags: ["ai"]
""",
        encoding="utf-8",
    )

    return root


def test_subscription_job_finds_subscribers(tmp_path: Path) -> None:
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("idea-miner", "subscription", root=root)
    emails = [r[0].telegram.chat_id for r in recipients if r[0].telegram]
    assert sorted(emails) == ["111", "222"]


def test_subscription_job_no_subscribers_returns_empty(tmp_path: Path) -> None:
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("unknown-job", "subscription", root=root)
    assert recipients == []


def test_disabled_subscription_ignored(tmp_path: Path) -> None:
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("maintenance", "subscription", root=root)
    assert recipients == []


def test_system_job_includes_admins(tmp_path: Path) -> None:
    root = _setup_people(tmp_path)
    recipients = discover_job_recipients("maintenance", "system", root=root)
    # Alice is admin, should be included even without a matching subscription
    chat_ids = [r[0].telegram.chat_id for r in recipients if r[0].telegram]
    assert "111" in chat_ids


def test_system_job_admin_plus_subscriber_dedup(tmp_path: Path) -> None:
    root = _setup_people(tmp_path)
    # Alice has both admin role and idea-miner subscription, should appear once
    recipients = discover_job_recipients("idea-miner", "system", root=root)
    chat_ids = [r[0].telegram.chat_id for r in recipients if r[0].telegram]
    assert chat_ids.count("111") == 1
    # Bob has subscription, should also appear
    assert "222" in chat_ids
