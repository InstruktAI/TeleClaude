#!/usr/bin/env python3
"""Migrate all state.json files to state.yaml."""

import json
from pathlib import Path

import yaml


def migrate_state_files(todos_root: Path) -> dict[str, int]:
    """Migrate all state.json files to state.yaml.

    Returns:
        dict with counts: migrated, skipped, failed
    """
    migrated = 0
    skipped = 0
    failed = 0

    for state_json in sorted(todos_root.glob("*/state.json")):
        slug = state_json.parent.name
        state_yaml = state_json.with_name("state.yaml")

        # Skip if state.yaml already exists
        if state_yaml.exists():
            print(f"⏭️  {slug}: state.yaml already exists, skipping")
            skipped += 1
            continue

        try:
            # Read JSON
            data = json.loads(state_json.read_text(encoding="utf-8"))

            # Write YAML
            yaml_content = yaml.dump(data, default_flow_style=False, sort_keys=False)
            state_yaml.write_text(yaml_content, encoding="utf-8")

            # Remove JSON file
            state_json.unlink()

            print(f"✅ {slug}: migrated to state.yaml")
            migrated += 1

        except Exception as exc:
            print(f"❌ {slug}: migration failed: {exc}")
            failed += 1

    return {"migrated": migrated, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    todos_root = Path("todos")
    if not todos_root.is_dir():
        print("❌ todos/ directory not found")
        exit(1)

    print(f"🔄 Starting migration of state.json → state.yaml in {todos_root.resolve()}\n")

    counts = migrate_state_files(todos_root)

    print("\n📊 Migration complete:")
    print(f"   ✅ Migrated: {counts['migrated']}")
    print(f"   ⏭️  Skipped: {counts['skipped']}")
    print(f"   ❌ Failed: {counts['failed']}")
