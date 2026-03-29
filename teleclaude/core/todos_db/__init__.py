"""Todo lifecycle database — state, artifacts, and roadmap.

Replaces filesystem-based state.yaml, roadmap.yaml, delivered.yaml,
and todos/{slug}/*.md artifact files with a single SQLite store.
"""

from __future__ import annotations

from ._artifacts import TodosDbArtifactsMixin
from ._base import TodosDbBase
from ._roadmap import TodosDbRoadmapMixin
from ._rows import ArtifactVersionRow, RoadmapRow
from ._state import TodosDbStateMixin


class TodosDb(
    TodosDbArtifactsMixin,
    TodosDbRoadmapMixin,
    TodosDbStateMixin,
    TodosDbBase,
):
    """Database interface for todo lifecycle state and artifacts."""


__all__ = ["ArtifactVersionRow", "RoadmapRow", "TodosDb"]
