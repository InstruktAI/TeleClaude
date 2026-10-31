"""Publish configuration schemas into the machine home and link project roots."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from instrukt_ai_logging import get_logger

from teleclaude.config.declaration import (
    COMPUTER_SCHEMA_FILENAME,
    HOME_SCHEMA_DIRECTORY,
    PROJECT_SCHEMA_LINK_DIRECTORY,
    schema_filename,
)
from teleclaude.config.schema import ConfigKind
from teleclaude.config.schema_export import export_computer_schema, export_tier_schemas
from teleclaude.core.models import JsonDict
from teleclaude.file_transaction import LOCK_SUFFIX
from teleclaude.git import Repo
from teleclaude.mcp.registry import MCP_SCHEMA_FILENAME, MCP_SCHEMA_SOURCE_PATH
from teleclaude.paths import TELECLAUDE_HOME

logger = get_logger(__name__)

_UTF8: Final = "utf-8"
_NEWLINE: Final = "\n"
_PROJECT_SCHEMA_DIRECTORY: Final = "schemas"
_LOCAL_EXCLUDE_DIRECTORY: Final = "info"
_LOCAL_EXCLUDE_FILENAME: Final = "exclude"
_PROJECT_CONFIG_FILENAME: Final = "teleclaude.yml"
_PROJECT_CONFIG_PATH: Final = Path(_PROJECT_CONFIG_FILENAME)
_PROJECT_CONFIG_LOCK_PATH: Final = _PROJECT_CONFIG_PATH.with_suffix(
    f"{_PROJECT_CONFIG_PATH.suffix}{LOCK_SUFFIX}",
)
_LOCAL_EXCLUDE_PATTERNS: Final = (
    "/.teleclaude/",
    f"/{_PROJECT_CONFIG_LOCK_PATH.as_posix()}",
)
_MCP_SCHEMA_INVALID: Final = "MCP registry schema source must contain a JSON object."
_PUBLICATION_EVENT: Final = "config_schema_publication"
_PUBLICATION_CONFLICT_EVENT: Final = "config_schema_publication_conflict"
_LINK_EVENT: Final = "project_config_schema_link"
_SCHEMA_TARGET_CONFLICT: Final = "Configuration schema target is not a directory: {target}"
_PUBLICATION_SUMMARY: Final = "config-schemas: target={target} written={written} unchanged={unchanged}"
_FAILED_EXIT_CODE: Final = 1
_SUCCEEDED_EXIT_CODE: Final = 0
_KNOWN_SCHEMA_FILENAMES: Final = frozenset(
    {schema_filename(kind) for kind in ConfigKind} | {COMPUTER_SCHEMA_FILENAME, MCP_SCHEMA_FILENAME}
)


class SchemaLinkDisposition(StrEnum):
    """Terminal state of one project's machine-local schema link."""

    CREATED = "created"
    REPOINTED = "repointed"
    UNCHANGED = "unchanged"
    OCCUPIED = "occupied"


class SchemaCopyDisposition(StrEnum):
    """Terminal state of a repository-local generated schema copy."""

    ABSENT = "absent"
    REMOVED = "removed"
    RETAINED_TRACKED = "retained_tracked"
    RETAINED_FOREIGN = "retained_foreign"


class SchemaPublicationConflict(FileExistsError):
    """Raised when the schema target is occupied by a non-directory entry."""

    def __init__(self, target: Path, source_root: Path) -> None:
        self.target = target
        self.source_root = source_root
        super().__init__(_SCHEMA_TARGET_CONFLICT.format(target=target))


@dataclass(frozen=True)
class ConfigSchemaPublication:
    """Content-gated result of publishing all configuration schemas."""

    target: Path
    source_root: Path
    replaced_interim_link: bool
    written: tuple[str, ...]
    unchanged: tuple[str, ...]


@dataclass(frozen=True)
class ProjectSchemaLink:
    """Observed disposition and target of one project's schema link."""

    root: Path
    disposition: SchemaLinkDisposition
    resolved_target: Path | None


def publish_config_schemas(target: Path | None = None) -> ConfigSchemaPublication:
    """Publish the computer, tier and MCP schemas into a real home directory."""
    destination = target if target is not None else TELECLAUDE_HOME / HOME_SCHEMA_DIRECTORY
    source_root = Path(__file__).resolve().parents[3]
    replaced_interim_link = destination.is_symlink()
    if replaced_interim_link:
        destination.unlink()
    if destination.exists() and not destination.is_dir():
        error = SchemaPublicationConflict(destination, source_root)
        logger.error(
            _PUBLICATION_CONFLICT_EVENT,
            target=str(destination),
            source_root=str(source_root),
        )
        raise error

    destination.mkdir(parents=True, exist_ok=True)
    schemas = export_tier_schemas()
    mcp_schema = json.loads(MCP_SCHEMA_SOURCE_PATH.read_text(encoding=_UTF8))
    if not isinstance(mcp_schema, dict):
        raise TypeError(_MCP_SCHEMA_INVALID)
    payloads: list[tuple[str, JsonDict]] = []
    for kind, schema in schemas.items():
        payloads.append((schema_filename(kind), schema))
    payloads.append((COMPUTER_SCHEMA_FILENAME, export_computer_schema()))
    payloads.append((MCP_SCHEMA_FILENAME, cast(JsonDict, mcp_schema)))

    written: list[str] = []
    unchanged: list[str] = []
    for filename, schema in payloads:
        output_path = destination / filename
        if _has_same_schema(output_path, schema):
            unchanged.append(filename)
            continue
        output_path.write_text(json.dumps(schema, indent=2) + _NEWLINE, encoding=_UTF8)
        written.append(filename)

    result = ConfigSchemaPublication(
        target=destination,
        source_root=source_root,
        replaced_interim_link=replaced_interim_link,
        written=tuple(written),
        unchanged=tuple(unchanged),
    )
    logger.info(
        _PUBLICATION_EVENT,
        target=str(result.target),
        source_root=str(result.source_root),
        replaced_interim_link=result.replaced_interim_link,
        written=result.written,
        unchanged=result.unchanged,
    )
    return result


