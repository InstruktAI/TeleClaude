"""Functional tests for AGENTS progressive documentation blocks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.distribute import _needs_domain_baseline_domain

pytestmark = pytest.mark.functional


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_index(project_root: Path) -> None:
    index_path = project_root / "docs" / "global" / "index.yaml"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "snippets": [
                    {
                        "id": "software-development/concept/builder",
                        "description": "Builder role.",
                        "type": "concept",
                        "scope": "global",
                        "domain": "software-development",
                        "activation_trigger": None,
                        "path": "docs/global/software-development/concept/builder.md",
                    },
                    {
                        "id": "software-development/procedure/build",
                        "description": "Build procedure.",
                        "type": "procedure",
                        "scope": "global",
                        "domain": "software-development",
                        "activation_trigger": "Use when building a prepared todo",
                        "needs_domain_baseline": True,
                        "path": "docs/global/software-development/procedure/build.md",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_snippet_files(project_root: Path) -> tuple[Path, Path, Path]:
    _write(
        project_root / "teleclaude.yml",
        "project_name: fixture\nbusiness:\n  publishes:\n"
        "    - slug: software-development\n      trigger: Use when developing software\n",
    )
    concept = _write(
        project_root / "docs" / "global" / "software-development" / "concept" / "builder.md",
        """---
description: Builder role.
---
# Builder — Concept
""",
    )
    procedure = _write(
        project_root / "docs" / "global" / "software-development" / "procedure" / "build.md",
        """---
description: Build procedure.
activation_trigger: Use when building a prepared todo
needs_domain_baseline: true
---
# Build — Procedure
""",
    )
    progressive = _write(
        project_root / "docs" / "global" / "baseline-progressive.md",
        "\n".join(
            [
                "@docs/global/software-development/concept/builder.md",
                "@docs/global/software-development/procedure/build.md",
                "",
            ]
        ),
    )
    return concept, procedure, progressive


def test_command_domain_baseline_stamp_reads_metadata_from_index(tmp_path: Path, snapshot: object) -> None:
    _, procedure, _ = _write_snippet_files(tmp_path)
    _write_index(tmp_path)
    command = tmp_path / "agents" / "commands" / "next-build.md"
    command.parent.mkdir(parents=True)

    output = _needs_domain_baseline_domain(
        f"Read @{procedure.relative_to(tmp_path).as_posix()} before acting.",
        project_root=tmp_path,
        current_path=command,
    )

    assert output == snapshot
