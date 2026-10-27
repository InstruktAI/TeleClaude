"""Which registered homes are present on this computer, and where each one's folder is.

The configuration context owns which companies, people and projects are
registered here. Callers ask by home kind and slug and never join a slug into a
path themselves; an unregistered home, or a slug that cannot name one, is
answered as absent.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.config.loader import find_company_config_path, list_company_config_paths
from teleclaude.config_subjects import ConfigSubjectKind
from teleclaude.paths import GLOBAL_CONFIG_PATH, PEOPLE_DIR, ConfigFileName
from teleclaude.project_manifest import load_registered_roots
from teleclaude.slug import derive_project_slug, validate_slug

_UTF8 = "utf-8"
_PROJECT_SLUG_FIELD = "project_slug"
_PROJECT_NAME_FIELD = "project_name"


def live_tier_declarations() -> tuple[Path, ...]:
    """Every tier declaration present on this computer: the global one, each person's and company's, each project's."""
    candidates = [GLOBAL_CONFIG_PATH]
    if PEOPLE_DIR.is_dir():
        candidates.extend(sorted(PEOPLE_DIR.glob(f"*/{ConfigFileName.OVERLAY}")))
    candidates.extend(list_company_config_paths())
    candidates.extend(root.path / ConfigFileName.OVERLAY for root in load_registered_roots() if root.is_present)
    seen: set[Path] = set()
    declarations: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        declarations.append(candidate)
    return tuple(declarations)


def registered_home_folder(kind: ConfigSubjectKind, slug: str) -> Path | None:
    """Answer the folder of the registered company, person or project ``slug`` on this computer.

    Returns ``None`` when no such home is registered here, when the slug cannot
    name a home, and for any kind that is not a company, person or project. The
    folder holds the home's ``teleclaude.yml``.
    """
    try:
        validate_slug(slug)
    except ValueError:
        return None
    if kind is ConfigSubjectKind.COMPANY:
        company_path = find_company_config_path(slug)
        return None if company_path is None else company_path.parent
    if kind is ConfigSubjectKind.PERSON:
        person_folder = PEOPLE_DIR / slug
        return person_folder if (person_folder / ConfigFileName.OVERLAY).is_file() else None
    if kind is ConfigSubjectKind.PROJECT:
        return _registered_project_root(slug)
    return None


def project_folder(reference: str) -> Path | None:
    """Answer the folder of the project a request names: a path as given, else the registered project's folder.

    A caller addressing another computer from a project's checkout names the project by the identity
    it is registered under, since its own path means nothing here. Returns ``None`` when the
    reference is neither a path nor an identity registered on this computer.
    """
    path = Path(reference)
    if path.is_absolute():
        return path
    return registered_home_folder(ConfigSubjectKind.PROJECT, reference)


def project_identity_for_folder(root: Path) -> str:
    """Answer the identity a project's folder is registered under: how another computer names the project.

    A path means nothing on another computer; the identity is what its own registry resolves to its folder.
    """
    return _raw_project_identity(root) or root.name


def _registered_project_root(slug: str) -> Path | None:
    """Find the registered project root whose identity is ``slug``.

    A root's identity comes from its raw declaration, so a project whose
    configuration fails to load is still identified, and its failure surfaces
    from the load that follows.
    """
    for root in load_registered_roots():
        if root.is_present and _raw_project_identity(root.path) == slug:
            return root.path
    return None


def _raw_project_identity(root: Path) -> str | None:
    declaration = root / ConfigFileName.OVERLAY
    try:
        document: object = yaml.safe_load(declaration.read_text(encoding=_UTF8))
    except (OSError, UnicodeError, yaml.YAMLError):
        return derive_project_slug(None, None, root)
    if not isinstance(document, dict):
        return derive_project_slug(None, None, root)
    return derive_project_slug(document.get(_PROJECT_SLUG_FIELD), document.get(_PROJECT_NAME_FIELD), root)
