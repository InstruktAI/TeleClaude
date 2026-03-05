"""Tests for cartridge lifecycle: install, remove, promote with permission checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude_events.cartridge_manifest import CartridgeError
from teleclaude_events.lifecycle import CartridgeScope, LifecycleManager


def _make_cartridge_dir(base: Path, cartridge_id: str) -> Path:
    """Create a minimal valid cartridge directory."""
    d = base / cartridge_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.yaml").write_text(
        f"id: {cartridge_id}\ndescription: Test cartridge\n",
        encoding="utf-8",
    )
    (d / "cartridge.py").write_text(
        "async def process(event, context):\n    return event\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def manager(tmp_path: Path) -> LifecycleManager:
    return LifecycleManager(
        personal_base_path=tmp_path / "personal",
        domain_base_path=tmp_path / "company",
    )


@pytest.fixture
def source_cartridge(tmp_path: Path) -> Path:
    src = tmp_path / "sources"
    src.mkdir()
    return _make_cartridge_dir(src, "my-cartridge")


class TestInstall:
    def test_install_personal_no_admin_required(
        self, manager: LifecycleManager, source_cartridge: Path, tmp_path: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.personal,
            target="alice",
            caller_is_admin=False,
        )
        dest = tmp_path / "personal" / "members" / "alice" / "cartridges" / "my-cartridge"
        assert dest.exists()
        assert (dest / "manifest.yaml").exists()

    def test_install_domain_requires_admin(
        self, manager: LifecycleManager, source_cartridge: Path
    ) -> None:
        with pytest.raises(PermissionError, match="admin role"):
            manager.install(
                source_path=source_cartridge,
                scope=CartridgeScope.domain,
                target="software",
                caller_is_admin=False,
            )

    def test_install_domain_as_admin_succeeds(
        self, manager: LifecycleManager, source_cartridge: Path, tmp_path: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.domain,
            target="software",
            caller_is_admin=True,
        )
        dest = tmp_path / "company" / "domains" / "software" / "cartridges" / "my-cartridge"
        assert dest.exists()

    def test_install_invalid_cartridge_raises(
        self, manager: LifecycleManager, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad-cartridge"
        bad.mkdir()
        # No manifest or process function
        with pytest.raises(CartridgeError):
            manager.install(
                source_path=bad,
                scope=CartridgeScope.personal,
                target="alice",
                caller_is_admin=False,
            )


class TestRemove:
    def test_remove_personal_cartridge(
        self, manager: LifecycleManager, source_cartridge: Path, tmp_path: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.personal,
            target="alice",
            caller_is_admin=False,
        )
        manager.remove(
            cartridge_id="my-cartridge",
            scope=CartridgeScope.personal,
            target="alice",
            caller_is_admin=False,
        )
        dest = tmp_path / "personal" / "members" / "alice" / "cartridges" / "my-cartridge"
        assert not dest.exists()

    def test_remove_domain_requires_admin(
        self, manager: LifecycleManager, source_cartridge: Path, tmp_path: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.domain,
            target="software",
            caller_is_admin=True,
        )
        with pytest.raises(PermissionError, match="admin role"):
            manager.remove(
                cartridge_id="my-cartridge",
                scope=CartridgeScope.domain,
                target="software",
                caller_is_admin=False,
            )

    def test_remove_missing_cartridge_raises(
        self, manager: LifecycleManager
    ) -> None:
        with pytest.raises(CartridgeError, match="not found"):
            manager.remove(
                cartridge_id="nonexistent",
                scope=CartridgeScope.personal,
                target="alice",
                caller_is_admin=False,
            )


class TestPromote:
    def test_promote_requires_admin(
        self, manager: LifecycleManager, source_cartridge: Path, tmp_path: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.personal,
            target="alice",
            caller_is_admin=False,
        )
        with pytest.raises(PermissionError, match="admin role"):
            manager.promote(
                cartridge_id="my-cartridge",
                from_scope=CartridgeScope.personal,
                to_scope=CartridgeScope.domain,
                target_domain="alice",
                caller_is_admin=False,
            )

    def test_promote_personal_to_domain(
        self, manager: LifecycleManager, source_cartridge: Path, tmp_path: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.personal,
            target="alice",
            caller_is_admin=False,
        )
        manager.promote(
            cartridge_id="my-cartridge",
            from_scope=CartridgeScope.personal,
            to_scope=CartridgeScope.domain,
            target_domain="alice",
            caller_is_admin=True,
            source_member_id="alice",
        )
        src = tmp_path / "personal" / "members" / "alice" / "cartridges" / "my-cartridge"
        dst = tmp_path / "company" / "domains" / "alice" / "cartridges" / "my-cartridge"
        assert not src.exists()
        assert dst.exists()

    def test_promote_missing_raises(self, manager: LifecycleManager) -> None:
        with pytest.raises(CartridgeError, match="not found"):
            manager.promote(
                cartridge_id="ghost",
                from_scope=CartridgeScope.personal,
                to_scope=CartridgeScope.domain,
                target_domain="nobody",
                caller_is_admin=True,
                source_member_id="nobody",
            )


class TestList:
    def test_list_returns_installed_cartridges(
        self, manager: LifecycleManager, source_cartridge: Path
    ) -> None:
        manager.install(
            source_path=source_cartridge,
            scope=CartridgeScope.personal,
            target="bob",
            caller_is_admin=False,
        )
        rows = manager.list_cartridges(CartridgeScope.personal, "bob")
        assert len(rows) == 1
        assert rows[0]["id"] == "my-cartridge"

    def test_list_empty_when_none_installed(
        self, manager: LifecycleManager
    ) -> None:
        rows = manager.list_cartridges(CartridgeScope.personal, "nobody")
        assert rows == []
