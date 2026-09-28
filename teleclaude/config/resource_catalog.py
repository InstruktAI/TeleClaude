"""Enumerate configuration subjects and read raw registry documents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.loader import list_company_config_paths
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import GLOBAL_CONFIG_PATH
from teleclaude.services.project_catalog import get_project_catalog_service

_PEOPLE_KEY = "people"
_SLUG_KEY = "slug"
_DOCUMENT_MAPPING_ERROR = "Configuration document must be a mapping: {path}"
_PEOPLE_LIST_ERROR = "Global configuration `people` must be a list, found {type}"


def load_mapping(content: str, path: Path) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Parse a round-trip document, rejecting a non-mapping body."""
    document = round_trip_yaml().load(content) if content else {}
    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise ValueError(_DOCUMENT_MAPPING_ERROR.format(path=path))
    return {str(key): value for key, value in document.items()}


def raw_people(global_raw: Mapping[str, object]) -> list[object]:
    """Return the raw people list, distinguishing absent from malformed."""
    if _PEOPLE_KEY not in global_raw:
        return []
    people = global_raw[_PEOPLE_KEY]
    if not isinstance(people, list):
        raise ValueError(_PEOPLE_LIST_ERROR.format(type=type(people).__name__))
    return list(people)


def _list_computer() -> list[SubjectRef]:
    return [SubjectRef(ConfigSubjectKind.COMPUTER)]


def _list_global() -> list[SubjectRef]:
    return [SubjectRef(ConfigSubjectKind.GLOBAL)]


def _list_person() -> list[SubjectRef]:
    with file_transaction(GLOBAL_CONFIG_PATH) as transaction:
        raw = load_mapping(transaction.read_text(), GLOBAL_CONFIG_PATH)
    return [
        SubjectRef(ConfigSubjectKind.PERSON, str(entry[_SLUG_KEY]))
        for entry in raw_people(raw)
        if isinstance(entry, dict) and entry.get(_SLUG_KEY)
    ]


def _list_company() -> list[SubjectRef]:
    return [SubjectRef(ConfigSubjectKind.COMPANY, path.parent.name) for path in list_company_config_paths()]


def _list_project() -> list[SubjectRef]:
    return [SubjectRef(ConfigSubjectKind.PROJECT, node.slug) for node in get_project_catalog_service().list_projects()]


_LIST_SUBJECTS: dict[ConfigSubjectKind, Callable[[], list[SubjectRef]]] = {
    ConfigSubjectKind.COMPUTER: _list_computer,
    ConfigSubjectKind.GLOBAL: _list_global,
    ConfigSubjectKind.PERSON: _list_person,
    ConfigSubjectKind.COMPANY: _list_company,
    ConfigSubjectKind.PROJECT: _list_project,
}


def list_subjects(kind: ConfigSubjectKind) -> list[SubjectRef]:
    """List every addressable subject of one kind."""
    return _LIST_SUBJECTS[kind]()
