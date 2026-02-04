"""Discover subscribers for cron jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml


@dataclass
class Subscriber:
    """A subscriber to a service (global or person)."""

    scope: str  # "global" or "person"
    name: str | None  # person name, None for global
    config_path: Path
    tags: list[str]

    @property
    def subscriptions_dir(self) -> Path:
        """Directory containing subscription data files."""
        return self.config_path.parent / "subscriptions"


def _load_config(path: Path) -> dict[str, Any] | None:
    """Load and parse YAML config, return None on error."""
    if not path.exists():
        return None
    try:
        result = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(result, dict):
            return cast(dict[str, Any], result)
        return {}
    except (yaml.YAMLError, OSError):
        return None


def discover_youtube_subscribers(root: Path | None = None) -> list[Subscriber]:
    """
    Find all scopes (global + people) with youtube subscription configured.

    Checks:
    - ~/.teleclaude/teleclaude.yml for global/business subscriptions
    - ~/.teleclaude/people/*/teleclaude.yml for person subscriptions

    Returns list of Subscribers that have subscriptions.youtube configured.
    """
    if root is None:
        root = Path.home() / ".teleclaude"

    subscribers: list[Subscriber] = []

    # Check global/business config
    global_cfg_path = root / "teleclaude.yml"
    global_cfg = _load_config(global_cfg_path)
    if global_cfg:
        youtube_file = global_cfg.get("subscriptions", {}).get("youtube")
        if youtube_file:
            tags = global_cfg.get("interests", {}).get("tags", [])
            subscribers.append(
                Subscriber(
                    scope="global",
                    name=None,
                    config_path=global_cfg_path,
                    tags=[str(t) for t in tags],
                )
            )

    # Check each person
    people_dir = root / "people"
    if people_dir.is_dir():
        for person_dir in sorted(people_dir.iterdir()):
            if not person_dir.is_dir():
                continue
            person_cfg_path = person_dir / "teleclaude.yml"
            person_cfg = _load_config(person_cfg_path)
            if not person_cfg:
                continue
            youtube_file = person_cfg.get("subscriptions", {}).get("youtube")
            if youtube_file:
                tags = person_cfg.get("interests", {}).get("tags", [])
                subscribers.append(
                    Subscriber(
                        scope="person",
                        name=person_dir.name,
                        config_path=person_cfg_path,
                        tags=[str(t) for t in tags],
                    )
                )

    return subscribers
