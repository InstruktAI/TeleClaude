"""Functional tests for domain baseline deployment and injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.distribute import (
    _render_progressive_index,
    ensure_docs_root_symlink,
    generate_domain_baselines,
)
from teleclaude.hooks import receiver

pytestmark = pytest.mark.functional


class _AdditionalContextAdapter:
    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        del hook_event_name
        return context


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_docs_root_is_single_symlink_with_generated_domain_baselines(tmp_path: Path) -> None:
    project_root = tmp_path
    source_docs_root = project_root / "docs" / "global"
    deploy_docs_root = tmp_path / "deploy" / "docs"
    domain_src = source_docs_root / "creative"
    _write(domain_src / "baseline.md", "Creative baseline body.\n")
    _write(domain_src / "policy" / "media.md", "Media policy.\n")

    ensure_docs_root_symlink(source_docs_root, deploy_docs_root)
    generate_domain_baselines(source_docs_root, project_root)

    # The deployed root is a single whole-tree symlink onto source/docs/global.
    assert deploy_docs_root.is_symlink()
    assert deploy_docs_root.resolve() == source_docs_root.resolve()

    # The inflated baseline lives beside its source manifest, never in a
    # `_baselines/` snapshot, and is visible through the symlink.
    expected_header = "# creative — Platform Baseline\n\n"
    generated = domain_src / "domain-baseline.md"
    assert generated.read_text(encoding="utf-8").startswith(expected_header)
    assert not (source_docs_root / "_baselines").exists()
    assert (deploy_docs_root / "creative" / "domain-baseline.md").is_file()

    # A source subfolder added after deploy resolves through the live symlink —
    # the snapshot brittleness that caused the original partial deploy is gone.
    _write(domain_src / "concept" / "image-generation.md", "Image generation concept.\n")
    assert (deploy_docs_root / "creative" / "concept" / "image-generation.md").is_file()


def test_ensure_docs_root_symlink_replaces_stale_real_directory(tmp_path: Path) -> None:
    source_docs_root = tmp_path / "docs" / "global"
    _write(source_docs_root / "creative" / "baseline.md", "Body.\n")
    deploy_docs_root = tmp_path / "deploy" / "docs"
    # Simulate the broken legacy state: a real directory of per-child symlinks.
    (deploy_docs_root / "_baselines").mkdir(parents=True)
    _write(deploy_docs_root / "_baselines" / "creative.md", "stale snapshot")

    ensure_docs_root_symlink(source_docs_root, deploy_docs_root)

    assert deploy_docs_root.is_symlink()
    assert deploy_docs_root.resolve() == source_docs_root.resolve()
    assert not (deploy_docs_root / "_baselines").exists()


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
    _write(docs_root / "creative" / "domain-baseline.md", generated_baseline)
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


def test_domain_baseline_strips_pending_planned_blocks(tmp_path: Path, snapshot: Any) -> None:
    source_docs_root = tmp_path / "docs" / "global"
    domain_src = source_docs_root / "creative"
    _write(
        domain_src / "baseline.md",
        "Domain manifest intro prose.\n\n@policy/leaky.md\n",
    )
    _write(
        domain_src / "policy" / "leaky.md",
        """---
description: A policy snippet carrying pending planned blocks.
---
# Leaky Policy

Ordinary current prose that must survive.

<!-- planned:future-work -->
Pending ADD content that must be dropped.
<!-- /planned:future-work -->

<!-- planned-change:future-work -->
Current REPLACE side that survives.
<!-- change:future-work -->
Replacement side that must be dropped.
<!-- /planned-change:future-work -->

Closing ordinary prose.
""",
    )

    generate_domain_baselines(source_docs_root, tmp_path)

    generated = (domain_src / "domain-baseline.md").read_text(encoding="utf-8")
    assert generated == snapshot
