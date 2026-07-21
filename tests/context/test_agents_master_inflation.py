"""Functional tests for AGENTS.master.md inflation into deployed AGENTS.md."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pydantic
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
def test_project_progressive_baseline_omits_global_activatable_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    project = tmp_path / "project"
    _write(
        project / "teleclaude.yml",
        "project_slug: fixture\nbusiness:\n  publishes:\n    - slug: erp\n      trigger: Use when doing erp work\n",
    )
    # No progressive ref: the sibling is detected by location, never by a master reference.
    _write(project / "AGENTS.master.md", "# Project\n")
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
                    "scope": "project",
                    "path": "docs/project/policy/example.md",
                },
                {
                    "id": "project/procedure/local-workflow",
                    "description": "Local workflow procedure.",
                    "type": "procedure",
                    "scope": "project",
                    "domain": "project",
                    "activation_trigger": "Use when running the local workflow",
                },
            ]
        ),
    )
    # A local-global-scoped triggered entry: `_load_snippet_index_entries` loads
    # both docs/global and docs/project index files, so collection must filter
    # to `scope == project` or this entry would leak into the project's section.
    _write(
        project / "docs" / "global" / "index.yaml",
        _index_payload(
            [
                {
                    "id": "general/procedure/leaked-general",
                    "description": "Leaked general procedure.",
                    "type": "procedure",
                    "scope": "global",
                    "domain": "general",
                    "activation_trigger": "Use when running leaked general",
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
    monkeypatch.setattr(distribute, "load_roots", lambda: [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(project)])

    distribute.main()

    output = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert output == snapshot


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
def test_global_progressive_baseline_scopes_activatable_catalog_to_general(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    mother = tmp_path / "mother"
    home = tmp_path / "home"
    deploy = tmp_path / "deploy" / "docs"
    erp_publisher = tmp_path / "erp_publisher"
    creative_publisher = tmp_path / "creative_publisher"

    ordinary_ref = _write(
        mother / "docs" / "global" / "general" / "policy" / "ordinary.md",
        "---\ndescription: Ordinary policy.\n---\n# Ordinary — Policy\n\nOrdinary body content.\n",
    )
    # No progressive ref: the sibling is detected by location. One ordinary
    # ref proves `@`-ref expansion still inlines verbatim (Task 2).
    _write(mother / "agents" / "AGENTS.global.md", f"# Global\n\n@{ordinary_ref}\n")
    _write(
        mother / "docs" / "global" / "general" / "policy" / "curated.md",
        "---\ndescription: Curated policy.\n---\n# Curated — Policy\n",
    )
    _write(mother / "docs" / "global" / "baseline-progressive.md", "@docs/global/general/policy/curated.md\n")
    _write(mother / "teleclaude.yml", "project_slug: mother\n")
    _write(
        mother / "docs" / "global" / "index.yaml",
        _index_payload(
            [
                {
                    "id": "general/policy/curated",
                    "description": "Curated policy.",
                    "type": "policy",
                    "scope": "global",
                    "domain": "general",
                    "path": "docs/global/general/policy/curated.md",
                },
            ]
        ),
    )
    _write(
        erp_publisher / "teleclaude.yml",
        "project_slug: erp-publisher\nbusiness:\n  publishes:\n    - slug: erp\n      trigger: Use when doing erp work\n",
    )
    _write(
        creative_publisher / "teleclaude.yml",
        "project_slug: creative-publisher\nbusiness:\n"
        "  publishes:\n    - slug: creative\n      trigger: Use when doing creative work\n",
    )
    _write(
        deploy / "index.yaml",
        _index_payload(
            [
                {
                    "id": "erp/procedure/erp-workflow",
                    "description": "Erp workflow procedure.",
                    "type": "procedure",
                    "domain": "erp",
                    "activation_trigger": "Use when running the erp workflow",
                    "path": "docs/global/erp/procedure/erp-workflow.md",
                },
                {
                    "id": "creative/procedure/creative-workflow",
                    "description": "Creative workflow procedure.",
                    "type": "procedure",
                    "domain": "creative",
                    "activation_trigger": "Use when running the creative workflow",
                    "path": "docs/global/creative/procedure/creative-workflow.md",
                },
                {
                    "id": "general/procedure/general-workflow",
                    "description": "General workflow procedure.",
                    "type": "procedure",
                    "domain": "general",
                    "activation_trigger": "Use when running the general workflow",
                    "path": "docs/global/general/procedure/general-workflow.md",
                },
            ]
        ),
    )
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)
    monkeypatch.setattr(distribute, "load_roots", lambda: [erp_publisher, creative_publisher])
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


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI5")
def test_pending_snippets_are_absent_from_every_transpiled_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    project = tmp_path / "project"
    _write(
        project / "teleclaude.yml",
        "project_slug: fixture\nbusiness:\n  publishes:\n    - slug: erp\n      trigger: Use when doing erp work\n",
    )
    # The pending policy is reachable four ways at once — @-ref from the master,
    # curated by the manifest, triggered in the index, and counted for its
    # domain — so one snapshot proves every surface honors delivered_by.
    _write(project / "AGENTS.master.md", "# Project\n\n@docs/project/policy/pending.md\n")
    _write(
        project / "docs" / "project" / "policy" / "pending.md",
        "---\ndescription: Pending policy.\ndelivered_by:\n  - some-slug\n---\n"
        "# Pending — Policy\n\nUnbuilt body content.\n",
    )
    _write(
        project / "docs" / "project" / "policy" / "live.md",
        "---\ndescription: Live policy.\n---\n# Live — Policy\n",
    )
    _write(
        project / "docs" / "project" / "baseline-progressive.md",
        "@docs/project/policy/live.md\n@docs/project/policy/pending.md\n",
    )
    _write(
        project / "docs" / "project" / "index.yaml",
        _index_payload(
            [
                {
                    "id": "project/policy/live",
                    "description": "Live policy.",
                    "type": "policy",
                    "scope": "project",
                    "path": "docs/project/policy/live.md",
                },
                {
                    "id": "project/policy/pending",
                    "description": "Pending policy.",
                    "type": "policy",
                    "scope": "project",
                    "delivered_by": ["some-slug"],
                    "path": "docs/project/policy/pending.md",
                },
                {
                    "id": "project/procedure/pending-workflow",
                    "description": "Pending workflow procedure.",
                    "type": "procedure",
                    "scope": "project",
                    "domain": "project",
                    "delivered_by": ["some-slug"],
                    "activation_trigger": "Use when running the pending workflow",
                },
                {
                    "id": "project/procedure/live-workflow",
                    "description": "Live workflow procedure.",
                    "type": "procedure",
                    "scope": "project",
                    "domain": "project",
                    "activation_trigger": "Use when running the live workflow",
                },
            ]
        ),
    )
    deploy = tmp_path / "deploy" / "docs"
    _write(
        deploy / "index.yaml",
        _index_payload(
            [
                {
                    "id": "erp/policy/live",
                    "description": "Live erp policy.",
                    "type": "policy",
                    "domain": "erp",
                    "path": "docs/global/erp/policy/live.md",
                },
                {
                    "id": "erp/policy/pending",
                    "description": "Pending erp policy.",
                    "type": "policy",
                    "domain": "erp",
                    "delivered_by": ["some-slug"],
                    "path": "docs/global/erp/policy/pending.md",
                },
            ]
        ),
    )
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)
    monkeypatch.setattr(distribute, "load_roots", lambda: [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(project)])

    distribute.main()

    output = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert output == snapshot


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI6")
def test_lock_sentinels_are_stripped_from_the_generated_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    project = tmp_path / "project"
    _write(project / "teleclaude.yml", "project_slug: fixture\n")
    master = _write(
        project / "AGENTS.master.md",
        "<!-- LOCKED_FILE: DO NOT EDIT. Human-maintained thin wrapper. -->\n\n"
        "# Project\n\nBody content.\n\n"
        "<!-- /LOCKED_FILE -->\n",
    )
    deploy = tmp_path / "deploy" / "docs"
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)
    monkeypatch.setattr(distribute, "load_roots", lambda: [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(project)])

    distribute.main()

    assert (project / "AGENTS.md").read_text(encoding="utf-8") == snapshot
    assert master.read_text(encoding="utf-8") == snapshot(name="master retains its sentinels")


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI4")
def test_hand_listed_triggered_procedure_blocks_the_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    project = tmp_path / "project"
    _write(
        project / "teleclaude.yml",
        "project_slug: fixture\nbusiness:\n  publishes:\n    - slug: erp\n      trigger: Use when doing erp work\n",
    )
    docs_global = project / "docs" / "global"
    _write(
        docs_global / "erp" / "procedure" / "workflow.md",
        "---\ndescription: Workflow procedure.\nactivation_trigger: Use when running the domain workflow\n---\n"
        "# Workflow\n",
    )
    _write(docs_global / "erp" / "baseline.md", "\n")
    # Hand-listing a triggered procedure in the manifest is dead weight —
    # auto-inclusion already surfaces it — so the sync blocks unconditionally.
    _write(docs_global / "erp" / "baseline-progressive.md", "@docs/global/erp/procedure/workflow.md\n")
    _write(
        docs_global / "index.yaml",
        _index_payload(
            [
                {
                    "id": "erp/procedure/workflow",
                    "description": "Workflow procedure.",
                    "type": "procedure",
                    "scope": "global",
                    "domain": "erp",
                    "activation_trigger": "Use when running the domain workflow",
                    "path": "docs/global/erp/procedure/workflow.md",
                },
            ]
        ),
    )
    deploy = tmp_path / "deploy" / "docs"
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)
    monkeypatch.setattr(distribute, "load_roots", lambda: [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(project), "--deploy"])

    with pytest.raises(SystemExit) as exc_info:
        distribute.main()

    assert str(exc_info.value) == snapshot


def _project_with_publishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, publishes_yaml: str) -> Path:
    """Build a project whose config load is exercised at the trigger-resolver boundary.

    The deploy index carries one domain-scoped snippet so `_render_domain_awareness`
    calls `_resolve_domain_triggers`, which loads and validates the project's own
    `business.publishes` entries — the real boundary where an invalid trigger
    fails config load and blocks the sync before any rendering happens.
    """
    project = tmp_path / "project"
    _write(project / "teleclaude.yml", f"project_slug: fixture\nbusiness:\n  publishes:\n{publishes_yaml}\n")
    _write(project / "AGENTS.master.md", "# Project\n")
    deploy = tmp_path / "deploy" / "docs"
    _write(
        deploy / "index.yaml",
        _index_payload(
            [
                {
                    "id": "erp/policy/example",
                    "description": "Example policy.",
                    "type": "policy",
                    "domain": "erp",
                    "path": "docs/global/erp/policy/example.md",
                },
            ]
        ),
    )
    monkeypatch.setattr(distribute, "GLOBAL_DOCS_DIR", deploy)
    monkeypatch.setattr(distribute, "load_roots", lambda: [])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["distribute.py", "--project-root", str(project)])
    return project


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
def test_legacy_bare_string_publishes_list_fails_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    _project_with_publishes(tmp_path, monkeypatch, publishes_yaml="    - erp")

    with pytest.raises(pydantic.ValidationError) as exc_info:
        distribute.main()

    assert str(exc_info.value) == snapshot


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
def test_publishes_entry_missing_trigger_fails_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    _project_with_publishes(tmp_path, monkeypatch, publishes_yaml="    - slug: erp")

    with pytest.raises(pydantic.ValidationError) as exc_info:
        distribute.main()

    assert str(exc_info.value) == snapshot


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
def test_publishes_entry_blank_trigger_fails_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    _project_with_publishes(tmp_path, monkeypatch, publishes_yaml='    - slug: erp\n      trigger: "   "')

    with pytest.raises(pydantic.ValidationError) as exc_info:
        distribute.main()

    assert str(exc_info.value) == snapshot


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
def test_publishes_entry_multiline_trigger_fails_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    _project_with_publishes(
        tmp_path, monkeypatch, publishes_yaml='    - slug: erp\n      trigger: "Use when doing erp\\nwork"'
    )

    with pytest.raises(pydantic.ValidationError) as exc_info:
        distribute.main()

    assert str(exc_info.value) == snapshot


@pytest.mark.spec("project/spec/feature/context/agents-master-inflation", "UC-AMI3")
def test_publishes_entry_over_length_trigger_fails_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: Any
) -> None:
    # 200 characters is the accepted boundary (see PUBLISHES_TRIGGER_MAX_LENGTH);
    # 201 is one character past it and must fail config load.
    over_length_trigger = "x" * 201
    _project_with_publishes(
        tmp_path, monkeypatch, publishes_yaml=f"    - slug: erp\n      trigger: {over_length_trigger}"
    )

    with pytest.raises(pydantic.ValidationError) as exc_info:
        distribute.main()

    assert str(exc_info.value) == snapshot
