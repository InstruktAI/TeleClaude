"""The codebase Blueprint — a generated AST structural map for change blast-radius.

See ``project/spec/codebase-blueprint`` for the contract. ``integration`` is the
single writer (``regenerate_blueprint``); agents consume blast-radius via
``telec code blueprint affected``.
"""

from __future__ import annotations

from teleclaude.core.blueprint._paths import (
    GRAPH_FILENAME,
    MANIFEST_FILENAME,
    blueprint_dir,
    graph_path,
    manifest_path,
)
from teleclaude.core.blueprint.affected import AffectedResult, Dependent, compute_affected, load_graph
from teleclaude.core.blueprint.generate import regenerate_blueprint
from teleclaude.core.blueprint.manifest import (
    BlueprintManifest,
    BlueprintStatus,
    Freshness,
    evaluate_freshness,
    read_manifest,
    write_manifest,
)
from teleclaude.core.blueprint.post_merge import run_post_merge_regeneration
from teleclaude.core.blueprint.refresh import dispatch_refresh

__all__ = [
    "GRAPH_FILENAME",
    "MANIFEST_FILENAME",
    "AffectedResult",
    "BlueprintManifest",
    "BlueprintStatus",
    "Dependent",
    "Freshness",
    "blueprint_dir",
    "compute_affected",
    "dispatch_refresh",
    "evaluate_freshness",
    "graph_path",
    "load_graph",
    "manifest_path",
    "read_manifest",
    "regenerate_blueprint",
    "run_post_merge_regeneration",
    "write_manifest",
]
