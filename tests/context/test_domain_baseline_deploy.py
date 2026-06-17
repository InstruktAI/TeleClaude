"""Functional tests for domain baseline deployment and injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.distribute import _render_progressive_index, deploy_domain_documentation
from teleclaude.hooks import receiver

pytestmark = pytest.mark.functional

EMPTY_INDEX_YAML = "snippets: []\n"


class _AdditionalContextAdapter:
    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        del hook_event_name
        return context


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_domain_documentation_deploys_live_domain_symlink_and_generated_baseline(tmp_path: Path) -> None:
    project_root = tmp_path
    source_docs_root = project_root / "docs" / "global"
    deploy_docs_root = tmp_path / "deploy" / "docs"
    domain_src = source_docs_root / "creative"
    _write(source_docs_root / "index.yaml", EMPTY_INDEX_YAML)
    _write(domain_src / "baseline.md", "Creative baseline body.\n")
    _write(domain_src / "policy" / "media.md", "Media policy.\n")
    _write(domain_src / "procedure" / "drafting.md", "Drafting procedure.\n")
    deploy_docs_root.mkdir(parents=True)
    (deploy_docs_root / "index.yaml").symlink_to(source_docs_root / "index.yaml")

    deploy_domain_documentation(source_docs_root, deploy_docs_root, project_root)

    index_dst = deploy_docs_root / "index.yaml"
    assert index_dst.is_file()
    assert not index_dst.is_symlink()
    assert index_dst.read_text(encoding="utf-8") == EMPTY_INDEX_YAML
    domain_dst = deploy_docs_root / "creative"
    assert domain_dst.is_symlink()
    assert domain_dst.resolve() == domain_src.resolve()
    expected_header = "# creative — Platform Baseline\n\n"
    assert (deploy_docs_root / "_baselines" / "creative.md").read_text(encoding="utf-8").startswith(expected_header)
    assert not (source_docs_root / "_baselines").exists()

    _write(domain_src / "concept" / "image-generation.md", "Image generation concept.\n")

    assert (domain_dst / "concept" / "image-generation.md").is_file()


def test_progressive_index_maps_deployed_refs_to_current_project_index(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    deployed_docs_root = tmp_path / "deployed" / "docs"
    snippet = _write(
        external_root / "docs" / "global" / "general" / "principle" / "evolution.md",
        """---
description: Evolution principle.
---
# Evolution — Principle
""",
    )
    _write(
        project_root / "docs" / "global" / "general" / "principle" / "evolution.md",
        snippet.read_text(encoding="utf-8"),
    )
    _write(
        project_root / "docs" / "global" / "index.yaml",
        """snippets:
- id: general/principle/evolution
  description: Evolution principle.
  type: principle
  activation_trigger:
  path: docs/global/general/principle/evolution.md
""",
    )
    deployed_docs_root.mkdir(parents=True)
    (deployed_docs_root / "general").symlink_to(external_root / "docs" / "global" / "general")
    progressive = _write(
        project_root / "docs" / "global" / "baseline-progressive.md",
        f"@{deployed_docs_root / 'general' / 'principle' / 'evolution.md'}\n",
    )

    assert _render_progressive_index(progressive, project_root=project_root).strip()


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD6")
def test_session_start_injects_generated_domain_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_root = tmp_path / "docs"
    generated_baseline = "Generated creative baseline.\n"
    _write(docs_root / "_baselines" / "creative.md", generated_baseline)
    _write(docs_root / "creative" / "baseline.md", "Source manifest.\n")
    monkeypatch.setattr(receiver.tc_paths, "GLOBAL_SNIPPETS_DIR", docs_root)
    monkeypatch.setattr(receiver, "_resolve_command_domain_for_session", lambda session_id: "creative")
    monkeypatch.setattr(receiver, "_resolve_identity_context", lambda session_id: (None, None))
    monkeypatch.setattr(receiver, "_get_memory_context", lambda project_name, *, identity_key=None: "")

    receiver._print_additional_context(
        "SessionStart",
        str(tmp_path),
        _AdditionalContextAdapter(),
        session_id="session-1",
    )

    assert capsys.readouterr().out == generated_baseline + "\n"


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD7")
def test_session_start_surfaces_missing_domain_baseline_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)
    monkeypatch.setattr(receiver.tc_paths, "GLOBAL_SNIPPETS_DIR", docs_root)
    monkeypatch.setattr(receiver, "_resolve_command_domain_for_session", lambda session_id: "creative")
    monkeypatch.setattr(receiver, "_resolve_identity_context", lambda session_id: (None, None))
    monkeypatch.setattr(receiver, "_get_memory_context", lambda project_name, *, identity_key=None: "")

    receiver._print_additional_context(
        "SessionStart",
        str(tmp_path),
        _AdditionalContextAdapter(),
        session_id="session-1",
    )

    assert capsys.readouterr().out.strip()
