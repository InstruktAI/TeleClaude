"""Functional tests for company onboarding: scaffold, SHA-tracked re-onboard, and surface."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from teleclaude.cli.telec.surface import CLI_SURFACE
from teleclaude.cli.telec.surface_types import TelecCommand
from teleclaude.company_setup import compute_inbox_changes, record_processed_files, scaffold_company
from teleclaude.company_setup.onboard_flow import _ANALYZE_COMMAND
from teleclaude.docs_index import build_company_index_payload
from teleclaude.paths import REPO_ROOT

pytestmark = pytest.mark.functional

_NAME = "Acme Corp"
_SLUG = "acme-corp"
_SNIPPET_ID = "company/policy/security"
_EXPECTED_SCOPE = "global"
_EXPECTED_DOMAIN = "company"
_AUTHORED_CLASSIFICATION_ERROR = "path-derived classification"
_ONBOARD_VERB = "onboard"
_CONFIG_COMPANY_VERB = "company"


def test_scaffold_creates_company_tree(tmp_path: Path) -> None:
    """Onboard scaffolds the company folder tree with a git inbox and a 0600 .env."""
    company_dir = scaffold_company(_NAME, companies_root=tmp_path)

    assert company_dir == tmp_path / _SLUG
    assert (company_dir / "docs" / "policy").is_dir()
    assert (company_dir / "inbox" / ".git").exists()
    assert (company_dir / "teleclaude.yml").is_file()
    assert (company_dir / "meta.yaml").is_file()
    env_mode = stat.S_IMODE(os.stat(company_dir / ".env").st_mode)
    assert env_mode == 0o600


def test_reonboard_reprocesses_only_changed_inbox_file(tmp_path: Path) -> None:
    """A second onboard with one changed inbox file reprocesses only that file (SHA skip)."""
    company_dir = scaffold_company(_NAME, companies_root=tmp_path)
    inbox = company_dir / "inbox"
    file_a = inbox / "handbook.md"
    file_b = inbox / "security.md"
    file_a.write_text("v1\n", encoding="utf-8")
    file_b.write_text("stable\n", encoding="utf-8")

    assert set(compute_inbox_changes(company_dir)) == {file_a, file_b}
    record_processed_files(company_dir, [file_a, file_b])
    assert compute_inbox_changes(company_dir) == []

    file_a.write_text("v2\n", encoding="utf-8")
    assert compute_inbox_changes(company_dir) == [file_a]


def test_path_derived_company_snippet_indexes(tmp_path: Path) -> None:
    """A path-derived company snippet (only `description` authored) classifies and indexes."""
    company_dir = scaffold_company(_NAME, companies_root=tmp_path)
    (company_dir / "docs" / "policy" / "security.md").write_text(
        "---\ndescription: Security policy.\n---\n# Security\n", encoding="utf-8"
    )

    payload = build_company_index_payload(company_dir)

    entry = next(item for item in payload["snippets"] if item["id"] == _SNIPPET_ID)
    assert entry["scope"] == _EXPECTED_SCOPE
    assert entry["domain"] == _EXPECTED_DOMAIN


def test_authored_classification_frontmatter_rejected(tmp_path: Path) -> None:
    """A company snippet that authors classification keys violates the path-derived contract."""
    company_dir = scaffold_company(_NAME, companies_root=tmp_path)
    (company_dir / "docs" / "policy" / "security.md").write_text(
        "---\nid: company/policy/security\ndescription: Security.\n---\n# Security\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match=_AUTHORED_CLASSIFICATION_ERROR):
        build_company_index_payload(company_dir)


def test_companies_onboard_surface_present_and_config_company_absent() -> None:
    """`telec companies onboard` is on the surface; `telec config company` is not."""
    assert TelecCommand("companies") is TelecCommand.COMPANIES
    assert _ONBOARD_VERB in CLI_SURFACE["companies"].subcommands
    assert _CONFIG_COMPANY_VERB not in CLI_SURFACE["config"].subcommands


def test_onboard_dispatch_target_has_shippable_command_artifact() -> None:
    """The slash command the onboard flow dispatches resolves to a shipped command artifact."""
    command_name = _ANALYZE_COMMAND.lstrip("/")
    assert (REPO_ROOT / "agents" / "commands" / f"{command_name}.md").exists()
