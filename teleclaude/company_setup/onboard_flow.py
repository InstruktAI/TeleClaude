"""Deterministic company-onboarding primitives plus the analysis dispatch.

``scaffold_company`` bootstraps the ``companies/<slug>/`` tree; ``compute_inbox_changes``
diffs the inbox against the SHA digest recorded in ``meta.yaml`` so re-onboarding
reprocesses only changed material; ``run_company_onboard`` scaffolds and then
dispatches the agent analysis session that generates the path-derived snippets.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from teleclaude.config.schema import CompanyConfig
from teleclaude.git import Repo
from teleclaude.paths import COMPANIES_ROOT
from teleclaude.project_setup.onboard_flow import _dispatch_session
from teleclaude.slug import normalize_slug, validate_slug

# The company doc taxonomies scaffolded under docs/ (the company-scaffolding spec
# omits adr — companies carry no decision record tree).
COMPANY_TAXONOMIES = ("principle", "concept", "policy", "procedure", "design", "spec")

_ANALYZE_COMMAND = "/companies-analyze"


def _meta_path(company_dir: Path) -> Path:
    return company_dir / "meta.yaml"


def _load_meta(company_dir: Path) -> dict[str, Any]:  # guard: loose-dict - meta.yaml is unstructured bookkeeping
    meta_path = _meta_path(company_dir)
    if not meta_path.exists():
        return {}
    loaded = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _write_meta(company_dir: Path, meta: dict[str, Any]) -> None:  # guard: loose-dict - meta.yaml bookkeeping
    _meta_path(company_dir).write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_inbox_files(inbox: Path) -> list[Path]:
    """Inbox material files, excluding the inbox's own git metadata."""
    return sorted(path for path in inbox.rglob("*") if path.is_file() and ".git" not in path.relative_to(inbox).parts)


def scaffold_company(name: str, slug: str | None = None, *, companies_root: Path = COMPANIES_ROOT) -> Path:
    """Scaffold ``companies/<slug>/`` — idempotent deterministic plumbing only.

    Creates the docs taxonomy tree and a git-tracked inbox, writes a minimal
    ``CompanyConfig`` overlay, seeds ``meta.yaml`` bookkeeping, and creates an
    owner-only (``0600``) ``.env`` for service credentials. Re-running preserves
    existing files (config, meta, populated inbox) rather than clobbering them.
    """
    resolved_slug = slug.strip() if slug else normalize_slug(name)
    validate_slug(resolved_slug)

    company_dir = companies_root / resolved_slug
    docs = company_dir / "docs"
    for taxonomy in COMPANY_TAXONOMIES:
        (docs / taxonomy).mkdir(parents=True, exist_ok=True)

    inbox = company_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    if not (inbox / ".git").exists():
        Repo.init(inbox)

    config_path = company_dir / "teleclaude.yml"
    if not config_path.exists():
        config = CompanyConfig(name=name, slug=resolved_slug)
        config_path.write_text(
            yaml.safe_dump(config.model_dump(mode="json", exclude_defaults=True), sort_keys=False),
            encoding="utf-8",
        )

    if not _meta_path(company_dir).exists():
        _write_meta(
            company_dir,
            {
                "company_name": name,
                "slug": resolved_slug,
                "created_at": datetime.now(UTC).isoformat(),
                "onboard_count": 0,
                "processed_files": [],
            },
        )

    env_path = company_dir / ".env"
    if not env_path.exists():
        env_path.touch()
    os.chmod(env_path, 0o600)

    return company_dir


def compute_inbox_changes(company_dir: Path) -> list[Path]:
    """Return inbox files whose content differs from the recorded SHA digest.

    New and modified files are returned; files with an unchanged SHA since the
    last processing are skipped. This is the deterministic primitive that lets
    re-onboarding reprocess only changed material.
    """
    inbox = company_dir / "inbox"
    if not inbox.exists():
        return []
    meta = _load_meta(company_dir)
    processed = meta.get("processed_files")
    recorded: dict[str, str] = {}
    if isinstance(processed, list):
        for entry in processed:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str) and isinstance(entry.get("sha256"), str):
                recorded[entry["path"]] = entry["sha256"]

    changed: list[Path] = []
    for path in _iter_inbox_files(inbox):
        rel = str(path.relative_to(inbox))
        if recorded.get(rel) != _file_sha256(path):
            changed.append(path)
    return changed


def record_processed_files(company_dir: Path, files: list[Path]) -> None:
    """Record the SHA digest of processed inbox files in ``meta.yaml``.

    Unchanged-SHA files retain their prior record; the supplied files are
    upserted. Removed files are not purged — generated knowledge persists.
    """
    inbox = company_dir / "inbox"
    meta = _load_meta(company_dir)
    processed = meta.get("processed_files")
    by_path: dict[str, dict[str, Any]] = {}  # guard: loose-dict - meta.yaml entries
    if isinstance(processed, list):
        for entry in processed:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                by_path[entry["path"]] = entry

    now = datetime.now(UTC).isoformat()
    for path in files:
        rel = str(path.relative_to(inbox))
        by_path[rel] = {"path": rel, "sha256": _file_sha256(path), "processed_at": now}

    meta["processed_files"] = [by_path[key] for key in sorted(by_path)]
    _write_meta(company_dir, meta)


def run_company_onboard(name: str, slug: str | None = None) -> None:
    """Scaffold the company tree, then dispatch the AI analysis session.

    Scaffolding runs synchronously; the analysis dispatch is fire-and-forget —
    the agent reads the inbox, generates path-derived snippets, builds the index,
    and validates. Operator monitors progress via ``telec sessions list``.
    """
    company_dir = scaffold_company(name, slug)
    _dispatch_session(company_dir, _ANALYZE_COMMAND, "Company doc-snippet analysis")
