"""Functional tests for per-domain single-owner docs composition, bundles, and injection."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.distribute as distribute
from scripts.distribute import (
    _Publisher,
    _render_domain_awareness,
    _render_progressive_index,
    compose_docs_root,
    deploy_documentation,
    domain_owners,
    generate_domain_baselines,
    write_merged_index,
)
from teleclaude.git import Repo
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


def test_compose_links_one_symlink_per_owned_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Smoke check on the composition primitive; UC-ARD4 is proven through the
    # real deploy boundary in test_deploy_documentation_* below.
    mother = tmp_path / "mother"
    alpha = tmp_path / "alpha"
    erp_dir = _write(alpha / "docs" / "global" / "erp" / "policy" / "billing.md", "Erp.\n").parent.parent
    general_dir = _write(
        mother / "docs" / "global" / "general" / "principle" / "shared.md", "General principle.\n"
    ).parent.parent
    monkeypatch.setattr(distribute, "_REPO_ROOT", mother)
    deploy = tmp_path / "deploy" / "docs"

    owners = domain_owners([_publisher(mother, "mother", set()), _publisher(alpha, "alpha", {"erp"})])
    compose_docs_root(owners, deploy)

    # Each owned domain is a single directory symlink to its owner's source folder.
    assert (deploy / "erp").is_symlink()
    assert (deploy / "erp").resolve() == erp_dir.resolve()
    # The cross-cutting general domain symlinks from the Mother repo.
    assert (deploy / "general").is_symlink()
    assert (deploy / "general").resolve() == general_dir.resolve()
    # Build-time manifests are never linked.
    assert not (deploy / "index.yaml").exists()


def test_compose_only_links_declared_domains(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    _write(alpha / "docs" / "global" / "erp" / "policy" / "billing.md", "Erp.\n")
    _write(alpha / "docs" / "global" / "creative" / "concept" / "art.md", "Creative.\n")
    deploy = tmp_path / "deploy" / "docs"

    owners = domain_owners([_publisher(alpha, "alpha", {"erp"})])
    compose_docs_root(owners, deploy)

    assert (deploy / "erp").is_symlink()
    # creative is present on disk but not declared in publishes → not composed.
    assert not (deploy / "creative").exists()


def test_compose_rebuild_drops_removed_source_snippet(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    kept = _write(alpha / "docs" / "global" / "erp" / "policy" / "kept.md", "Kept.\n")
    removed = _write(alpha / "docs" / "global" / "erp" / "policy" / "removed.md", "Removed.\n")
    deploy = tmp_path / "deploy" / "docs"
    owners = domain_owners([_publisher(alpha, "alpha", {"erp"})])

    compose_docs_root(owners, deploy)
    # The domain symlink is a live view of the owner's source dir.
    assert (deploy / "erp" / "policy" / "removed.md").resolve() == removed.resolve()

    removed.unlink()
    compose_docs_root(owners, deploy)

    # A removed source snippet vanishes through the directory symlink — no orphan relink.
    assert (deploy / "erp" / "policy" / "kept.md").resolve() == kept.resolve()
    assert not (deploy / "erp" / "policy" / "removed.md").exists()


def _index_payload(snippets: list[dict[str, object]]) -> str:  # guard: loose-dict-func - test index fixtures
    return yaml.safe_dump({"project_root": "~/.teleclaude", "snippets": snippets}, sort_keys=False)


def test_write_merged_index_unions_publishers(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write(
        alpha / "docs" / "global" / "index.yaml",
        _index_payload([{"id": "erp/policy/from-alpha", "domain": "erp", "source_project": "alpha"}]),
    )
    _write(
        beta / "docs" / "global" / "index.yaml",
        _index_payload([{"id": "creative/concept/from-beta", "domain": "creative", "source_project": "beta"}]),
    )
    deploy = tmp_path / "deploy" / "docs"
    deploy.mkdir(parents=True)

    write_merged_index([_publisher(alpha, "alpha", {"erp"}), _publisher(beta, "beta", {"creative"})], deploy)

    merged = yaml.safe_load((deploy / "index.yaml").read_text(encoding="utf-8"))
    ids = {entry["id"]: entry["source_project"] for entry in merged["snippets"]}
    assert ids == {"erp/policy/from-alpha": "alpha", "creative/concept/from-beta": "beta"}


_BUNDLE_HEADER = "# erp — Platform Baseline\n\n"
_ALPHA_BODY = "ALPHA BODY"
_BETA_BODY = "BETA BODY"
_SHARED_BODY = "SHARED BODY"


def test_generate_single_owner_bundle_into_owner_source_dir(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    only_a = _write(
        alpha / "docs" / "global" / "erp" / "concept" / "a.md", f"---\ndescription: A.\n---\n{_ALPHA_BODY}\n"
    )
    shared = _write(
        alpha / "docs" / "global" / "erp" / "policy" / "shared.md",
        f"---\ndescription: Shared.\n---\n{_SHARED_BODY}\n",
    )
    _write(
        alpha / "docs" / "global" / "erp" / "baseline.md",
        f"@{only_a}\n@{shared}\n",
    )
    deploy = tmp_path / "deploy" / "docs"

    owners = domain_owners([_publisher(alpha, "alpha", {"erp"})])
    compose_docs_root(owners, deploy)
    generate_domain_baselines(owners, deploy, tmp_path)

    # The single-source bundle is written into the owner's source dir...
    bundle_src = alpha / "docs" / "global" / "erp" / "domain-baseline-bundle.md"
    assert bundle_src.exists()
    # ...and resolves through the per-domain symlink at the deployed path.
    bundle = (deploy / "erp" / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert bundle.startswith(_BUNDLE_HEADER)
    assert _ALPHA_BODY in bundle
    assert _SHARED_BODY in bundle


def test_domain_owners_blocks_split_domain_ownership(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"

    with pytest.raises(SystemExit, match="split domain ownership: erp claimed by alpha and beta"):
        domain_owners([_publisher(alpha, "alpha", {"erp"}), _publisher(beta, "beta", {"erp"})])


def test_domain_owners_blocks_side_project_claiming_general(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `general` is Mother-owned; a side project declaring it in business.publishes
    # is a split, not a silent override of Mother's reservation.
    mother = tmp_path / "mother"
    side = tmp_path / "side"
    _write(mother / "docs" / "global" / "general" / "principle" / "shared.md", "General.\n")
    monkeypatch.setattr(distribute, "_REPO_ROOT", mother)

    with pytest.raises(SystemExit, match="split domain ownership: general claimed by mother and side"):
        domain_owners([_publisher(mother, "mother", set()), _publisher(side, "side", {"general"})])


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


def _build_publisher_with_progressive_procedure(root: Path, slug: str, domain: str) -> None:
    _write(root / "teleclaude.yml", f"project_slug: {slug}\nbusiness:\n  publishes:\n    - {domain}\n")
    docs_global = root / "docs" / "global"
    policy = _write(
        docs_global / domain / "policy" / "overview.md",
        """---
