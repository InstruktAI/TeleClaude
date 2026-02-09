"""Discover subscribers for cron jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.config.loader import load_global_config, load_person_config


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
    if global_cfg_path.exists():
        global_cfg = load_global_config(global_cfg_path)
        if global_cfg.subscriptions.youtube:
            subscribers.append(
                Subscriber(
                    scope="global",
                    name=None,
                    config_path=global_cfg_path,
                    tags=global_cfg.interests,
                )
            )

    # Check each person
    people_dir = root / "people"
    if people_dir.is_dir():
        for person_dir in sorted(people_dir.iterdir()):
            if not person_dir.is_dir():
                continue
            person_cfg_path = person_dir / "teleclaude.yml"
            if person_cfg_path.exists():
                person_cfg = load_person_config(person_cfg_path)
                if person_cfg.subscriptions.youtube:
                    subscribers.append(
                        Subscriber(
                            scope="person",
                            name=person_dir.name,
                            config_path=person_cfg_path,
                            tags=person_cfg.interests,
                        )
                    )

    return subscribers
