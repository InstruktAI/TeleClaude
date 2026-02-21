#!/usr/bin/env python3
"""Migrate person configs from legacy notifications format to subscription model.

Migrations performed:
- notifications.telegram_chat_id -> creds.telegram.chat_id
- notifications.channels -> explicit JobSubscription entries
- subscriptions.youtube (old key-value) -> YoutubeSubscription entries
- notifications block removed after migration

Idempotent: skips configs already in the new format.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

YamlDict = dict[str, Any]  # guard: loose-dict - raw YAML data is inherently untyped


def _people_dir() -> Path:
    return Path.home() / ".teleclaude" / "people"


def _is_new_format(data: YamlDict) -> bool:
    """Check if config is already in the new subscription format."""
    if "notifications" in data:
        return False
    subs = data.get("subscriptions")
    if isinstance(subs, dict):
        return False
    if isinstance(subs, list):
        return all(isinstance(s, dict) and "type" in s for s in subs)
    return True


def _migrate(data: YamlDict) -> tuple[YamlDict, list[str]]:
    """Migrate a person config dict in place. Returns (data, changes)."""
    changes: list[str] = []

    raw_notifications = data.get("notifications")
    notifications: YamlDict = raw_notifications if isinstance(raw_notifications, dict) else {}

    # 1. Move telegram_chat_id -> creds.telegram.chat_id
    chat_id = notifications.get("telegram_chat_id")
    if chat_id is not None:
        creds: YamlDict = data.setdefault("creds", {})
        telegram: YamlDict = creds.setdefault("telegram", {})
        if "chat_id" not in telegram:
            telegram["chat_id"] = str(chat_id)
            changes.append(f"  moved notifications.telegram_chat_id -> creds.telegram.chat_id = {chat_id}")

    # 2. Convert notifications.channels -> JobSubscription entries
    new_subs: list[YamlDict] = []
    channels = notifications.get("channels", [])
    if isinstance(channels, list):
        for ch in channels:
            new_subs.append(
                {
                    "type": "job",
                    "job": str(ch),
                    "enabled": True,
                }
            )
            changes.append(f"  converted channel '{ch}' -> JobSubscription")

    # 3. Convert old subscriptions.youtube -> YoutubeSubscription
    old_subs = data.get("subscriptions")
    if isinstance(old_subs, dict):
        youtube_source = old_subs.get("youtube")
        if youtube_source:
            new_subs.append(
                {
                    "type": "youtube",
                    "source": str(youtube_source),
                    "tags": [],
                    "enabled": True,
                }
            )
            changes.append(f"  converted subscriptions.youtube -> YoutubeSubscription(source={youtube_source})")
        data["subscriptions"] = new_subs
        changes.append("  replaced old subscriptions dict with list[SubscriptionEntry]")
    elif isinstance(old_subs, list):
        # Already a list — append any channel-derived subs
        if new_subs:
            existing: list[YamlDict] = data.setdefault("subscriptions", [])
            existing.extend(new_subs)
    else:
        if new_subs:
            data["subscriptions"] = new_subs

    # 4. Remove notifications block
    if "notifications" in data:
        data.pop("notifications")
        changes.append("  removed notifications block")

    return data, changes


def migrate_person_configs(*, dry_run: bool = False, people_dir: Path | None = None) -> int:
    """Run migration on all person configs. Returns count of migrated configs."""
    root = people_dir or _people_dir()
    if not root.is_dir():
        print(f"People directory not found: {root}")
        return 0

    migrated = 0
    for person_dir in sorted(root.iterdir()):
        config_path = person_dir / "teleclaude.yml"
        if not config_path.is_file():
            continue

        name = person_dir.name
        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}

        if _is_new_format(data):
            print(f"  {name}: already migrated, skipping")
            continue

        data, changes = _migrate(data)
        if not changes:
            print(f"  {name}: no changes needed")
            continue

        print(f"  {name}:")
        for change in changes:
            print(change)

        if not dry_run:
            backup = config_path.with_suffix(".yml.bak")
            shutil.copy2(config_path, backup)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            print(f"    written (backup at {backup.name})")

        migrated += 1

    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate person configs to subscription model.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--people-dir", type=Path, help="Override people directory path")
    args = parser.parse_args()

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"Migrating person configs ({mode})...")

    count = migrate_person_configs(dry_run=args.dry_run, people_dir=args.people_dir)

    if count:
        print(f"\nMigrated {count} config(s).")
    else:
        print("\nNo configs needed migration.")

    sys.exit(0)


if __name__ == "__main__":
    main()
