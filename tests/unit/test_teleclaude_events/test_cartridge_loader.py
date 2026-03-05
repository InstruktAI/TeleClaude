"""Tests for cartridge loader: DAG resolution, scope validation, cycle detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from teleclaude_events.cartridge_loader import (
    LoadedCartridge,
    discover_cartridges,
    load_cartridge,
    resolve_dag,
    validate_pipeline,
)
from teleclaude_events.cartridge_manifest import (
    CartridgeCycleError,
    CartridgeDependencyError,
    CartridgeError,
    CartridgeManifest,
    CartridgeScopeError,
)


def _make_loaded(
    id: str,
    depends_on: list[str] | None = None,
    domain_affinity: list[str] | None = None,
    output_slots: list[str] | None = None,
) -> LoadedCartridge:
    manifest = CartridgeManifest(
        id=id,
        description=f"Test cartridge {id}",
        depends_on=depends_on or [],
        domain_affinity=domain_affinity or [],
        output_slots=output_slots or [],
    )
    return LoadedCartridge(manifest=manifest, module_path=Path("/fake"), process=AsyncMock())


class TestManifestLoad:
    def test_valid_manifest_from_dict(self) -> None:
        raw = {
            "id": "enrich-git",
            "description": "Enriches events with git context",
            "version": "0.2.0",
            "domain_affinity": ["software"],
            "depends_on": ["trust-check"],
            "output_slots": ["enrichment.git"],
        }
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.id == "enrich-git"
        assert manifest.version == "0.2.0"
        assert manifest.domain_affinity == ["software"]
        assert manifest.depends_on == ["trust-check"]
        assert manifest.output_slots == ["enrichment.git"]

    def test_manifest_defaults(self) -> None:
        raw = {"id": "minimal", "description": "Minimal cartridge"}
        manifest = CartridgeManifest.model_validate(raw)
        assert manifest.version == "0.1.0"
        assert manifest.domain_affinity == []
        assert manifest.depends_on == []
        assert manifest.personal is False
        assert manifest.module == "cartridge"


class TestDAGResolution:
    def test_no_deps_single_level(self) -> None:
        c1 = _make_loaded("a")
        c2 = _make_loaded("b")
        levels = resolve_dag([c1, c2])
        assert len(levels) == 1
        assert set(c.manifest.id for c in levels[0]) == {"a", "b"}

    def test_simple_chain_two_levels(self) -> None:
        c1 = _make_loaded("a")
        c2 = _make_loaded("b", depends_on=["a"])
        levels = resolve_dag([c1, c2])
        assert len(levels) == 2
        assert levels[0][0].manifest.id == "a"
        assert levels[1][0].manifest.id == "b"

    def test_diamond_dependency(self) -> None:
        a = _make_loaded("a")
        b = _make_loaded("b", depends_on=["a"])
        c = _make_loaded("c", depends_on=["a"])
        d = _make_loaded("d", depends_on=["b", "c"])
        levels = resolve_dag([a, b, c, d])
        assert levels[0][0].manifest.id == "a"
        level1_ids = {x.manifest.id for x in levels[1]}
        assert level1_ids == {"b", "c"}
        assert levels[2][0].manifest.id == "d"

    def test_cycle_raises_error(self) -> None:
        a = _make_loaded("a", depends_on=["b"])
        b = _make_loaded("b", depends_on=["a"])
        with pytest.raises(CartridgeCycleError):
            resolve_dag([a, b])

    def test_self_cycle_raises_error(self) -> None:
        a = _make_loaded("a", depends_on=["a"])
        with pytest.raises(CartridgeCycleError):
            resolve_dag([a])

    def test_missing_dependency_raises_error(self) -> None:
        c = _make_loaded("c", depends_on=["missing"])
        with pytest.raises(CartridgeDependencyError):
            resolve_dag([c])

    def test_empty_list_returns_empty_levels(self) -> None:
        assert resolve_dag([]) == []


class TestPipelineValidation:
    def test_scope_mismatch_raises(self) -> None:
        c = _make_loaded("c", domain_affinity=["software"])
        levels = [[c]]
        with pytest.raises(CartridgeScopeError):
            validate_pipeline(levels, "helpdesk")

    def test_scope_match_passes(self) -> None:
        c = _make_loaded("c", domain_affinity=["software"])
        levels = [[c]]
        validate_pipeline(levels, "software")  # should not raise

    def test_empty_affinity_passes_any_domain(self) -> None:
        c = _make_loaded("c", domain_affinity=[])
        levels = [[c]]
        validate_pipeline(levels, "any-domain")  # should not raise

    def test_output_slot_conflict_warns(self, caplog: Any) -> None:
        c1 = _make_loaded("c1", output_slots=["enrichment.git"])
        c2 = _make_loaded("c2", output_slots=["enrichment.git"])
        levels = [[c1, c2]]
        import logging

        with caplog.at_level(logging.WARNING):
            validate_pipeline(levels, "software")
        assert "Output slot conflict" in caplog.text


class TestLoadCartridge:
    def test_load_cartridge_from_dir(self, tmp_path: Path) -> None:
        cartridge_dir = tmp_path / "my-cartridge"
        cartridge_dir.mkdir()
        (cartridge_dir / "manifest.yaml").write_text(
            "id: my-cartridge\ndescription: Test\n", encoding="utf-8"
        )
        (cartridge_dir / "cartridge.py").write_text(
            "async def process(event, context):\n    return event\n", encoding="utf-8"
        )
        loaded = load_cartridge(cartridge_dir)
        assert loaded.manifest.id == "my-cartridge"
        assert callable(loaded.process)

    def test_load_cartridge_missing_manifest_raises(self, tmp_path: Path) -> None:
        cartridge_dir = tmp_path / "empty"
        cartridge_dir.mkdir()
        with pytest.raises(CartridgeError):
            load_cartridge(cartridge_dir)

    def test_load_cartridge_missing_process_raises(self, tmp_path: Path) -> None:
        cartridge_dir = tmp_path / "no-process"
        cartridge_dir.mkdir()
        (cartridge_dir / "manifest.yaml").write_text(
            "id: no-process\ndescription: Test\n", encoding="utf-8"
        )
        (cartridge_dir / "cartridge.py").write_text(
            "# no process function\n", encoding="utf-8"
        )
        with pytest.raises(CartridgeError, match="missing 'process'"):
            load_cartridge(cartridge_dir)


class TestDiscoverCartridges:
    def test_discover_skips_dirs_without_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-cartridge").mkdir()
        cartridges = discover_cartridges(tmp_path)
        assert cartridges == []

    def test_discover_finds_valid_cartridges(self, tmp_path: Path) -> None:
        d = tmp_path / "valid"
        d.mkdir()
        (d / "manifest.yaml").write_text("id: valid\ndescription: V\n", encoding="utf-8")
        (d / "cartridge.py").write_text(
            "async def process(event, context):\n    return event\n", encoding="utf-8"
        )
        cartridges = discover_cartridges(tmp_path)
        assert len(cartridges) == 1
        assert cartridges[0].manifest.id == "valid"

    def test_discover_skips_invalid_gracefully(self, tmp_path: Path) -> None:
        good = tmp_path / "good"
        good.mkdir()
        (good / "manifest.yaml").write_text("id: good\ndescription: G\n", encoding="utf-8")
        (good / "cartridge.py").write_text(
            "async def process(event, context):\n    return event\n", encoding="utf-8"
        )
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "manifest.yaml").write_text("id: bad\ndescription: B\n", encoding="utf-8")
        # No cartridge.py
        cartridges = discover_cartridges(tmp_path)
        assert len(cartridges) == 1
        assert cartridges[0].manifest.id == "good"

    def test_discover_nonexistent_path_returns_empty(self, tmp_path: Path) -> None:
        cartridges = discover_cartridges(tmp_path / "nonexistent")
        assert cartridges == []
