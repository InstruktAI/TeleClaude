"""Functional tests for Blueprint generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.core.blueprint._paths import GRAPH_FILENAME, graph_path
from teleclaude.core.blueprint.generate import regenerate_blueprint
from teleclaude.core.blueprint.manifest import BlueprintStatus

pytestmark = pytest.mark.functional


# guard: loose-dict-func - fixture mirroring the graph.json contract under test
def _larger_graph() -> dict[str, object]:
    return {
        "directed": True,
        "nodes": [
            {"id": "kept", "source_file": "kept.py", "label": "kept()"},
            {"id": "removed", "source_file": "removed.py", "label": "removed()"},
        ],
        "links": [],
    }


# guard: loose-dict-func - fixture mirroring the graph.json contract under test
def _smaller_graph() -> dict[str, object]:
    return {
        "directed": True,
        "nodes": [{"id": "kept", "source_file": "kept.py", "label": "kept()"}],
        "links": [],
    }


def test_regenerate_blueprint_overwrites_cache_when_extraction_has_fewer_nodes(tmp_path: Path) -> None:
    """A shrinking re-extraction succeeds and promotes the smaller graph to the Blueprint cache."""
    graph_path(tmp_path).parent.mkdir(parents=True)
    graph_path(tmp_path).write_text(json.dumps(_larger_graph()), encoding="utf-8")

    def fake_graphify_update(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        root = Path(args[2])
        source_graph = root / "graphify-out" / GRAPH_FILENAME
        source_graph.parent.mkdir(parents=True)
        source_graph.write_text(json.dumps(_smaller_graph()), encoding="utf-8")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0 if len(args) == 4 else 1,
            stdout="",
            stderr="node count decreased",
        )

    with patch("teleclaude.core.blueprint.generate.subprocess.run", side_effect=fake_graphify_update):
        manifest = regenerate_blueprint(tmp_path, baseline_sha="mainbaselinesha0001")

    assert manifest.status is BlueprintStatus.OK
    assert json.loads(graph_path(tmp_path).read_text(encoding="utf-8")) == _smaller_graph()