def _has_same_schema(path: Path, schema: JsonDict) -> bool:
    if not path.exists():
        return False
    try:
        existing: object = json.loads(path.read_text(encoding=_UTF8))
        return existing == schema
    except json.JSONDecodeError:
        return False


def converge_project_schema_link(root: Path) -> ProjectSchemaLink:
    """Ensure a project root links to the machine's published schema directory."""
    link_path = root / PROJECT_SCHEMA_LINK_DIRECTORY
    target = (TELECLAUDE_HOME / HOME_SCHEMA_DIRECTORY).resolve()
    _ensure_local_exclude(root)

    if not link_path.is_symlink():
        if link_path.exists():
            result = ProjectSchemaLink(root, SchemaLinkDisposition.OCCUPIED, None)
            _record_link(result)
            return result
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link_path)
        result = ProjectSchemaLink(root, SchemaLinkDisposition.CREATED, target)
        _record_link(result)
        return result

    current_target = Path(os.readlink(link_path))
    if not current_target.is_absolute():
        current_target = link_path.parent / current_target
    if current_target.resolve() == target:
        result = ProjectSchemaLink(root, SchemaLinkDisposition.UNCHANGED, target)
        _record_link(result)
        return result

    link_path.unlink()
    os.symlink(target, link_path)
    result = ProjectSchemaLink(root, SchemaLinkDisposition.REPOINTED, target)
    _record_link(result)
    return result


def _ensure_local_exclude(root: Path) -> None:
    repo = Repo(root)
    common_directory = Path(repo.common_dir).resolve()
    exclude_path = common_directory / _LOCAL_EXCLUDE_DIRECTORY / _LOCAL_EXCLUDE_FILENAME
    content = exclude_path.read_text(encoding=_UTF8) if exclude_path.exists() else ""
    existing_patterns = set(content.splitlines())
    missing_patterns = tuple(pattern for pattern in _LOCAL_EXCLUDE_PATTERNS if pattern not in existing_patterns)
    if not missing_patterns:
        return
    prefix = content if not content or content.endswith(_NEWLINE) else content + _NEWLINE
    exclude_path.write_text(prefix + _NEWLINE.join(missing_patterns) + _NEWLINE, encoding=_UTF8)


def _record_link(result: ProjectSchemaLink) -> None:
    logger.info(
        _LINK_EVENT,
        project_root=str(result.root),
        disposition=result.disposition,
        resolved_target=str(result.resolved_target) if result.resolved_target is not None else None,
    )


def remove_stray_schema_copy(root: Path) -> SchemaCopyDisposition:
    """Remove only an untracked directory containing exclusively generated schemas."""
    schema_directory = root / _PROJECT_SCHEMA_DIRECTORY
    if not schema_directory.exists() and not schema_directory.is_symlink():
        return SchemaCopyDisposition.ABSENT
    if schema_directory.is_symlink() or not schema_directory.is_dir():
        return SchemaCopyDisposition.RETAINED_FOREIGN

    entries = tuple(schema_directory.iterdir())
    generated_files = tuple(
        entry
        for entry in entries
        if entry.name in _KNOWN_SCHEMA_FILENAMES and entry.is_file() and not entry.is_symlink()
    )
    if not generated_files:
        return SchemaCopyDisposition.ABSENT
    if len(generated_files) != len(entries):
        return SchemaCopyDisposition.RETAINED_FOREIGN

    repo = Repo(root)
    tracked = repo.git.ls_files("--", _PROJECT_SCHEMA_DIRECTORY).strip()
    if tracked:
        return SchemaCopyDisposition.RETAINED_TRACKED

    for entry in generated_files:
        entry.unlink()
    schema_directory.rmdir()
    return SchemaCopyDisposition.REMOVED


def run_schema_publication() -> int:
    """Publish schemas into the active machine home, report the result, and answer the exit code."""
    try:
        result = publish_config_schemas()
    except SchemaPublicationConflict as error:
        print(str(error))
        return _FAILED_EXIT_CODE
    print(
        _PUBLICATION_SUMMARY.format(
            target=result.target,
            written=", ".join(result.written),
            unchanged=", ".join(result.unchanged),
        ),
    )
    return _SUCCEEDED_EXIT_CODE


def main() -> None:
    """Publish schemas into the active machine home and report the result."""
    exit_code = run_schema_publication()
    if exit_code != _SUCCEEDED_EXIT_CODE:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