description: Domain overview.
---
# Domain Overview

Current domain body.
""",
    )
    procedure = _write(
        docs_global / domain / "procedure" / "workflow.md",
        """---
description: Workflow procedure.
activation_trigger: Use when running the domain workflow
---
# Workflow
""",
    )
    _write(docs_global / domain / "baseline.md", f"@{policy}\n")
    _write(docs_global / domain / "baseline-progressive.md", f"@{procedure}\n")
    _write(
        docs_global / "index.yaml",
        _index_payload(
            [
                {
                    "id": f"{domain}/policy/overview",
                    "description": "Domain overview.",
                    "type": "policy",
                    "domain": domain,
                    "source_project": slug,
                    "path": f"docs/global/{domain}/policy/overview.md",
                },
                {
                    "id": f"{domain}/procedure/workflow",
                    "description": "Workflow procedure.",
                    "type": "procedure",
                    "domain": domain,
                    "source_project": slug,
                    "activation_trigger": "Use when running the domain workflow",
                    "path": f"docs/global/{domain}/procedure/workflow.md",
                },
            ]
        ),
    )


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD4")
def test_deploy_documentation_composes_per_domain_through_the_real_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha = tmp_path / "alpha"  # the project being synced, owns erp
    beta = tmp_path / "beta"  # a second registered publisher, owns creative
    repo = tmp_path / "repo"
    _build_publisher(alpha, "alpha", "erp", {"erp/policy/from-alpha": _ALPHA_BODY})
    _build_publisher(beta, "beta", "creative", {"creative/concept/from-beta": _BETA_BODY})
    snippets_source = _write(repo / "docs" / "global" / "snippets" / "legacy.md", "Legacy.\n").parent
    monkeypatch.setattr(distribute, "load_roots", lambda: [beta])
    monkeypatch.setattr(distribute, "_resolve_git_common_root", lambda root: alpha)
    monkeypatch.setattr(distribute, "_REPO_ROOT", repo)
    deploy = tmp_path / "deploy" / "docs"

    deploy_documentation(alpha, alpha / "docs" / "global", deploy_docs_root=deploy)

    # Each owned domain is a single symlink to its owning publisher's source dir.
    assert (deploy / "erp").resolve() == (alpha / "docs" / "global" / "erp").resolve()
    assert (deploy / "creative").resolve() == (beta / "docs" / "global" / "creative").resolve()
    merged = yaml.safe_load((deploy / "index.yaml").read_text(encoding="utf-8"))
    assert {entry["id"] for entry in merged["snippets"]} == {"erp/policy/from-alpha", "creative/concept/from-beta"}
    assert _ALPHA_BODY in (deploy / "erp" / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert _BETA_BODY in (deploy / "creative" / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert (deploy / "snippets").is_symlink()
    assert (deploy / "snippets").resolve() == snippets_source.resolve()


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD3")
def test_deploy_documentation_finds_mother_across_worktree_code_and_canonical_main_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mother identification must survive the exact divergence that dropped
    `general` in production: the running distribute.py code loaded from one
    checkout (`_REPO_ROOT`) while the docs being composed resolve through the
    canonical main checkout (`resolve_invocation_project_root` always
    canonicalizes the deploy's `project_root`/`docs_global` to main, even when
    the executing code's own checkout is a linked worktree such as the
    integration worktree). A real git worktree reproduces the divergence;
    `_resolve_git_common_root` must resolve both checkouts to the same
    canonical root so Mother — and therefore `general` — is never dropped,
    regardless of which checkout's code is executing."""
    main_root = tmp_path / "main"
    _build_publisher(
        main_root, "teleclaude", "software-development", {"software-development/policy/from-main": _ALPHA_BODY}
    )
    _write(main_root / "docs" / "global" / "general" / "principle" / "shared.md", "General shared.\n")
    repo = Repo.init(main_root)
    repo.git.checkout("-B", "main")
    repo.git.config("user.name", "Distribute Test")
    repo.git.config("user.email", "distribute-test@example.test")
    repo.git.add(".")
    repo.git.commit("-m", "initial")
    integration_worktree = main_root / "trees" / "_integration"
    repo.git.worktree("add", "-b", "integration", str(integration_worktree), "HEAD")
    monkeypatch.setattr(distribute, "load_roots", lambda: [])
    docs_global = main_root / "docs" / "global"

    # Code loaded from the main checkout — the normal `telec sync` wrapper path.
    monkeypatch.setattr(distribute, "_REPO_ROOT", main_root)
    deploy_from_main = tmp_path / "deploy-main" / "docs"
    deploy_documentation(main_root, docs_global, deploy_docs_root=deploy_from_main)
    assert (deploy_from_main / "general").is_symlink()
    assert (deploy_from_main / "general").resolve() == (docs_global / "general").resolve()

    # Code loaded from the integration worktree — the divergence that dropped
    # `general` in production.
    monkeypatch.setattr(distribute, "_REPO_ROOT", integration_worktree)
    deploy_from_worktree = tmp_path / "deploy-worktree" / "docs"
    deploy_documentation(main_root, docs_global, deploy_docs_root=deploy_from_worktree)
    assert (deploy_from_worktree / "general").is_symlink()
    assert (deploy_from_worktree / "general").resolve() == (docs_global / "general").resolve()


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD9")
def test_domain_bundle_carries_activatable_procedures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    publisher = tmp_path / "publisher"
    deploy = tmp_path / "deploy" / "docs"
    _build_publisher_with_progressive_procedure(publisher, "publisher", "erp")
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)

    owners = domain_owners([_publisher(publisher, "publisher", {"erp"})])
    compose_docs_root(owners, deploy)
    write_merged_index([_publisher(publisher, "publisher", {"erp"})], deploy)
    generate_domain_baselines(owners, deploy, publisher)

    bundle = (deploy / "erp" / "domain-baseline-bundle.md").read_text(encoding="utf-8")

    assert bundle == snapshot


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD9")
def test_global_agent_config_carries_activatable_procedures_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    mother = tmp_path / "mother"
    publisher = tmp_path / "publisher"
    home = tmp_path / "home"
    deploy = tmp_path / "deploy" / "docs"
    _build_publisher_with_progressive_procedure(publisher, "publisher", "erp")
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)

    owners = domain_owners([_publisher(publisher, "publisher", {"erp"})])
    compose_docs_root(owners, deploy)
    write_merged_index([_publisher(publisher, "publisher", {"erp"})], deploy)
    generate_domain_baselines(owners, deploy, publisher)

    # Drive scripts.distribute.main through an isolated mother fixture
    # (relocated `__file__` anchor) so production code — not the test —
    # supplies the scope discriminator that keeps the catalog on this arm.
    _write(
        mother / "agents" / "AGENTS.global.md",
        "# Global\n\n## Required reads\n\n- @docs/global/baseline-progressive.md\n",
    )
    _write(mother / "docs" / "global" / "baseline-progressive.md", "\n")
    _write(mother / "teleclaude.yml", "project_slug: mother\n")
    monkeypatch.setattr(distribute, "__file__", str(mother / "scripts" / "distribute.py"))
    monkeypatch.setenv("HOME", str(home))
    # External formatter boundary, unrelated to the scope discriminator under
    # test: avoid a real `npx prettier` subprocess inside the fast test tier.
    monkeypatch.setattr(distribute, "_format_markdown", lambda paths: None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(mother)])

    distribute.main()

    global_body = (mother / "dist" / "global" / "claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert global_body == snapshot


@pytest.mark.spec("project/spec/feature/context/agent-runtime-deployment", "UC-ARD8")
def test_deploy_documentation_blocks_split_domain_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    # Two publishers own the same domain with DISJOINT snippet sets — the old
    # id-collision guard could not catch this; per-domain split detection does.
    _build_publisher(alpha, "alpha", "erp", {"erp/policy/from-alpha": "ALPHA BODY"})
    _build_publisher(beta, "beta", "erp", {"erp/concept/from-beta": "BETA BODY"})
    monkeypatch.setattr(distribute, "load_roots", lambda: [beta])
    monkeypatch.setattr(distribute, "_resolve_git_common_root", lambda root: alpha)
    deploy = tmp_path / "deploy" / "docs"

    with pytest.raises(SystemExit, match="split domain ownership: erp claimed by"):
        deploy_documentation(alpha, alpha / "docs" / "global", deploy_docs_root=deploy)

    # Nothing is composed when the split blocks the deploy.
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
    # Mirror the deployed layout: docs_root is a real dir and each domain entry
    # is a per-domain symlink into an external publisher source dir (see
    # test_deploy_documentation_composes_per_domain_through_the_real_boundary),
    # so the bundle resolves *through* the symlink out of docs_root.
    src_dir = _write(tmp_path / "src" / "creative" / "domain-baseline-bundle.md", generated_bundle).parent
    docs_root.mkdir(parents=True)
    (docs_root / "creative").symlink_to(src_dir)
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

    generate_domain_baselines({"creative": _publisher(publisher, "alpha", {"creative"})}, deploy, tmp_path)

    generated = (domain_src / "domain-baseline-bundle.md").read_text(encoding="utf-8")
    assert generated == snapshot
