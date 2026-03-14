"""Cartridge loader — discovers, loads, and resolves the dependency DAG."""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.events.cartridge_manifest import (
    CartridgeCycleError,
    CartridgeDependencyError,
    CartridgeError,
    CartridgeManifest,
    CartridgeScopeError,
)

if TYPE_CHECKING:
    from teleclaude.events.envelope import EventEnvelope
    from teleclaude.events.pipeline import PipelineContext

logger = get_logger(__name__)


@dataclass
class LoadedCartridge:
    manifest: CartridgeManifest
    module_path: Path
    process: Callable[[EventEnvelope, PipelineContext], Awaitable[EventEnvelope | None]]


def load_cartridge(path: Path) -> LoadedCartridge:
    """Load a single cartridge from its directory."""
    manifest_path = path / "manifest.yaml"
    if not manifest_path.exists():
        raise CartridgeError(f"No manifest.yaml in {path}")

    with open(manifest_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    manifest = CartridgeManifest.model_validate(raw)
    module_file = path / f"{manifest.module}.py"
    if not module_file.exists():
        raise CartridgeError(f"Module {manifest.module}.py not found in {path}")

    # Load module without polluting sys.path globally
    spec = importlib.util.spec_from_file_location(
        f"_cartridge_{manifest.id}",
        module_file,
        submodule_search_locations=[],
    )
    if spec is None or spec.loader is None:
        raise CartridgeError(f"Cannot create module spec for {module_file}")

    module = importlib.util.module_from_spec(spec)
    # Register module in sys.modules under a unique key to isolate it from other cartridges
    sys.modules[f"_cartridge_{manifest.id}"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        del sys.modules[f"_cartridge_{manifest.id}"]
        raise CartridgeError(f"Failed to load module {module_file}: {e}") from e

    if not hasattr(module, "process"):
        del sys.modules[f"_cartridge_{manifest.id}"]
        raise CartridgeError(f"Module {module_file} missing 'process' callable")

    return LoadedCartridge(
        manifest=manifest,
        module_path=path,
        process=module.process,
    )


def discover_cartridges(domain_path: Path) -> list[LoadedCartridge]:
    """Scan immediate subdirs of domain_path for manifest.yaml and load each."""
    if not domain_path.exists():
        return []

    loaded: list[LoadedCartridge] = []
    for subdir in sorted(domain_path.iterdir()):
        if not subdir.is_dir():
            continue
        if not (subdir / "manifest.yaml").exists():
            continue
        try:
            cartridge = load_cartridge(subdir)
            loaded.append(cartridge)
        except CartridgeError as e:
            logger.warning("Skipping cartridge in %s: %s", subdir, e)

    return loaded


def resolve_dag(cartridges: list[LoadedCartridge]) -> list[list[LoadedCartridge]]:
    """Topological sort via Kahn's algorithm. Returns levels."""
    by_id: dict[str, LoadedCartridge] = {c.manifest.id: c for c in cartridges}

    # Validate all dependencies exist
    for c in cartridges:
        for dep in c.manifest.depends_on:
            if dep not in by_id:
                raise CartridgeDependencyError(
                    f"Cartridge '{c.manifest.id}' declares dependency '{dep}' which is not loaded"
                )

    # Build in-degree and adjacency
    in_degree: dict[str, int] = {c.manifest.id: 0 for c in cartridges}
    dependents: dict[str, list[str]] = defaultdict(list)

    for c in cartridges:
        for dep in c.manifest.depends_on:
            dependents[dep].append(c.manifest.id)
            in_degree[c.manifest.id] += 1

    # Kahn's algorithm
    queue: deque[str] = deque(cid for cid, deg in in_degree.items() if deg == 0)
    levels: list[list[LoadedCartridge]] = []
    processed: set[str] = set()

    while True:
        current_level = list(queue)
        if not current_level:
            break
        queue.clear()

        levels.append([by_id[cid] for cid in current_level])
        processed.update(current_level)

        next_queue: list[str] = []
        for cid in current_level:
            for dependent in dependents[cid]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)
        queue.extend(next_queue)

    if len(processed) != len(cartridges):
        cycle_ids = [c.manifest.id for c in cartridges if c.manifest.id not in processed]
        raise CartridgeCycleError(f"Dependency cycle detected among: {cycle_ids}")

    return levels


def validate_pipeline(levels: list[list[LoadedCartridge]], domain: str) -> None:
    """Validate scope affinity; log warnings for output slot conflicts."""
    slot_owners: dict[str, str] = {}

    for level in levels:
        for c in level:
            # Scope check
            if c.manifest.domain_affinity and domain not in c.manifest.domain_affinity:
                raise CartridgeScopeError(
                    f"Cartridge '{c.manifest.id}' declares domain_affinity "
                    f"{c.manifest.domain_affinity} but is being loaded for domain '{domain}'"
                )

            # Output slot conflict check (warning only)
            for slot in c.manifest.output_slots:
                if slot in slot_owners:
                    logger.warning(
                        "Output slot conflict in domain '%s': cartridges '%s' and '%s' both claim slot '%s'",
                        domain,
                        slot_owners[slot],
                        c.manifest.id,
                        slot,
                    )
                else:
                    slot_owners[slot] = c.manifest.id
