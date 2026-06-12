"""Functional tests for the codebase Blueprint blast-radius helper and command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.cli.telec.handlers.context import _handle_blueprint_affected
from teleclaude.core.blueprint._paths import graph_path, manifest_path

pytestmark = pytest.mark.functional

_BASELINE = "mainbaselinesha0001"

# Leading indent on each dependent output line — used in _dependent_labels_via_command.
_DEPENDENT_LINE_INDENT = "  "


def _graph() -> dict[str, object]:
    """A dependency chain app.main -> top.run -> mid.use_base -> core.base, plus noise.

    Edges point dependent -> dependency, so the reverse traversal from a change in
    core.py must reach mid, top and app (a depth-3 hop that proves the traversal is
    unbounded, beyond graphify's default depth-2 cap).
    """
    return {
        "directed": True,
        "nodes": [
            {"id": "core", "source_file": "core.py", "source_location": "L1", "label": "core.py"},
            {"id": "core_base", "source_file": "core.py", "source_location": "L2", "label": "base()"},
            {"id": "mid_use", "source_file": "mid.py", "source_location": "L5", "label": "use_base()"},
            {"id": "top_run", "source_file": "top.py", "source_location": "L9", "label": "run()"},
            {"id": "app_main", "source_file": "app.py", "source_location": "L3", "label": "main()"},
            {"id": "lonely", "source_file": "unrelated.py", "source_location": "L1", "label": "lonely()"},
            {"id": "helper_h", "source_file": "helper.py", "source_location": "L1", "label": "h()"},
            {"id": "consumer_c", "source_file": "consumer.py", "source_location": "L4", "label": "c()"},
        ],
        "links": [
            {"relation": "contains", "source": "core", "target": "core_base"},
            {"relation": "calls", "source": "mid_use", "target": "core_base"},
            {"relation": "calls", "source": "top_run", "target": "mid_use"},
            {"relation": "calls", "source": "app_main", "target": "top_run"},
            {"relation": "imports", "source": "consumer_c", "target": "helper_h"},
        ],
    }


def _dependent_labels_via_command(tmp_path: Path, changed: list[str], capsys: pytest.CaptureFixture[str]) -> set[str]:
    """Run the blueprint affected command and return the set of dependent labels.

    Uses the CLI handler at the command boundary — not the internal compute_affected
    helper — so the full handler path (freshness check, graph load, format, print) is
    exercised.
    """
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, changed, main_sha=_BASELINE)
    out = capsys.readouterr().out
    labels = set()
    for line in out.splitlines():
        if line.startswith(_DEPENDENT_LINE_INDENT):
            # Each dependent line: "  file:line  label" — split on double-space after strip.
            parts = line.strip().split(_DEPENDENT_LINE_INDENT, 1)
            if len(parts) == 2:
                labels.add(parts[1])
    return labels


def test_affected_returns_unbounded_transitive_dependents(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A change in core.py reaches every transitive dependent, including depth-3 app.main."""
    assert _dependent_labels_via_command(tmp_path, ["core.py"], capsys) == {"use_base()", "run()", "main()"}


def test_affected_traverses_only_downstream_dependents(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A change in mid.py reaches its dependents, never its dependencies (core)."""
    assert _dependent_labels_via_command(tmp_path, ["mid.py"], capsys) == {"run()", "main()"}


def test_affected_unions_dependents_across_changed_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two changed files in independent subgraphs contribute one unioned dependent set."""
    assert _dependent_labels_via_command(tmp_path, ["core.py", "helper.py"], capsys) == {
        "use_base()",
        "run()",
        "main()",
        "c()",
    }


def test_affected_excludes_nodes_inside_the_changed_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dependents that live in another changed file are part of the change, not the radius."""
    assert _dependent_labels_via_command(tmp_path, ["core.py", "mid.py"], capsys) == {"run()", "main()"}


def test_affected_reports_files_absent_from_the_graph(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A changed file with no symbols in the graph is surfaced as unmatched."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, ["ghost.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


def _write_blueprint(root: Path, *, baseline_sha: str, status: str = "ok") -> None:
    manifest_path(root).parent.mkdir(parents=True, exist_ok=True)
    graph_path(root).write_text(json.dumps(_graph()))
    manifest_path(root).write_text(
        json.dumps({"baseline_sha": baseline_sha, "generated_at": "2026-06-11T00:00:00+00:00", "status": status})
    )


def _run_command(tmp_path: Path, changed: list[str], *, main_sha: str | None) -> None:
    with (
        patch("teleclaude.cli.telec.handlers.context.resolve_invocation_cwd", return_value=tmp_path),
        patch("teleclaude.cli.telec.handlers.context._resolve_main_sha", return_value=main_sha),
    ):
        _handle_blueprint_affected(changed)


def test_command_prints_blast_radius_when_fresh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A fresh Blueprint prints the dependent set with file:line."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, ["core.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


def test_command_falls_back_when_blueprint_is_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A baseline behind current main yields the explicit manual-exploration fallback."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    _run_command(tmp_path, ["core.py"], main_sha="differentmainsha9999")
    assert capsys.readouterr().out == snapshot


def test_command_falls_back_when_blueprint_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """No manifest at all yields the fallback, never a silent skip."""
    _run_command(tmp_path, ["core.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot


def test_command_falls_back_when_blueprint_graph_is_malformed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], snapshot: object
) -> None:
    """A malformed graph yields the fallback, never an empty dependent set."""
    _write_blueprint(tmp_path, baseline_sha=_BASELINE)
    graph_path(tmp_path).write_text(json.dumps({"nodes": {}, "links": []}))
    _run_command(tmp_path, ["core.py"], main_sha=_BASELINE)
    assert capsys.readouterr().out == snapshot
