"""Domain registry — maps domain names to config and cartridge paths."""

from __future__ import annotations

import re
from pathlib import Path

from teleclaude_events.domain_config import DomainConfig, DomainsConfig


def _slugify_email(email: str) -> str:
    """Convert email address to a safe filesystem slug."""
    return re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")


class DomainRegistry:
    def __init__(self) -> None:
        self._domains: dict[str, DomainConfig] = {}
        self._config: DomainsConfig = DomainsConfig()

    def load_from_config(self, config: DomainsConfig) -> None:
        self._config = config
        self._domains = dict(config.domains)
        # Ensure each domain has its name set from the dict key
        for name, domain_cfg in self._domains.items():
            if domain_cfg.name != name:
                self._domains[name] = domain_cfg.model_copy(update={"name": name})

    def get(self, name: str) -> DomainConfig | None:
        return self._domains.get(name)

    def list_enabled(self) -> list[DomainConfig]:
        return [d for d in self._domains.values() if d.enabled]

    def cartridge_path_for(self, domain_name: str) -> Path:
        domain = self._domains.get(domain_name)
        if domain and domain.cartridge_path:
            return Path(domain.cartridge_path).expanduser()
        base = Path(self._config.base_path).expanduser()
        return base / "domains" / domain_name / "cartridges"

    def personal_path_for(self, member_id: str) -> Path:
        """Resolve member filesystem path from email (slugified)."""
        slug = _slugify_email(member_id)
        base = Path(self._config.personal_base_path).expanduser()
        return base / "members" / slug / "cartridges"
