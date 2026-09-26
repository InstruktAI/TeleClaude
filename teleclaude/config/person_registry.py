"""Pure transformations over the raw global document's person registry.

No I/O: callers hold the global file's lock and persist the returned document
through their own commit path.
"""

from __future__ import annotations

import copy
from typing import Any

from teleclaude.config.schema import PersonEntry

_PEOPLE_KEY = "people"
_SLUG_KEY = "slug"


def _raw_people(global_doc: dict[object, object]) -> list[Any]:  # guard: loose-dict - raw YAML config
    """Return the raw `people` list, or an empty list when absent."""
    people = global_doc.get(_PEOPLE_KEY)
    return list(people) if isinstance(people, list) else []


def with_person(
    global_doc: dict[object, object],  # guard: loose-dict - raw YAML config
    entry: PersonEntry,
) -> dict[object, object]:  # guard: loose-dict - raw YAML config
    """Return a new raw global document with `entry` appended to `people`."""
    people = _raw_people(global_doc)
    if any(isinstance(person, dict) and person.get(_SLUG_KEY) == entry.slug for person in people):
        raise ValueError(f"Person with slug '{entry.slug}' already exists")
    candidate = copy.deepcopy(global_doc)
    candidate_people = _raw_people(candidate)
    candidate_people.append(entry.model_dump(mode="json", exclude_defaults=True))
    candidate[_PEOPLE_KEY] = candidate_people
    return candidate


def without_person(
    global_doc: dict[object, object],  # guard: loose-dict - raw YAML config
    slug: str,
) -> dict[object, object]:  # guard: loose-dict - raw YAML config
    """Return a new raw global document with the `slug` entry removed from `people`."""
    people = _raw_people(global_doc)
    if not any(isinstance(person, dict) and person.get(_SLUG_KEY) == slug for person in people):
        raise ValueError(f"Person with slug '{slug}' not found")
    candidate = copy.deepcopy(global_doc)
    candidate_people = _raw_people(candidate)
    candidate[_PEOPLE_KEY] = [
        person for person in candidate_people if not (isinstance(person, dict) and person.get(_SLUG_KEY) == slug)
    ]
    return candidate
