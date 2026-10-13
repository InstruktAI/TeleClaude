"""Declared-file writing for the same-named configuration tiers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any, Final

from ruamel.yaml import YAML

from teleclaude.config.field_constraints import refuse_document
from teleclaude.config.schema import CURRENT_SCHEMA_VERSION, TIER_DOCUMENT_MODELS, ConfigKind
from teleclaude.file_transaction import file_transaction

HOME_SCHEMA_DIRECTORY: Final = "schemas"
PROJECT_SCHEMA_LINK_DIRECTORY: Final = ".teleclaude/schemas"
COMPUTER_SCHEMA_FILENAME: Final = "teleclaude-computer.schema.json"
_SCHEMA_MODELINE_PREFIX: Final = "# yaml-language-server: $schema="
_UTF8: Final = "utf-8"
_NEWLINE: Final = "\n"
_KIND_FIELD: Final = "kind"
_SCHEMA_VERSION_FIELD: Final = "schema_version"
_EMPTY_TEXT: Final = ""
_COMPUTER_SCHEMA_MODELINE: Final = f"{_SCHEMA_MODELINE_PREFIX}{HOME_SCHEMA_DIRECTORY}/{COMPUTER_SCHEMA_FILENAME}"
_SCHEMA_FILENAMES: Final[dict[ConfigKind, str]] = {
    ConfigKind.GLOBAL: "teleclaude-global.schema.json",
    ConfigKind.PROJECT: "teleclaude-project.schema.json",
    ConfigKind.PERSON: "teleclaude-person.schema.json",
    ConfigKind.COMPANY: "teleclaude-company.schema.json",
}
_SCHEMA_REFERENCES: Final[dict[ConfigKind, str]] = {
    ConfigKind.GLOBAL: f"{HOME_SCHEMA_DIRECTORY}/{_SCHEMA_FILENAMES[ConfigKind.GLOBAL]}",
    ConfigKind.PROJECT: f"{PROJECT_SCHEMA_LINK_DIRECTORY}/{_SCHEMA_FILENAMES[ConfigKind.PROJECT]}",
    ConfigKind.PERSON: f"../../{HOME_SCHEMA_DIRECTORY}/{_SCHEMA_FILENAMES[ConfigKind.PERSON]}",
    ConfigKind.COMPANY: f"../../{HOME_SCHEMA_DIRECTORY}/{_SCHEMA_FILENAMES[ConfigKind.COMPANY]}",
}


def schema_filename(kind: ConfigKind) -> str:
    """Return the published schema filename for one configuration tier."""
    return _SCHEMA_FILENAMES[kind]


def write_declared_config(
    path: Path,
    kind: ConfigKind,
    document: Mapping[str, object],
) -> None:
    """Atomically write a declared configuration document with its tier reference."""
    _atomic_write(path, render_declared_config(kind, document))


def render_declared_config(
    kind: ConfigKind,
    document: Mapping[str, object],
) -> str:
    """Render a declared document for an already-held file transaction.

    Raises ``FieldConstraintRefusal`` before producing output when the document breaks a
    relationship declared on its tier's fields.
    """
    return _render_document(kind, document, _SCHEMA_MODELINE_PREFIX + _SCHEMA_REFERENCES[kind])


def write_yaml_document(path: Path, document: Mapping[str, object]) -> None:
    """Atomically write a YAML document that does not carry a tier declaration."""
    _atomic_write(path, _render_yaml(document, None))


def render_machine_config(document: Mapping[str, object]) -> str:
    """Render stored computer input with exactly one leading editor schema reference."""
    content = _render_yaml(deepcopy(document), None)
    body = _EMPTY_TEXT.join(
        line for line in content.splitlines(keepends=True) if not line.startswith(_SCHEMA_MODELINE_PREFIX)
    )
    return f"{_COMPUTER_SCHEMA_MODELINE}{_NEWLINE}{body}"


def _render_document(kind: ConfigKind, document: Mapping[str, object], modeline: str | None) -> str:
    refuse_document(TIER_DOCUMENT_MODELS[kind], document)
    declared_document: Any = document.copy() if isinstance(document, dict) else dict(document)
    _strip_schema_modelines(declared_document)
    declared_document[_KIND_FIELD] = kind.value
    # A document keeps the version it carries; a candidate without one takes the current declaration.
    declared_document.setdefault(_SCHEMA_VERSION_FIELD, CURRENT_SCHEMA_VERSION)
    return _render_yaml(declared_document, modeline)


def _strip_schema_modelines(document: Any) -> None:
    """Remove retained round-trip modelines before rendering the canonical one."""
    comments = getattr(getattr(document, "ca", None), "comment", None)
    if not isinstance(comments, list):
        return
    for index, source in enumerate(comments):
        if isinstance(source, list):
            comments[index] = [
                token
                for token in source
                if not str(getattr(token, "value", "")).lstrip().startswith(_SCHEMA_MODELINE_PREFIX)
            ]
        elif str(getattr(source, "value", "")).lstrip().startswith(_SCHEMA_MODELINE_PREFIX):
            comments[index] = None


def _render_yaml(document: Mapping[str, object], modeline: str | None) -> str:
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.default_flow_style = False
    yaml_rt.representer.add_multi_representer(Enum, _represent_enum)
    buffer = StringIO()
    yaml_rt.dump(document, buffer)
    prefix = f"{modeline}{_NEWLINE}" if modeline is not None else _EMPTY_TEXT
    return f"{prefix}{buffer.getvalue()}"


def _represent_enum(representer: Any, data: Enum) -> Any:
    """Serialize Enum values as their YAML-safe primitive representation."""
    return representer.represent_data(data.value)


def _atomic_write(path: Path, content: str) -> None:
    with file_transaction(path) as transaction:
        transaction.replace_text(content, encoding=_UTF8)
