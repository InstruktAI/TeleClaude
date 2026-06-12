"""Blast-radius over the Blueprint — changed files to their dependents.

This is the one value-add primitive the Blueprint adds over the raw engine:
``graphify affected`` resolves only unique *symbol* seeds and has no
file→dependents notion. Here a set of changed files is mapped to every symbol
node those files define, and an unbounded reverse traversal over the dependency
edges yields the union of dependents (callers, importers, subclasses, users).
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

# The dependency relations whose reverse direction means "depends on". This is
# graphify's own `affected` relation set; the purely structural `contains`
# (file→symbol) edge is excluded — it is not a dependency.
_DEPENDENCY_RELATIONS = frozenset(
    {
        "calls",
        "references",
        "imports",
        "imports_from",
        "re_exports",
        "inherits",
        "extends",
        "implements",
        "uses",
        "mixes_in",
        "embeds",
    }
)


@dataclass(frozen=True)
class Dependent:
    """A node in the blast radius of the changed files."""

    node_id: str
    label: str
    source_file: str
    line: int | None


@dataclass(frozen=True)
class AffectedResult:
    """The blast radius plus enough context to report coverage honestly."""

    dependents: list[Dependent]
    seed_count: int
    unmatched_files: list[str]


def load_graph(path: Path) -> dict[str, object] | None:
    """Load a Blueprint graph.json, returning ``None`` if absent or malformed.

    A graph is malformed if ``nodes`` or ``links`` is missing or not a list;
    silently coercing either to ``[]`` would turn a corrupt graph into a silent
    "no dependents found" result, which is indistinguishable from a genuinely
    empty graph.
    """
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("nodes"), list) or not isinstance(raw.get("links"), list):
        return None
    return raw


def _parse_line(source_location: object) -> int | None:
    if not isinstance(source_location, str):
        return None
    digits = source_location.lstrip("L").split("-", 1)[0]
    return int(digits) if digits.isdigit() else None


def _normalize_changed(path: str, repo_root: Path) -> str:
    """Normalize a changed-file path to the repo-root-relative POSIX form graph nodes use."""
    p = Path(path)
    if p.is_absolute():
        try:
            return p.relative_to(repo_root).as_posix()
        except ValueError:
            return p.as_posix()
    return Path(path).as_posix()


def compute_affected(graph: dict[str, object], changed_files: list[str], *, repo_root: Path) -> AffectedResult:
    """Compute the union blast radius of ``changed_files`` over the graph.

    Maps each changed file to the node-ids it defines (seeds), runs an unbounded
    reverse BFS over the dependency edges, and returns the reached nodes that lie
    outside the changed set — the dependents the change can affect.
    """
    nodes = graph.get("nodes")
    links = graph.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise ValueError("Blueprint graph must contain list-valued 'nodes' and 'links'")

    nodes_by_id: dict[str, dict[str, object]] = {}
    files_with_nodes: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        source_file = node.get("source_file")
        if isinstance(node_id, str) and isinstance(source_file, str):
            nodes_by_id[node_id] = node
            files_with_nodes[source_file].append(node_id)

    reverse_adj: dict[str, list[str]] = defaultdict(list)
    for link in links:
        if not isinstance(link, dict):
            continue
        if link.get("relation") not in _DEPENDENCY_RELATIONS:
            continue
        source = link.get("source")
        target = link.get("target")
        if isinstance(source, str) and isinstance(target, str):
            reverse_adj[target].append(source)

    normalized_changed = {_normalize_changed(f, repo_root) for f in changed_files}
    unmatched = sorted(f for f in normalized_changed if f not in files_with_nodes)

    seed_ids: set[str] = set()
    for changed in normalized_changed:
        seed_ids.update(files_with_nodes.get(changed, []))

    visited: set[str] = set(seed_ids)
    queue: deque[str] = deque(seed_ids)
    while queue:
        current = queue.popleft()
        for dependent_id in reverse_adj.get(current, []):
            if dependent_id not in visited:
                visited.add(dependent_id)
                queue.append(dependent_id)

    dependents: list[Dependent] = []
    for node_id in visited:
        if node_id in seed_ids:
            continue
        node = nodes_by_id[node_id]
        source_file = str(node.get("source_file", ""))
        if source_file in normalized_changed:
            continue
        dependents.append(
            Dependent(
                node_id=node_id,
                label=str(node.get("label", node_id)),
                source_file=source_file,
                line=_parse_line(node.get("source_location")),
            )
        )

    dependents.sort(key=lambda d: (d.source_file, d.line if d.line is not None else 0, d.label))
    return AffectedResult(dependents=dependents, seed_count=len(seed_ids), unmatched_files=unmatched)
