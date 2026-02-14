"""Discover notification subscribers from per-person config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import PersonConfig


@dataclass(frozen=True)
class NotificationRecipient:
    """Resolved notification recipient."""

    email: str
    telegram_chat_id: str


@dataclass(frozen=True)
class NotificationSubscriptionIndex:
    """Channel -> recipients mapping."""

    by_channel: dict[str, list[NotificationRecipient]]

    def for_channel(self, channel: str) -> list[NotificationRecipient]:
        """Return recipients subscribed to a given channel."""
        return list(self.by_channel.get(channel, []))

    def get_chat_id(self, email: str) -> str | None:
        """Resolve chat ID for the given email."""
        for recipients in self.by_channel.values():
            for recipient in recipients:
                if recipient.email == email:
                    return recipient.telegram_chat_id
        return None


def _normalize_key(value: str) -> str:
    """Normalize person directory keys to improve tolerant matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _load_person_emails(root: Path) -> dict[str, str]:
    """Build map of person directory keys -> email from global config."""
    people_cfg_path = root / "teleclaude.yml"
    if not people_cfg_path.exists():
        return {}

    global_cfg = load_global_config(people_cfg_path)
    result: dict[str, str] = {}
    for person in global_cfg.people:
        # Match against common selectors in people/<id> directories.
        result[_normalize_key(person.name)] = person.email
        if person.username:
            result[_normalize_key(person.username)] = person.email
    return result


def _iter_person_configs(root: Path) -> list[tuple[str, PersonConfig]]:
    """Yield person name and PersonConfig for all readable person configs."""
    people_dir = root / "people"
    if not people_dir.is_dir():
        return []

    results: list[tuple[str, PersonConfig]] = []
    for person_dir in sorted(people_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        person_cfg_path = person_dir / "teleclaude.yml"
        if not person_cfg_path.exists():
            continue
        person_cfg = load_person_config(person_cfg_path)
        results.append((person_dir.name, person_cfg))

    return results


def build_notification_subscriptions(root: Path | None = None) -> NotificationSubscriptionIndex:
    """Build notification subscriptions grouped by channel.

    Inputs:
        root: Base directory for person configs (defaults to ~/.teleclaude)

    Returns:
        NotificationSubscriptionIndex with per-channel recipients.
    """
    if root is None:
        root = Path.home() / ".teleclaude"

    email_by_key = _load_person_emails(root)
    by_channel: dict[str, list[NotificationRecipient]] = {}

    for person_name, person_cfg in _iter_person_configs(root):
        channels = [channel.strip() for channel in person_cfg.notifications.channels if channel.strip()]
        chat_id = person_cfg.notifications.telegram_chat_id

        if not channels or not chat_id:
            continue

        key = _normalize_key(person_name)
        email = email_by_key.get(key, f"{person_name}@local")

        recipient = NotificationRecipient(email=email, telegram_chat_id=chat_id)
        for channel in channels:
            by_channel.setdefault(channel, []).append(recipient)

    # Deduplicate recipients by email while preserving order per channel.
    deduped: dict[str, list[NotificationRecipient]] = {}
    for channel, recipients in by_channel.items():
        seen: set[str] = set()
        unique: list[NotificationRecipient] = []
        for recipient in recipients:
            if recipient.email in seen:
                continue
            seen.add(recipient.email)
            unique.append(recipient)
        deduped[channel] = unique

    return NotificationSubscriptionIndex(by_channel=deduped)


def discover_notification_recipients_for_channel(
    channel: str,
    *,
    root: Path | None = None,
) -> list[NotificationRecipient]:
    """Return all subscribers for one channel."""
    return build_notification_subscriptions(root).for_channel(channel)
