# Demo: Cross-Project Context Selection

This demo validates three delivered behaviors:

1. Phase 0 project catalog output (`list_projects=True`).
2. Phase 1 multi-project index loading with ID rewriting (`project/...` -> `{project}/...`).
3. Visibility filtering: non-admin sees only `visibility: public` snippets.

```bash
set -euo pipefail

python - <<'PY'
from pathlib import Path
import tempfile
import yaml

from teleclaude import context_selector
from teleclaude.project_manifest import ProjectManifestEntry


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_index(index_path: Path, project_root: Path, snippets: list[dict[str, str]]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"project_root": str(project_root), "snippets": snippets}
    index_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    current_root = root / "current"
    current_root.mkdir(parents=True, exist_ok=True)

    global_root = root / "global"
    global_docs = global_root / "agents" / "docs"
    write_index(global_docs / "index.yaml", global_root, [])

    teleclaude_root = root / "teleclaude"
    write(
        teleclaude_root / "docs" / "project" / "design" / "architecture.md",
        "---\nid: project/design/architecture\ntype: design\nscope: project\ndescription: Architecture\nvisibility: public\n---\n\nArchitecture content.\n",
    )
    write(
        teleclaude_root / "docs" / "project" / "design" / "internal.md",
        "---\nid: project/design/internal\ntype: design\nscope: project\ndescription: Internal\nvisibility: internal\n---\n\nInternal content.\n",
    )
    write_index(
        teleclaude_root / "docs" / "project" / "index.yaml",
        teleclaude_root,
        [
            {
                "id": "project/design/architecture",
                "description": "Architecture",
                "type": "design",
                "scope": "project",
                "path": "docs/project/design/architecture.md",
                "visibility": "public",
            },
            {
                "id": "project/design/internal",
                "description": "Internal",
                "type": "design",
                "scope": "project",
                "path": "docs/project/design/internal.md",
                "visibility": "internal",
            },
        ],
    )

    context_selector.GLOBAL_SNIPPETS_DIR = global_docs
    context_selector.load_manifest = lambda: [
        ProjectManifestEntry(
            name="teleclaude",
            description="Core docs",
            index_path=str(teleclaude_root / "docs" / "project" / "index.yaml"),
            project_root=str(teleclaude_root),
        )
    ]

    catalog = context_selector.build_context_output(
        areas=[],
        project_root=current_root,
        list_projects=True,
    )
    assert "teleclaude: Core docs" in catalog

    admin_index = context_selector.build_context_output(
        areas=["design"],
        project_root=current_root,
        projects=["teleclaude"],
        caller_role="admin",
    )
    assert "teleclaude/design/architecture" in admin_index
    assert "teleclaude/design/internal" in admin_index

    member_index = context_selector.build_context_output(
        areas=["design"],
        project_root=current_root,
        projects=["teleclaude"],
        caller_role="member",
    )
    assert "teleclaude/design/architecture" in member_index
    assert "teleclaude/design/internal" not in member_index

print("demo-ok")
PY
```

Verification:

- The script exits 0.
- It prints `demo-ok`.
