"""Blueprint generation — re-extract the codebase graph and refresh the cache.

Generation is automation-only: the integrator is the single writer of the
context-owned Blueprint cache. This runs the pinned no-LLM ``graphify update`` and
relocates the resulting ``graph.json`` to ``.teleclaude/blueprint/``. It is
best-effort by contract — a failure records a non-``ok`` manifest and never raises,
so a delivery is never blocked by the Blueprint.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.blueprint._paths import GRAPH_FILENAME, blueprint_dir, graph_path, manifest_path
from teleclaude.core.blueprint.affected import load_graph
from teleclaude.core.blueprint.manifest import BlueprintManifest, BlueprintStatus, write_manifest

logger = get_logger(__name__)

_GRAPHIFY_OUT_DIRNAME = "graphify-out"


def _graph_node_count(path: Path) -> int | None:
    graph = load_graph(path)
    if graph is None:
        return None
    nodes = graph.get("nodes")
    return len(nodes) if isinstance(nodes, list) else None


def _previous_graph_node_count(repo_root: Path, source_graph: Path) -> int | None:
    source_count = _graph_node_count(source_graph)
    if source_count is not None:
        return source_count
    return _graph_node_count(graph_path(repo_root))


def _run_graphify_update(repo_root: Path) -> int:
    """Run ``graphify update`` over the repo, returning its exit code.

    graphify is an off-the-shelf AST engine adopted behind the graph.json seam
    (project/adr/0016); it has no Python binding, so a subprocess call is the
    sanctioned escape hatch from the no-shell-out policy. graphify honors
    ``.gitignore``, so worktrees, ``.venv`` and ``node_modules`` are skipped.
    """
    source_graph = repo_root / _GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
    previous_node_count = _previous_graph_node_count(repo_root, source_graph)
    proc = subprocess.run(
        # The integrator always performs a complete deterministic re-extraction;
        # force bypasses graphify's node-count guard so code-deleting refactors
        # can replace the cache instead of pinning the Blueprint in error.
        ["graphify", "update", str(repo_root), "--force"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=False,
    )
    if proc.returncode != 0:
        logger.warning("graphify update failed rc=%s stderr=%s", proc.returncode, proc.stderr.strip())
    current_node_count = _graph_node_count(source_graph)
    if previous_node_count is not None and current_node_count is not None and current_node_count < previous_node_count:
        logger.info(
            "graphify update produced fewer nodes previous=%s current=%s",
            previous_node_count,
            current_node_count,
        )
    return proc.returncode


def regenerate_blueprint(repo_root: str | Path, *, baseline_sha: str) -> BlueprintManifest:
    """Regenerate the Blueprint from ``repo_root`` and write graph + manifest.

    Best-effort: never raises. On success the graph is copied to
    ``.teleclaude/blueprint/graph.json`` and the manifest records ``ok`` with
    ``baseline_sha``; on any failure the manifest records ``error`` and the prior
    graph (if any) is left untouched.
    """
    root = Path(repo_root)
    generated_at = datetime.now(UTC).isoformat()
    status = BlueprintStatus.ERROR
    try:
        rc = _run_graphify_update(root)
        source_graph = root / _GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
        if rc == 0 and source_graph.is_file():
            blueprint_dir(root).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_graph, graph_path(root))
            status = BlueprintStatus.OK
    except OSError as exc:
        logger.warning("Blueprint regeneration failed: %s", exc)

    manifest = BlueprintManifest(baseline_sha=baseline_sha, generated_at=generated_at, status=status)
    try:
        write_manifest(manifest_path(root), manifest)
    except OSError as exc:
        logger.warning("Failed to write blueprint manifest: %s", exc)
        return BlueprintManifest(baseline_sha=baseline_sha, generated_at=generated_at, status=BlueprintStatus.ERROR)
    return manifest
