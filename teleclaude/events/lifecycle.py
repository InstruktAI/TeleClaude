"""Cartridge lifecycle — install, remove, promote."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.events.cartridge_loader import load_cartridge
from teleclaude.events.cartridge_manifest import CartridgeError

logger = get_logger(__name__)


class PromotionSpec(NamedTuple):
    """Parameters describing a lifecycle promotion target."""

    from_scope: CartridgeScope
    to_scope: CartridgeScope
    target_domain: str
    source_member_id: str | None = None


class CartridgeScope(str, Enum):
    """Filesystem scope for installed cartridges."""

    PERSONAL = "personal"
    DOMAIN = "domain"
    PLATFORM = "platform"
    SANDBOX = "sandbox"


class LifecycleManager:
    """Install, remove, promote, and inspect cartridges across lifecycle scopes."""

    def __init__(
        self,
        personal_base_path: Path,
        domain_base_path: Path,
        reload_callback: Callable[[], None] | None = None,
    ) -> None:
        self._personal_base = personal_base_path
        self._domain_base = domain_base_path
        self._reload_callback = reload_callback

    def _require_admin(self, caller_is_admin: bool, action: str) -> None:
        """Require an administrative caller for a privileged lifecycle action."""
        if not caller_is_admin:
            raise PermissionError(f"This operation requires admin role. Action: {action}")

    def _resolve_target_path(self, scope: CartridgeScope, target: str) -> Path:
        """Map a lifecycle scope and target identifier to its cartridge directory."""
        if scope == CartridgeScope.SANDBOX:
            raise ValueError("CartridgeScope.sandbox is not a lifecycle scope and cannot be used with install/remove")
        if scope == CartridgeScope.PERSONAL:
            return self._personal_base / "members" / target / "cartridges"
        if scope == CartridgeScope.DOMAIN:
            return self._domain_base / "domains" / target / "cartridges"
        return self._domain_base / "platform" / "cartridges"

    def install(
        self,
        source_path: Path,
        scope: CartridgeScope,
        target: str,
        caller_is_admin: bool,
    ) -> None:
        """Install a cartridge into a target lifecycle scope."""
        if scope in (CartridgeScope.DOMAIN, CartridgeScope.PLATFORM):
            self._require_admin(caller_is_admin, "install domain/platform cartridge")

        # Validate manifest before install
        load_cartridge(source_path)

        dest_dir = self._resolve_target_path(scope, target)
        cartridge_name = source_path.name
        dest = dest_dir / cartridge_name

        dest_dir.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_path, dest)
        logger.info("Installed cartridge '%s' to %s", cartridge_name, dest)
        self.reload()

    def remove(
        self,
        cartridge_id: str,
        scope: CartridgeScope,
        target: str,
        caller_is_admin: bool,
    ) -> None:
        """Remove a cartridge from a target lifecycle scope."""
        if scope in (CartridgeScope.DOMAIN, CartridgeScope.PLATFORM):
            self._require_admin(caller_is_admin, "remove domain/platform cartridge")

        search_path = self._resolve_target_path(scope, target)
        cartridge_dir = self._find_cartridge_dir(search_path, cartridge_id)
        if cartridge_dir is None:
            raise CartridgeError(f"Cartridge '{cartridge_id}' not found in {search_path}")

        shutil.rmtree(cartridge_dir)
        logger.info("Removed cartridge '%s' from %s", cartridge_id, cartridge_dir)
        self.reload()

    def promote(self, cartridge_id: str, spec: PromotionSpec, *, caller_is_admin: bool) -> None:
        """Promote a cartridge from one scope to another."""
        self._require_admin(caller_is_admin, "promote cartridge")

        # When promoting from personal scope, the source path must use the member id,
        # not the target domain name.
        if spec.from_scope == CartridgeScope.PERSONAL:
            if not spec.source_member_id:
                raise ValueError("source_member_id is required when promoting from personal scope")
            src_path = self._resolve_target_path(spec.from_scope, spec.source_member_id)
        else:
            src_path = self._resolve_target_path(spec.from_scope, spec.target_domain)
        cartridge_dir = self._find_cartridge_dir(src_path, cartridge_id)
        if cartridge_dir is None:
            raise CartridgeError(f"Cartridge '{cartridge_id}' not found in {src_path}")

        dest_base = self._resolve_target_path(spec.to_scope, spec.target_domain)
        dest = dest_base / cartridge_dir.name
        dest_base.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(cartridge_dir, dest)
        shutil.rmtree(cartridge_dir)

        logger.info(
            "Promoted cartridge '%s' from %s to %s",
            cartridge_id,
            spec.from_scope,
            spec.to_scope,
        )
        self.reload()

    def _find_cartridge_dir(self, base: Path, cartridge_id: str) -> Path | None:
        """Find the installed cartridge directory with the given manifest id."""
        if not base.exists():
            return None
        for subdir in base.iterdir():
            if not subdir.is_dir():
                continue
            manifest_path = subdir / "manifest.yaml"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                if raw.get("id") == cartridge_id:
                    return subdir
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Skipping cartridge in %s: could not read manifest: %s", subdir, e)
                continue
        return None

    def reload(self) -> None:
        """Invoke the configured reload callback, if one is set."""
        if self._reload_callback is not None:
            self._reload_callback()

    def list_cartridges(self, scope: CartridgeScope, target: str) -> list[dict[str, str]]:
        """Return manifest metadata for cartridges installed at a target scope."""
        path = self._resolve_target_path(scope, target)
        results: list[dict[str, str]] = []
        if not path.exists():
            return results

        for subdir in sorted(path.iterdir()):
            if not subdir.is_dir():
                continue
            manifest_path = subdir / "manifest.yaml"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                results.append(
                    {
                        "id": raw.get("id", subdir.name),
                        "description": raw.get("description", ""),
                        "version": raw.get("version", "0.1.0"),
                        "scope": scope.value,
                        "target": target,
                    }
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Skipping cartridge in %s: could not read manifest: %s", subdir, e)
                continue
        return results
