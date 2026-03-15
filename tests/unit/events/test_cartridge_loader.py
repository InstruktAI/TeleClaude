"""Characterization tests for teleclaude.events.cartridge_loader."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from teleclaude.events.cartridge_loader import (
    LoadedCartridge,
    discover_cartridges,
    load_cartridge,
    resolve_dag,
    validate_pipeline,
)
from teleclaude.events.cartridge_manifest import (
    CartridgeCycleError,
    CartridgeDependencyError,
    CartridgeError,
    CartridgeManifest,
    CartridgeScopeError,
)


def _write_cartridge(
    parent: Path,
    manifest_data: dict[str, object],  # guard: loose-dict - cartridge manifest fixture is untyped YAML data
    module_code: str = "async def process(event, ctx): return event",
    module_name: str = "cartridge",
) -> Path:
    """Create a cartridge directory with manifest and module."""
    cdir = parent / str(manifest_data.get("id", "test"))
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "manifest.yaml").write_text(yaml.dump(manifest_data))
    (cdir / f"{module_name}.py").write_text(dedent(module_code))
    return cdir


def _simple_manifest(
    cid: str = "c1", **kwargs: object
) -> dict[str, object]:  # guard: loose-dict - manifest factory merges caller kwargs
    return {"id": cid, "description": "test cartridge", **kwargs}


class TestLoadCartridge:
    def test_loads_valid_cartridge(self, tmp_path: Path) -> None:
        cdir = _write_cartridge(tmp_path, _simple_manifest("c1"))
        loaded = load_cartridge(cdir)
        assert loaded.manifest.id == "c1"

    def test_loaded_cartridge_has_process_callable(self, tmp_path: Path) -> None:
        cdir = _write_cartridge(tmp_path, _simple_manifest("c1"))
        loaded = load_cartridge(cdir)
        assert callable(loaded.process)

    def test_loaded_cartridge_module_path_is_directory(self, tmp_path: Path) -> None:
        cdir = _write_cartridge(tmp_path, _simple_manifest("c1"))
        loaded = load_cartridge(cdir)
        assert loaded.module_path == cdir

    def test_missing_manifest_raises_cartridge_error(self, tmp_path: Path) -> None:
        empty = tmp_path / "c1"
        empty.mkdir()
        with pytest.raises(CartridgeError):
            load_cartridge(empty)

    def test_missing_module_raises_cartridge_error(self, tmp_path: Path) -> None:
        cdir = tmp_path / "c1"
        cdir.mkdir()
        (cdir / "manifest.yaml").write_text(yaml.dump(_simple_manifest("c1")))
        with pytest.raises(CartridgeError):
            load_cartridge(cdir)

    def test_module_without_process_raises_cartridge_error(self, tmp_path: Path) -> None:
        cdir = _write_cartridge(tmp_path, _simple_manifest("c1"), module_code="x = 1")
        with pytest.raises(CartridgeError):
            load_cartridge(cdir)

    def test_module_error_raises_cartridge_error(self, tmp_path: Path) -> None:
        cdir = _write_cartridge(tmp_path, _simple_manifest("c1"), module_code="raise ValueError('bad module')")
        with pytest.raises(CartridgeError):
            load_cartridge(cdir)

    def test_custom_module_name(self, tmp_path: Path) -> None:
        manifest = _simple_manifest("c1", module="my_handler")
        cdir = _write_cartridge(tmp_path, manifest, module_name="my_handler")
        loaded = load_cartridge(cdir)
        assert loaded.manifest.module == "my_handler"


class TestDiscoverCartridges:
    def test_returns_empty_for_nonexistent_path(self, tmp_path: Path) -> None:
        result = discover_cartridges(tmp_path / "missing")
        assert result == []

    def test_discovers_all_valid_cartridges(self, tmp_path: Path) -> None:
        for cid in ["a", "b", "c"]:
            _write_cartridge(tmp_path, _simple_manifest(cid))
        result = discover_cartridges(tmp_path)
        assert {c.manifest.id for c in result} == {"a", "b", "c"}

    def test_skips_directories_without_manifest(self, tmp_path: Path) -> None:
        _write_cartridge(tmp_path, _simple_manifest("valid"))
        (tmp_path / "no-manifest").mkdir()
        result = discover_cartridges(tmp_path)
        assert len(result) == 1

    def test_skips_files_not_directories(self, tmp_path: Path) -> None:
        _write_cartridge(tmp_path, _simple_manifest("valid"))
        (tmp_path / "some_file.txt").write_text("not a dir")
        result = discover_cartridges(tmp_path)
        assert len(result) == 1

    def test_returns_sorted_by_subdirectory_name(self, tmp_path: Path) -> None:
        for cid in ["z-cart", "a-cart", "m-cart"]:
            _write_cartridge(tmp_path, _simple_manifest(cid))
        result = discover_cartridges(tmp_path)
        ids = [c.manifest.id for c in result]
        assert ids == sorted(ids)


def _make_loaded(manifest: CartridgeManifest) -> LoadedCartridge:
    async def process(event: object, _ctx: object) -> object:
        return event

    return LoadedCartridge(manifest=manifest, module_path=Path("."), process=process)


class TestResolveDag:
    def test_empty_list_returns_empty_levels(self) -> None:
        assert resolve_dag([]) == []

    def test_single_cartridge_returns_one_level(self) -> None:
        c = _make_loaded(CartridgeManifest(id="c1", description="d"))
        levels = resolve_dag([c])
        assert len(levels) == 1
        assert levels[0][0].manifest.id == "c1"

    def test_independent_cartridges_in_same_level(self) -> None:
        c1 = _make_loaded(CartridgeManifest(id="c1", description="d"))
        c2 = _make_loaded(CartridgeManifest(id="c2", description="d"))
        levels = resolve_dag([c1, c2])
        assert len(levels) == 1
        assert len(levels[0]) == 2

    def test_dependency_creates_two_levels(self) -> None:
        c1 = _make_loaded(CartridgeManifest(id="c1", description="d"))
        c2 = _make_loaded(CartridgeManifest(id="c2", description="d", depends_on=["c1"]))
        levels = resolve_dag([c1, c2])
        assert len(levels) == 2
        assert levels[0][0].manifest.id == "c1"
        assert levels[1][0].manifest.id == "c2"

    def test_missing_dependency_raises(self) -> None:
        c1 = _make_loaded(CartridgeManifest(id="c1", description="d", depends_on=["missing"]))
        with pytest.raises(CartridgeDependencyError):
            resolve_dag([c1])

    def test_cycle_raises_cartridge_cycle_error(self) -> None:
        c1 = _make_loaded(CartridgeManifest(id="c1", description="d", depends_on=["c2"]))
        c2 = _make_loaded(CartridgeManifest(id="c2", description="d", depends_on=["c1"]))
        with pytest.raises(CartridgeCycleError):
            resolve_dag([c1, c2])


class TestValidatePipeline:
    def test_no_domain_affinity_passes(self) -> None:
        c = _make_loaded(CartridgeManifest(id="c1", description="d"))
        validate_pipeline([[c]], "any-domain")

    def test_domain_affinity_match_passes(self) -> None:
        c = _make_loaded(CartridgeManifest(id="c1", description="d", domain_affinity=["eng"]))
        validate_pipeline([[c]], "eng")

    def test_domain_affinity_mismatch_raises(self) -> None:
        c = _make_loaded(CartridgeManifest(id="c1", description="d", domain_affinity=["eng"]))
        with pytest.raises(CartridgeScopeError):
            validate_pipeline([[c]], "marketing")

    def test_output_slot_conflict_does_not_raise(self) -> None:
        c1 = _make_loaded(CartridgeManifest(id="c1", description="d", output_slots=["slot.a"]))
        c2 = _make_loaded(CartridgeManifest(id="c2", description="d", output_slots=["slot.a"]))
        # Conflict is warning-only, not an error
        validate_pipeline([[c1, c2]], "dom")
