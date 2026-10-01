"""Deterministic company-onboarding primitives.

``scaffold_company`` bootstraps the ``companies/<slug>/`` home and converges it to
the company templates; ``compute_inbox_changes``
diffs the inbox against the SHA digest recorded in ``meta.yaml`` so re-onboarding
reprocesses only changed material. Analysis dispatch is an explicit, separate
act (`telec sessions run`), never a side effect of scaffolding.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from teleclaude.config.declaration import write_declared_config
from teleclaude.config.schema import CompanyConfig, ConfigKind
from teleclaude.core.reconciliation.home_convergence import company_home_targets
from teleclaude.core.reconciliation.template_installation import materialize_template_targets
from teleclaude.git import Repo
from teleclaude.paths import COMPANIES_ROOT, ConfigFileName
from teleclaude.slug import normalize_slug, validate_slug

# Taxonomy directories earlier scaffolds created empty; removed while they are still empty.
_LEGACY_TAXONOMIES = ("principle", "concept", "policy", "procedure", "design", "spec")
_COMPANY_DOCS = Path("docs")
_COMPANY_LOCAL_DOCS = _COMPANY_DOCS / "local"


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

    Creates a git-tracked inbox, writes a minimal ``CompanyConfig`` overlay, seeds
    ``meta.yaml`` bookkeeping, and creates an owner-only (``0600``) ``.env`` for
    service credentials; re-running preserves those existing files. Removes empty
    taxonomy directories earlier scaffolds left, then converges the home to the
    company templates: the master (and an enabled help desk's master) is the
    template's rendering after every call, and the local baseline manifests are
    created only when absent.
    """
    resolved_slug = slug.strip() if slug else normalize_slug(name)
    validate_slug(resolved_slug)

    company_dir = companies_root / resolved_slug
    company_dir.mkdir(parents=True, exist_ok=True)
    _remove_empty_legacy_taxonomies(company_dir)

    inbox = company_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    if not (inbox / ".git").exists():
        Repo.init(inbox)

    config_path = company_dir / ConfigFileName.OVERLAY
    if not config_path.exists():
        config = CompanyConfig(kind=ConfigKind.COMPANY, name=name, slug=resolved_slug)
        write_declared_config(
            config_path,
            ConfigKind.COMPANY,
            config.model_dump(mode="json", exclude_defaults=True),
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

    env_path = company_dir / ConfigFileName.ENV
    if not env_path.exists():
        env_path.touch()
    os.chmod(env_path, 0o600)

    materialize_template_targets(company_home_targets(company_dir), values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation
    return company_dir


def _remove_empty_legacy_taxonomies(company_dir: Path) -> None:
    """Remove each legacy taxonomy directory under either docs layout only while it is empty."""
    for docs_root in (company_dir / _COMPANY_DOCS, company_dir / _COMPANY_LOCAL_DOCS):
        for taxonomy in _LEGACY_TAXONOMIES:
            directory = docs_root / taxonomy
            if directory.is_dir() and not directory.is_symlink() and not any(directory.iterdir()):
                directory.rmdir()


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
