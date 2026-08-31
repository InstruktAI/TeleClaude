"""Declared-file writing for the same-named configuration tiers."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Mapping
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any, Final

from ruamel.yaml import YAML

from teleclaude.config.schema import ConfigKind

_SCHEMA_DIRECTORY: Final = "schemas"
_SCHEMA_MODELINE_PREFIX: Final = "# yaml-language-server: $schema="
_UTF8: Final = "utf-8"
_NEWLINE: Final = "\n"
_KIND_FIELD: Final = "kind"
_LOCK_SUFFIX: Final = ".lock"
_TEMPORARY_SUFFIX: Final = ".tmp"
_WRITE_MODE: Final = "w"
_READ_WRITE_MODE: Final = "r+"
_EMPTY_TEXT: Final = ""
_SCHEMA_FILENAMES: Final[dict[ConfigKind, str]] = {
    ConfigKind.GLOBAL: "teleclaude-global.schema.json",
    ConfigKind.PROJECT: "teleclaude-project.schema.json",
    ConfigKind.PERSON: "teleclaude-person.schema.json",
    ConfigKind.COMPANY: "teleclaude-company.schema.json",
}


def schema_filename(kind: ConfigKind) -> str:
    """Return the published schema filename for one configuration tier."""
    return _SCHEMA_FILENAMES[kind]


def write_declared_config(
    path: Path,
    kind: ConfigKind,
    document: Mapping[str, object],
    *,
    schema_root: Path,
) -> None:
    """Atomically write a declared configuration document and available modeline."""
    schema_path = schema_root / _SCHEMA_DIRECTORY / schema_filename(kind)
    modeline = _schema_modeline(path, schema_path)
    rendered = _render_document(kind, document, modeline)
    _atomic_write(path, rendered)


def write_yaml_document(path: Path, document: Mapping[str, object]) -> None:
    """Atomically write a YAML document that does not carry a tier declaration."""
    _atomic_write(path, _render_yaml(document, None))


def _schema_modeline(config_path: Path, schema_path: Path) -> str | None:
    if not schema_path.is_file():
        return None
    relative_schema_path = os.path.relpath(schema_path, config_path.parent)
    return f"{_SCHEMA_MODELINE_PREFIX}{relative_schema_path}"


def _render_document(kind: ConfigKind, document: Mapping[str, object], modeline: str | None) -> str:
    declared_document = {
        _KIND_FIELD: kind.value,
        **{key: value for key, value in document.items() if key != _KIND_FIELD},
    }
    return _render_yaml(declared_document, modeline)


def _render_yaml(document: Mapping[str, object], modeline: str | None) -> str:
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.default_flow_style = False
    yaml_rt.representer.add_multi_representer(Enum, _represent_enum)
    buffer = StringIO()
    yaml_rt.dump(dict(document), buffer)
    prefix = f"{modeline}{_NEWLINE}" if modeline is not None else _EMPTY_TEXT
    return f"{prefix}{buffer.getvalue()}"


def _represent_enum(representer: Any, data: Enum) -> Any:
    """Serialize Enum values as their YAML-safe primitive representation."""
    return representer.represent_data(data.value)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(_LOCK_SUFFIX)
    temporary_path = path.with_suffix(_TEMPORARY_SUFFIX)
    with open(lock_path, _WRITE_MODE, encoding=_UTF8) as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass

        try:
            temporary_path.write_text(content, encoding=_UTF8)
            with open(temporary_path, _READ_WRITE_MODE, encoding=_UTF8) as temporary_file:
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path.exists():
                temporary_path.unlink()
            raise
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass
