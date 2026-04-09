"""SQLModel table definitions for todos.db."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, String, Text, text
from sqlmodel import Field, SQLModel


class TodoRoadmap(SQLModel, table=True):
    """Roadmap entry persisted in todos.db."""

    __tablename__ = "roadmap"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    slug: str
    position: int
    group_slug: str | None = None
    description: str | None = None
    status: str = "active"
    delivered_at: str | None = None
    delivered_commit: str | None = None
    children: str | None = None
    created_at: str
    updated_at: str


class TodoStateModel(SQLModel, table=True):
    """State blob for a todo."""

    __tablename__ = "todo_state"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    id: str = Field(
        sa_column=Column(
            "id",
            String,
            ForeignKey("roadmap.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    slug: str
    state: str
    created_at: str
    updated_at: str


class TodoArtifact(SQLModel, table=True):
    """Current artifact contents for a todo."""

    __tablename__ = "todo_artifacts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    id: str = Field(
        sa_column=Column(
            "id",
            String,
            ForeignKey("roadmap.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    slug: str
    name: str = Field(primary_key=True)
    content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    digest: str = Field(default="")
    updated_by: str | None = None
    updated_at: str | None = None


class TodoArtifactVersion(SQLModel, table=True):
    """Historical artifact snapshot."""

    __tablename__ = "todo_artifact_versions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    version_id: int | None = Field(default=None, primary_key=True)
    id: str = Field(
        sa_column=Column(
            "id",
            String,
            ForeignKey("roadmap.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    slug: str
    name: str
    content: str = Field(sa_column=Column(Text, nullable=False))
    digest: str
    updated_by: str | None = None
    created_at: str


class RoadmapDep(SQLModel, table=True):
    """Dependency edge between roadmap slugs."""

    __tablename__ = "roadmap_deps"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    slug: str = Field(primary_key=True)
    depends_on: str = Field(primary_key=True)


Index(
    "idx_roadmap_slug_active",
    TodoRoadmap.slug,
    unique=True,
    sqlite_where=text("status IN ('active', 'icebox')"),
)
Index("idx_av_id_name", TodoArtifactVersion.id, TodoArtifactVersion.name, TodoArtifactVersion.created_at)

ROADMAP_TABLE = SQLModel.metadata.tables["roadmap"]
TODO_STATE_TABLE = SQLModel.metadata.tables["todo_state"]
TODO_ARTIFACT_TABLE = SQLModel.metadata.tables["todo_artifacts"]
TODO_ARTIFACT_VERSION_TABLE = SQLModel.metadata.tables["todo_artifact_versions"]
ROADMAP_DEPS_TABLE = SQLModel.metadata.tables["roadmap_deps"]

TODOS_DB_TABLES = [
    ROADMAP_TABLE,
    TODO_STATE_TABLE,
    TODO_ARTIFACT_TABLE,
    TODO_ARTIFACT_VERSION_TABLE,
    ROADMAP_DEPS_TABLE,
]


__all__ = [
    "ROADMAP_DEPS_TABLE",
    "ROADMAP_TABLE",
    "TODOS_DB_TABLES",
    "TODO_ARTIFACT_TABLE",
    "TODO_ARTIFACT_VERSION_TABLE",
    "TODO_STATE_TABLE",
    "RoadmapDep",
    "TodoArtifact",
    "TodoArtifactVersion",
    "TodoRoadmap",
    "TodoStateModel",
]
