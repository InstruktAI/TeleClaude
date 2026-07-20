"""Functional tests for AGENTS.master.md inflation into deployed AGENTS.md."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.distribute as distribute

pytestmark = pytest.mark.functional


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _index_payload(snippets: list[dict[str, object]]) -> str:  # guard: loose-dict-func - test index fixtures
    return yaml.safe_dump({"project_root": "~/.teleclaude", "snippets": snippets}, sort_keys=False)


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD9")
def test_project_progressive_baseline_omits_global_activatable_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    project = tmp_path / "project"
    _write(project / "teleclaude.yml", "project_slug: fixture\n")
    _write(
        project / "AGENTS.master.md",
        "# Project\n\n## Required reads\n\n- @docs/project/baseline-progressive.md\n",
    )
    _write(
        project / "docs" / "project" / "policy" / "example.md",
        "---\ndescription: Example policy.\n---\n# Example — Policy\n",
    )
    _write(project / "docs" / "project" / "baseline-progressive.md", "@docs/project/policy/example.md\n")
    _write(
        project / "docs" / "project" / "index.yaml",
        _index_payload(
            [
                {
                    "id": "project/policy/example",
                    "description": "Example policy.",
                    "type": "policy",
                    "path": "docs/project/policy/example.md",
                },
            ]
        ),
    )
    # The merged global deploy index carries a trigger-bearing procedure that
    # must not surface in project-scoped output.
    deploy = tmp_path / "deploy" / "docs"
    _write(
        deploy / "index.yaml",
        _index_payload(
            [
                {
                    "id": "erp/procedure/leaked-workflow",
                    "description": "Leaked workflow procedure.",
                    "type": "procedure",
                    "domain": "erp",
                    "activation_trigger": "Use when running the leaked workflow",
                    "path": "docs/global/erp/procedure/leaked-workflow.md",
                },
            ]
        ),
    )
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(project)])

    distribute.main()

    output = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert output == snapshot
