"""Functional tests for per-file docs composition, merged bundles, and injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.distribute as distribute
import teleclaude.docs_index as docs_index
from scripts.distribute import (
    _Publisher,
    _render_domain_awareness,
    _render_progressive_index,
    compose_docs_root,
    deploy_documentation,
    ensure_global_snippets_link,
    generate_domain_baselines,
    write_merged_index,
)
from teleclaude.docs_index import SnippetEntry, check_global_collisions
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


def _publisher(root: Path, slug: str, publishes: set[str]) -> _Publisher:
    return _Publisher(slug=slug, docs_global=root / "docs" / "global", publishes=frozenset(publishes))


def test_compose_merges_files_from_multiple_publishers_into_one_domain(tmp_path: Path) -> None:
    # Smoke check on the composition primitive; UC-ARD4 is proven through the
    # real deploy boundary in test_deploy_documentation_* below.
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    a_file = _write(alpha / "docs" / "global" / "erp" / "policy" / "from-alpha.md", "Alpha erp policy.\n")
    general_file = _write(alpha / "docs" / "global" / "general" / "principle" / "shared.md", "General principle.\n")
    b_file = _write(beta / "docs" / "global" / "erp" / "concept" / "from-beta.md", "Beta erp concept.\n")
    deploy = tmp_path / "deploy" / "docs"

    compose_docs_root(
        [_publisher(alpha, "alpha", {"erp"}), _publisher(beta, "beta", {"erp"})],
        deploy,
    )

    # The erp domain dir merges files from both publishers; each resolves to its source.
    assert (deploy / "erp" / "policy" / "from-alpha.md").resolve() == a_file.resolve()
    assert (deploy / "erp" / "concept" / "from-beta.md").resolve() == b_file.resolve()
    # general is contributed without a publishes declaration (cross-cutting).
    assert (deploy / "general" / "principle" / "shared.md").resolve() == general_file.resolve()
    # Build-time manifests are never linked.
    assert not (deploy / "index.yaml").exists()


def test_compose_only_links_declared_domains(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    _write(alpha / "docs" / "global" / "erp" / "policy" / "billing.md", "Erp.\n")
    _write(alpha / "docs" / "global" / "creative" / "concept" / "art.md", "Creative.\n")
    deploy = tmp_path / "deploy" / "docs"

    compose_docs_root([_publisher(alpha, "alpha", {"erp"})], deploy)

    assert (deploy / "erp" / "policy" / "billing.md").is_symlink()
    # creative is present on disk but not declared in publishes → not composed.
    assert not (deploy / "creative").exists()


def test_compose_rebuild_gcs_removed_snippet_link(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    kept = _write(alpha / "docs" / "global" / "erp" / "policy" / "kept.md", "Kept.\n")
    removed = _write(alpha / "docs" / "global" / "erp" / "policy" / "removed.md", "Removed.\n")
    deploy = tmp_path / "deploy" / "docs"
    publishers = [_publisher(alpha, "alpha", {"erp"})]

    compose_docs_root(publishers, deploy)
    assert (deploy / "erp" / "policy" / "removed.md").is_symlink()

    removed.unlink()
    compose_docs_root(publishers, deploy)

    assert (deploy / "erp" / "policy" / "kept.md").resolve() == kept.resolve()
    assert not (deploy / "erp" / "policy" / "removed.md").exists()


def test_ensure_global_snippets_link_points_to_mother_project_global_snippets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    source = _write(repo / "docs" / "global" / "snippets" / "example.md", "Snippet.\n").parent
    deploy = tmp_path / "deploy" / "docs"
    deploy.mkdir(parents=True)
    _write(deploy / "snippets" / "stale.md", "stale\n")
    monkeypatch.setattr(distribute, "_REPO_ROOT", repo)

    ensure_global_snippets_link(deploy)

    assert (deploy / "snippets").is_symlink()
    assert (deploy / "snippets").resolve() == source.resolve()


def _index_payload(snippets: list[dict[str, object]]) -> str:  # guard: loose-dict-func - test index fixtures
    return yaml.safe_dump({"project_root": "~/.teleclaude", "snippets": snippets}, sort_keys=False)


def _collision_entry(snippet_id: str, path: str) -> SnippetEntry:
    return {
        "id": snippet_id,
        "description": snippet_id,
        "type": "policy",
        "scope": "global",
        "domain": "erp",
        "activation_trigger": None,
        "path": path,
    }


def test_write_merged_index_unions_publishers(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write(
        alpha / "docs" / "global" / "index.yaml",
        _index_payload([{"id": "erp/policy/from-alpha", "domain": "erp", "source_project": "alpha"}]),
    )
    _write(
        beta / "docs" / "global" / "index.yaml",
        _index_payload([{"id": "erp/concept/from-beta", "domain": "erp", "source_project": "beta"}]),
    )
    deploy = tmp_path / "deploy" / "docs"
    deploy.mkdir(parents=True)

    write_merged_index([_publisher(alpha, "alpha", {"erp"}), _publisher(beta, "beta", {"erp"})], deploy)

    merged = yaml.safe_load((deploy / "index.yaml").read_text(encoding="utf-8"))
    ids = {entry["id"]: entry["source_project"] for entry in merged["snippets"]}
    assert ids == {"erp/policy/from-alpha": "alpha", "erp/concept/from-beta": "beta"}


_BUNDLE_HEADER = "# erp — Platform Baseline\n\n"
_ALPHA_BODY = "ALPHA BODY"
_BETA_BODY = "BETA BODY"
_SHARED_BODY = "SHARED BODY"


def test_generate_merged_bundle_dedups_shared_refs(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    shared = _write(
        tmp_path / "shared" / "erp" / "policy" / "shared.md", f"---\ndescription: Shared.\n---\n{_SHARED_BODY}\n"
    )
    only_a = _write(
        alpha / "docs" / "global" / "erp" / "concept" / "a.md", f"---\ndescription: A.\n---\n{_ALPHA_BODY}\n"
    )
    only_b = _write(beta / "docs" / "global" / "erp" / "concept" / "b.md", f"---\ndescription: B.\n---\n{_BETA_BODY}\n")
    _write(
        alpha / "docs" / "global" / "erp" / "baseline.md",
        f"@{only_a}\n@{shared}\n",
    )
    _write(
        beta / "docs" / "global" / "erp" / "baseline.md",
        f"@{only_b}\n@{shared}\n",
    )
    deploy = tmp_path / "deploy" / "docs"
    deploy.mkdir(parents=True)

    generate_domain_baselines(
        [_publisher(alpha, "alpha", {"erp"}), _publisher(beta, "beta", {"erp"})],
        deploy,
        tmp_path,
    )

    bundle = (deploy / "erp" / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert bundle.startswith(_BUNDLE_HEADER)
    assert _ALPHA_BODY in bundle
    assert _BETA_BODY in bundle
    # The shared snippet, referenced by both publishers, inflates exactly once.
    assert bundle.count(_SHARED_BODY) == 1


def test_check_global_collisions_blocks_duplicate_id_across_publishers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy" / "docs"
    _write(
        deploy / "index.yaml",
        _index_payload([{"id": "erp/policy/shared", "domain": "erp", "source_project": "alpha"}]),
    )
    monkeypatch.setattr(docs_index, "GLOBAL_DOCS_DIR", deploy)

    project_root = tmp_path / "beta"
    _write(project_root / "teleclaude.yml", "project_slug: beta\n")
    snippets_root = project_root / "docs" / "global"
    snippets_root.mkdir(parents=True)

    with pytest.raises(SystemExit):
        check_global_collisions(
            [_collision_entry("erp/policy/shared", "docs/global/erp/policy/shared.md")],
            project_root,
            snippets_root,
        )


def test_check_global_collisions_allows_distinct_ids_in_same_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy = tmp_path / "deploy" / "docs"
    _write(
        deploy / "index.yaml",
        _index_payload([{"id": "erp/policy/from-alpha", "domain": "erp", "source_project": "alpha"}]),
    )
    monkeypatch.setattr(docs_index, "GLOBAL_DOCS_DIR", deploy)

    project_root = tmp_path / "beta"
    _write(project_root / "teleclaude.yml", "project_slug: beta\n")
    snippets_root = project_root / "docs" / "global"
    snippets_root.mkdir(parents=True)

    # Distinct id in the same domain from a different publisher is the expected merge.
    check_global_collisions(
        [_collision_entry("erp/concept/from-beta", "docs/global/erp/concept/from-beta.md")],
        project_root,
        snippets_root,
    )


def _build_publisher(root: Path, slug: str, domain: str, snippets: dict[str, str]) -> None:
    """Write a full publisher tree: config, snippet files, baseline, and index."""
    _write(root / "teleclaude.yml", f"project_slug: {slug}\nbusiness:\n  publishes:\n    - {domain}\n")
    docs_global = root / "docs" / "global"
    refs: list[str] = []
    index_entries: list[dict[str, object]] = []  # guard: loose-dict - test index fixtures
    for snippet_id, body in snippets.items():
        rel = snippet_id.split("/", 1)[1]  # drop the domain prefix
        src = _write(docs_global / domain / f"{rel}.md", f"---\ndescription: {snippet_id}.\n---\n{body}\n")
        refs.append(f"@{src}")
        index_entries.append({"id": snippet_id, "domain": domain, "source_project": slug})
    _write(docs_global / domain / "baseline.md", "\n".join(refs) + "\n")
    _write(docs_global / "index.yaml", _index_payload(index_entries))


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD4")
def test_deploy_documentation_merges_publishers_through_the_real_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha = tmp_path / "alpha"  # the project being synced
    beta = tmp_path / "beta"  # a second registered publisher of the same domain
    repo = tmp_path / "repo"
    _build_publisher(alpha, "alpha", "erp", {"erp/policy/from-alpha": "ALPHA BODY"})
    _build_publisher(beta, "beta", "erp", {"erp/concept/from-beta": "BETA BODY"})
    snippets_source = _write(repo / "docs" / "global" / "snippets" / "legacy.md", "Legacy.\n").parent
    monkeypatch.setattr(distribute, "load_roots", lambda: [beta])
    monkeypatch.setattr(distribute, "_resolve_git_common_root", lambda root: alpha)
    monkeypatch.setattr(distribute, "_REPO_ROOT", repo)
    deploy = tmp_path / "deploy" / "docs"

    deploy_documentation(alpha, alpha / "docs" / "global", deploy_docs_root=deploy)

    # The shared erp domain merges both publishers' files, each resolving to its source.
    assert (deploy / "erp" / "policy" / "from-alpha.md").resolve() == (
        alpha / "docs" / "global" / "erp" / "policy" / "from-alpha.md"
    ).resolve()
    assert (deploy / "erp" / "concept" / "from-beta.md").resolve() == (
        beta / "docs" / "global" / "erp" / "concept" / "from-beta.md"
    ).resolve()
    merged = yaml.safe_load((deploy / "index.yaml").read_text(encoding="utf-8"))
    assert {entry["id"] for entry in merged["snippets"]} == {"erp/policy/from-alpha", "erp/concept/from-beta"}
    bundle = (deploy / "erp" / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert _ALPHA_BODY in bundle
    assert _BETA_BODY in bundle
    assert (deploy / "snippets").is_symlink()
    assert (deploy / "snippets").resolve() == snippets_source.resolve()


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD8")
def test_deploy_documentation_blocks_duplicate_id_across_publishers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _build_publisher(alpha, "alpha", "erp", {"erp/policy/shared": "ALPHA BODY"})
    _build_publisher(beta, "beta", "erp", {"erp/policy/shared": "BETA BODY"})
    monkeypatch.setattr(distribute, "load_roots", lambda: [beta])
    monkeypatch.setattr(distribute, "_resolve_git_common_root", lambda root: alpha)
    deploy = tmp_path / "deploy" / "docs"

    with pytest.raises(SystemExit):
        deploy_documentation(alpha, alpha / "docs" / "global", deploy_docs_root=deploy)

    assert not (deploy / "index.yaml").exists()


def test_render_domain_awareness_one_line_per_published_domain(tmp_path: Path, snapshot: Any) -> None:
    deploy = tmp_path / "docs"
    _write(
        deploy / "index.yaml",
        _index_payload(
            [
                {"id": "erp/policy/a", "domain": "erp"},
                {"id": "erp/concept/b", "domain": "erp"},
                {"id": "creative/concept/c", "domain": "creative"},
                {"id": "general/principle/x", "domain": "general"},
            ]
        ),
    )

    # One line per published domain (erp=2, creative=1); the cross-cutting
    # `general` domain is excluded.
    assert _render_domain_awareness(deploy) == snapshot


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
def test_session_start_injects_generated_domain_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_root = tmp_path / "docs"
    generated_bundle = "Generated creative bundle.\n"
    _write(docs_root / "creative" / "domain-baseline-bundle.md", generated_bundle)
    monkeypatch.setattr(receiver.tc_paths, "GLOBAL_DOCS_DIR", docs_root)
    monkeypatch.setattr(receiver, "_resolve_command_domain_for_session", lambda session_id: "creative")
    monkeypatch.setattr(receiver, "_resolve_identity_context", lambda session_id: (None, None))
    monkeypatch.setattr(receiver, "_get_memory_context", lambda project_name, *, identity_key=None: "")

    receiver._print_additional_context(
        "SessionStart",
        str(tmp_path),
        _AdditionalContextAdapter(),
        session_id="session-1",
    )

    assert capsys.readouterr().out == generated_bundle + "\n"


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD7")
def test_session_start_surfaces_missing_domain_bundle_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)
    monkeypatch.setattr(receiver.tc_paths, "GLOBAL_DOCS_DIR", docs_root)
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


def test_single_publisher_bundle_strips_pending_planned_blocks(tmp_path: Path, snapshot: Any) -> None:
    publisher = tmp_path / "alpha"
    domain_src = publisher / "docs" / "global" / "creative"
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
    deploy = tmp_path / "deploy" / "docs"
    deploy.mkdir(parents=True)

    generate_domain_baselines([_publisher(publisher, "alpha", {"creative"})], deploy, tmp_path)

    generated = (deploy / "creative" / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert generated == snapshot
