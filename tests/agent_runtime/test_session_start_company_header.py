"""Functional tests for session-start company-header injection.

The company header is the company-scoped twin of the person header: resolved
from the active project's company and rendered before the person header.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.hooks import receiver

pytestmark = pytest.mark.functional

_COMPANY_SLUG = "instrukt-ai"
_COMPANY_NAME = "Instrukt AI"
_COMPANY_DESC = "An AI orphanage building agents to become free."
_PERSON_HEADER = "Human owner: Alice"
_UNKNOWN_SLUG = "ghost-co"
_WARNING_TOKEN = "WARNING"


class _AdditionalContextAdapter:
    def format_additional_context(self, hook_event_name: str, context: str) -> str:
        del hook_event_name
        return context


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, project_company: str | None) -> Path:
    """Wire a project workspace and a company folder; quiet the other context sources."""
    companies_root = tmp_path / "companies"
    company_dir = companies_root / _COMPANY_SLUG
    company_dir.mkdir(parents=True)
    (company_dir / "teleclaude.yml").write_text(
        f"name: {_COMPANY_NAME}\nslug: {_COMPANY_SLUG}\ndescription: {_COMPANY_DESC}\n", encoding="utf-8"
    )
    monkeypatch.setattr(receiver.tc_paths, "COMPANIES_ROOT", companies_root)

    project_root = tmp_path / "proj"
    project_root.mkdir()
    company_line = f"company: {project_company}\n" if project_company else ""
    (project_root / "teleclaude.yml").write_text(f"project_slug: proj\n{company_line}", encoding="utf-8")

    monkeypatch.setattr(receiver, "_resolve_identity_context", lambda session_id: (None, _PERSON_HEADER))
    monkeypatch.setattr(receiver, "_resolve_command_domain_for_session", lambda session_id: None)
    monkeypatch.setattr(receiver, "_get_memory_context", lambda project_name, *, identity_key=None: "")
    return project_root


def test_company_header_injected_before_person_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A session in a company-declaring project carries the company header before the person header."""
    project_root = _setup(tmp_path, monkeypatch, project_company=_COMPANY_SLUG)

    receiver._print_additional_context("SessionStart", str(project_root), _AdditionalContextAdapter(), session_id="s1")

    out = capsys.readouterr().out
    assert _COMPANY_NAME in out
    assert _COMPANY_DESC in out
    assert out.index(_COMPANY_NAME) < out.index(_PERSON_HEADER)


def test_no_company_project_carries_no_company_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A session whose project declares no company carries no company header."""
    project_root = _setup(tmp_path, monkeypatch, project_company=None)

    receiver._print_additional_context("SessionStart", str(project_root), _AdditionalContextAdapter(), session_id="s1")

    out = capsys.readouterr().out
    assert _COMPANY_NAME not in out
    assert _PERSON_HEADER in out


def test_unknown_company_surfaces_warning_without_leaking_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A project declaring an unconfigured company surfaces a warning and leaks no profile."""
    project_root = _setup(tmp_path, monkeypatch, project_company=_UNKNOWN_SLUG)

    receiver._print_additional_context("SessionStart", str(project_root), _AdditionalContextAdapter(), session_id="s1")

    out = capsys.readouterr().out
    assert _WARNING_TOKEN in out
    assert _UNKNOWN_SLUG in out
    # The misconfiguration surfaces, but the unrelated configured company never leaks.
    assert _COMPANY_NAME not in out
