"""Resolve the registered configuration subject governing a working folder."""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.config.context_root import (
    ConfigDeclaration,
    load_declared_config_kind,
    load_raw_declaration,
    nearest_config_declaration,
)
from teleclaude.config.migrations import registered_subject
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import ConfigFileName
from teleclaude.project_manifest import ConfigKind
from teleclaude.project_root import declaration_root
from teleclaude.slug import derive_project_slug

_PROJECT_SLUG_KEY = "project_slug"
_PROJECT_NAME_KEY = "project_name"
_PROJECT_READ_SUBJECT = "project"
_DECLARATION_ERROR = "Failed to resolve configuration subject from declaration {path}: {error}"
_PROJECT_DECLARATION_REQUIRED = "Owning checkout does not declare a project: {path}"


class SubjectResolutionError(ValueError):
    """A declaration on a working folder's path cannot identify its subject."""

    def __init__(self, message: str, *, declaration_path: Path) -> None:
        super().__init__(message)
        self.declaration_path = declaration_path


def resolve_config_subject(working_folder: Path) -> SubjectRef | None:
    """Resolve the registry subject declared nearest to a session's working folder."""
    declaration = nearest_config_declaration(working_folder, error_factory=_declaration_error)
    return _resolve_declaration(declaration)


class ConfigSubjectResolver:
    """Resolve multiple folders while reading each nearest declaration only once."""

    def __init__(self) -> None:
        self._by_declaration: dict[Path | None, SubjectRef | None | SubjectResolutionError] = {}
        self._declarations_by_directory: dict[Path, ConfigDeclaration | None | Exception] = {}

    def resolve(self, working_folder: Path) -> SubjectRef | None:
        """Resolve a folder and memoize the result by its nearest declaration path."""
        declaration = nearest_config_declaration(
            working_folder,
            error_factory=_declaration_error,
            directory_cache=self._declarations_by_directory,
        )
        declaration_path = declaration.path if declaration is not None else None
        if declaration_path in self._by_declaration:
            result = self._by_declaration[declaration_path]
            if isinstance(result, SubjectResolutionError):
                raise result
            return result
        try:
            result = _resolve_declaration(declaration)
        except SubjectResolutionError as error:
            self._by_declaration[declaration_path] = error
            raise
        self._by_declaration[declaration_path] = result
        return result


def _resolve_declaration(declaration: ConfigDeclaration | None) -> SubjectRef | None:
    """Resolve one already-identified declaration through its owning rules."""
    if declaration is None or declaration.kind is ConfigKind.GLOBAL:
        return None
    if declaration.kind is ConfigKind.PROJECT:
        return _resolve_project_subject(declaration.path)
    return registered_subject(declaration.path)


def _resolve_project_subject(declaration_path: Path) -> SubjectRef:
    """Resolve a project declaration from its owning checkout, not a slug worktree."""
    root = declaration_root(declaration_path.parent)
    owning_declaration = root / ConfigFileName.OVERLAY
    try:
        kind = load_declared_config_kind(owning_declaration)
        if kind is not ConfigKind.PROJECT:
            raise ValueError(_PROJECT_DECLARATION_REQUIRED.format(path=owning_declaration))
        raw = load_raw_declaration(owning_declaration, subject=_PROJECT_READ_SUBJECT)
        slug = derive_project_slug(raw.get(_PROJECT_SLUG_KEY), raw.get(_PROJECT_NAME_KEY), root)
        if slug is None:
            raise ValueError(_PROJECT_DECLARATION_REQUIRED.format(path=owning_declaration))
        return SubjectRef(ConfigSubjectKind.PROJECT, slug)
    except SubjectResolutionError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise _declaration_error(owning_declaration, exc) from exc


def _declaration_error(path: Path, error: Exception) -> SubjectResolutionError:
    """Build the normalized failure used for unreadable or invalid declarations."""
    return SubjectResolutionError(_DECLARATION_ERROR.format(path=path, error=error), declaration_path=path)
