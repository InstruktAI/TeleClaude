"""Compose Mother's human-curated global skill folders into the shared catalog."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from teleclaude.paths import GLOBAL_SKILLS_DIR, SKILL_STORE_DIR

_AGENTS_DIRNAME = "agents"
_GLOBAL_DIRNAME = "global"
_SKILLS_DIRNAME = "skills"
_CATALOG_MASTER_FILENAME = "AGENTS.master.md"
_CATALOG_OUTPUT_FILENAME = "AGENTS.md"
_CATALOG_CLAUDE_FILENAME = "CLAUDE.md"
_CATALOG_CLAUDE_CONTENT = "@./AGENTS.md\n"
_NEXT_CATALOG_DIRNAME = ".skills.next"
_PREVIOUS_CATALOG_DIRNAME = ".skills.previous"
_ALL_GLOB = "*"
_UTF8 = "utf-8"
_HASH_FILE_MARKER = b"file\0"
_HASH_DIRECTORY_MARKER = b"directory\0"
_HASH_SYMLINK_MARKER = b"symlink\0"
_HASH_SEPARATOR = b"\0"
_DIGEST_LENGTH = 64
_COPY_TEMP_SUFFIX = ".next"
_MISSING_CATALOG_MESSAGE = "global skill catalog master not found: {path}"
_COMPOSED_MESSAGE = "  Composed global skills: {target} ({count} skill(s))"

CatalogRenderer = Callable[[Path], str]


@dataclass(frozen=True)
class GlobalSkillContribution:
    """One named skill folder Mother carries in its tiered global-skill source."""

    name: str
    source: Path
    publisher_root: Path


def global_skill_source_root(mother_root: Path) -> Path:
    """Return Mother's tiered global-skill source root.

    The catalog is composed from Mother alone — no other registered project
    is ever a publisher here. A side-project skill folder under this same
    relative path in its own checkout is refused at validation
    (`teleclaude.agent_artifacts`), never merged.
    """
    return mother_root / _AGENTS_DIRNAME / _GLOBAL_DIRNAME / _SKILLS_DIRNAME


def _direct_skill_dirs(mother_root: Path) -> Iterator[Path]:
    source_root = global_skill_source_root(mother_root)
    if not source_root.is_dir():
        return
    for entry in sorted(source_root.iterdir(), key=lambda path: path.name):
        if entry.is_dir():
            yield entry


def collect_global_skills(mother_root: Path) -> list[GlobalSkillContribution]:
    """Collect Mother's own direct skill folders. A filesystem directory can never
    yield the same entry name twice, so no cross-publisher collision is possible here.
    """
    return [GlobalSkillContribution(source.name, source, mother_root) for source in _direct_skill_dirs(mother_root)]


def _digest_directory(source: Path) -> str:
    digest = hashlib.sha256()
    for entry in sorted(source.rglob(_ALL_GLOB), key=lambda path: path.relative_to(source).as_posix()):
        relative = entry.relative_to(source).as_posix().encode()
        if entry.is_symlink():
            digest.update(_HASH_SYMLINK_MARKER)
            digest.update(relative)
            digest.update(_HASH_SEPARATOR)
            digest.update(os.readlink(entry).encode())
        elif entry.is_dir():
            digest.update(_HASH_DIRECTORY_MARKER)
            digest.update(relative)
        elif entry.is_file():
            digest.update(_HASH_FILE_MARKER)
            digest.update(relative)
            digest.update(_HASH_SEPARATOR)
            digest.update(entry.read_bytes())
    return digest.hexdigest()[:_DIGEST_LENGTH]


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _materialize_snapshot(contribution: GlobalSkillContribution) -> Path:
    digest = _digest_directory(contribution.source)
    digest_root = SKILL_STORE_DIR / digest
    snapshot = digest_root / contribution.name
    if snapshot.is_dir():
        return snapshot

    digest_root.mkdir(parents=True, exist_ok=True)
    temporary = digest_root / f"{contribution.name}{_COPY_TEMP_SUFFIX}"
    _remove_path(temporary)
    shutil.copytree(contribution.source, temporary, symlinks=True)
    os.replace(temporary, snapshot)
    return snapshot


def _stage_catalog(contributions: list[GlobalSkillContribution]) -> Path:
    staging = GLOBAL_SKILLS_DIR.parent / _NEXT_CATALOG_DIRNAME
    _remove_path(staging)
    staging.mkdir(parents=True, exist_ok=True)
    for contribution in contributions:
        snapshot = _materialize_snapshot(contribution)
        (staging / contribution.name).symlink_to(snapshot, target_is_directory=True)
    return staging


def compose_global_skill_catalog(
    mother_root: Path,
    render_catalog: CatalogRenderer,
) -> None:
    """Materialize global skills, render the Mother catalog, and publish it as one unit."""
    catalog_master = global_skill_source_root(mother_root) / _CATALOG_MASTER_FILENAME
    if not catalog_master.is_file():
        raise FileNotFoundError(_MISSING_CATALOG_MESSAGE.format(path=catalog_master))

    contributions = collect_global_skills(mother_root)
    staging = _stage_catalog(contributions)
    previous = GLOBAL_SKILLS_DIR.parent / _PREVIOUS_CATALOG_DIRNAME
    _remove_path(previous)
    had_previous = os.path.lexists(GLOBAL_SKILLS_DIR)
    if had_previous:
        os.replace(GLOBAL_SKILLS_DIR, previous)
    os.replace(staging, GLOBAL_SKILLS_DIR)

    try:
        rendered = render_catalog(catalog_master)
        source_catalog = catalog_master.parent / _CATALOG_OUTPUT_FILENAME
        source_claude = catalog_master.parent / _CATALOG_CLAUDE_FILENAME
        source_catalog.write_text(rendered, encoding=_UTF8)
        source_claude.write_text(_CATALOG_CLAUDE_CONTENT, encoding=_UTF8)
        (GLOBAL_SKILLS_DIR / _CATALOG_OUTPUT_FILENAME).write_text(rendered, encoding=_UTF8)
        (GLOBAL_SKILLS_DIR / _CATALOG_CLAUDE_FILENAME).write_text(_CATALOG_CLAUDE_CONTENT, encoding=_UTF8)
    except Exception:
        _remove_path(GLOBAL_SKILLS_DIR)
        if had_previous:
            os.replace(previous, GLOBAL_SKILLS_DIR)
        raise
    _remove_path(previous)
    print(_COMPOSED_MESSAGE.format(target=GLOBAL_SKILLS_DIR, count=len(contributions)))
