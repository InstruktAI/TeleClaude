"""Forward migration for the declarative scheduled-job configuration shape."""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from teleclaude.config._file_io import file_transaction
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.schema import ConfigKind

_JOBS_KEY: Final = "jobs"
_AGENT_KEY: Final = "agent"
_LEGACY_FIELDS: Final = frozenset(
    {"type", "message", "schedule", "preferred_hour", "preferred_weekday", "preferred_day"}
)
_UTF8: Final = "utf-8"


def migrate_jobs_config(path: Path, kind: ConfigKind) -> None:
    """Convert name-keyed jobs and scalar candidates before strict validation."""
    with file_transaction(path) as transaction:
        document = _load_document(transaction.read_text(encoding=_UTF8))
        if document is None or not _migrate_document(document):
            return
        rendered = render_declared_config(kind, document)
        transaction.replace_text(rendered, encoding=_UTF8)


def _load_document(content: str) -> CommentedMap | None:
    parser = YAML(typ="rt")
    parsed = parser.load(content)
    return parsed if isinstance(parsed, CommentedMap) else None


def _migrate_document(document: CommentedMap) -> bool:
    raw_jobs = document.get(_JOBS_KEY)
    if raw_jobs is None:
        return False
    if isinstance(raw_jobs, CommentedSeq):
        return _migrate_entries(raw_jobs)
    if not isinstance(raw_jobs, CommentedMap):
        return False
    entries = CommentedSeq()
    for declaration in raw_jobs.values():
        if not isinstance(declaration, CommentedMap):
            raise ValueError("legacy job declarations must be mappings")
        entries.append(declaration)
    document[_JOBS_KEY] = entries
    return _migrate_entries(entries) or True


def _migrate_entries(entries: CommentedSeq) -> bool:
    changed = False
    for declaration in entries:
        if not isinstance(declaration, MutableMapping):
            raise ValueError("job declarations must be mappings")
        for field in _LEGACY_FIELDS:
            if field in declaration:
                del declaration[field]
                changed = True
        candidate = declaration.get(_AGENT_KEY)
        if isinstance(candidate, str):
            declaration[_AGENT_KEY] = CommentedSeq([candidate])
            changed = True
    return changed
