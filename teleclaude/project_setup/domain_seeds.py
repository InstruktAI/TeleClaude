"""Idempotent seeding of default event domain configs into the global config file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from instrukt_ai_logging import get_logger

from teleclaude_events.domain_seeds import DEFAULT_EVENT_DOMAINS

logger = get_logger(__name__)

_GLOBAL_CONFIG_PATH = Path("~/.teleclaude/teleclaude.yml")


# guard: loose-dict-func - YAML global config is untyped; dict[str, Any] is the appropriate boundary type
def seed_event_domains(_project_root: Path) -> None:
    """Merge default pillar configs into the global config's event_domains section.

    Idempotent: skips if event_domains.domains already has entries (preserves user edits).
    """
    config_path = _GLOBAL_CONFIG_PATH.expanduser()
    if not config_path.exists():
        logger.debug("Global config not found at %s — skipping event domain seeding", config_path)
        return

    try:
        with open(config_path, encoding="utf-8") as f:
            raw: dict[str, Any] = (
                yaml.safe_load(f) or {}
            )  # guard: loose-dict - YAML config is unstructured at the top level
    except Exception as e:
        logger.error("Failed to read global config for domain seeding: %s", e)
        return

    existing = raw.get("event_domains") or {}
    existing_domains = existing.get("domains") or {}
    if existing_domains:
        logger.debug(
            "event_domains.domains already populated (%d entries) — skipping seed",
            len(existing_domains),
        )
        return

    if "event_domains" not in raw:
        raw["event_domains"] = {}

    # Deep merge: preserve top-level event_domains settings, fill in domains
    for key, value in DEFAULT_EVENT_DOMAINS.items():
        if key == "domains":
            raw["event_domains"].setdefault("domains", {})
            raw["event_domains"]["domains"].update(value)  # type: ignore[arg-type]
        else:
            raw["event_domains"].setdefault(key, value)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        logger.info(
            "Seeded event_domains with %d default pillar configs",
            len(DEFAULT_EVENT_DOMAINS.get("domains", {})),  # type: ignore[union-attr]
        )
    except Exception as e:
        logger.error("Failed to write seeded event_domains to global config: %s", e)
