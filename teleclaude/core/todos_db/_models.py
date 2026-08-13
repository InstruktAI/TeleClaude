"""SQLModel table definitions for todos.db."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Text, text
from sqlmodel import Field, SQLModel


class Todo(SQLModel, table=True):
    """Todo entry persisted in todos.db."""

    __tablename__ = "todo"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    slug: str
    ready_since: str | None = Field(default=None)
    schedule: str | None = Field(default=None)
    # The row this todo was grouped under, keyed by durable id — never by name.
    # Set once at grouping and never re-homed. The referenced row transitions to
    # `status="holder"` in the same transaction; see TodoStatus.HOLDER.
    group_id: str | None = Field(default=None, sa_column=Column(String, ForeignKey("todo.id"), nullable=True))
    description: str | None = None
    status: str = "active"
    delivered_at: str | None = None
    delivered_commit: str | None = None
    children: str | None = None
    # The Creation Record — how this todo came into existence. Stamped once at
    # creation, immutable thereafter, audit-only (never widens authorization).
    # `lineage` is the complete creation chain in one value: `<root>` or
    # `<root>>session:<session_id>` (see teleclaude.types.creation_record.Lineage).
    # Total by contract for a todo created after this column existed; a legacy
    # pre-migration row may still carry NULL until the backfill task runs.
    lineage: str | None = Field(default=None)
    # The creation door, stamped by the door itself: tui | cli | web | agent | split.
    entry_point: str | None = Field(default=None)
    # Derived true for the human doors; declared by the filing agent for the
    # agent door (default false — a forgotten flag lands in the audit bucket).
    # `server_default` matters: raw-SQL inserts (the legacy markdown importer)
    # bypass the ORM's Python-side default and rely on the DDL default.
    human_involved: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=text("0")))
    # Door-specific reference data, never identity: the parent todo slug for
    # the split door; absent otherwise.
    context: str | None = Field(default=None)
    # Soft-delete tombstone. Set only while status == 'removed'; cleared on
    # reactivation. removed_deps is the row-id-keyed JSON snapshot of the
    # entry's outgoing dependency slugs (same TEXT/JSON convention as children),
    # captured at soft-remove and replayed on reactivation.
    removed_at: str | None = None
    prev_status: str | None = None
    removed_deps: str | None = None
    pending_purge_paths: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
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
            ForeignKey("todo.id", ondelete="CASCADE"),
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
            ForeignKey("todo.id", ondelete="CASCADE"),
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
            ForeignKey("todo.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    slug: str
    name: str
    content: str = Field(sa_column=Column(Text, nullable=False))
    digest: str
    updated_by: str | None = None
    created_at: str


class TodoDep(SQLModel, table=True):
    """Dependency edge between todo slugs."""

    __tablename__ = "todo_deps"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    slug: str = Field(primary_key=True)
    depends_on: str = Field(primary_key=True)


class TodoDispatchClaim(SQLModel, table=True):
    """Short-lived lifecycle runner dispatch claim."""

    __tablename__ = "todo_dispatch_claims"  # pyright: ignore[reportAssignmentType]
    __table_args__ = {"extend_existing": True}

    slug: str = Field(primary_key=True)
    lane: str = Field(primary_key=True)
    owner: str
    claimed_at: str
    expires_at: str


Index(
    "idx_todo_slug_active",
    Todo.slug,
    unique=True,
    sqlite_where=text("status IN ('active', 'icebox', 'holder')"),
)
Index("idx_av_id_name", TodoArtifactVersion.id, TodoArtifactVersion.name, TodoArtifactVersion.created_at)

TODO_TABLE = SQLModel.metadata.tables["todo"]
TODO_STATE_TABLE = SQLModel.metadata.tables["todo_state"]
TODO_ARTIFACT_TABLE = SQLModel.metadata.tables["todo_artifacts"]
TODO_ARTIFACT_VERSION_TABLE = SQLModel.metadata.tables["todo_artifact_versions"]
TODO_DEPS_TABLE = SQLModel.metadata.tables["todo_deps"]
TODO_DISPATCH_CLAIMS_TABLE = SQLModel.metadata.tables["todo_dispatch_claims"]

TODOS_DB_TABLES = [
    TODO_TABLE,
    TODO_STATE_TABLE,
    TODO_ARTIFACT_TABLE,
    TODO_ARTIFACT_VERSION_TABLE,
    TODO_DEPS_TABLE,
    TODO_DISPATCH_CLAIMS_TABLE,
]


__all__ = [
    "TODOS_DB_TABLES",
    "TODO_ARTIFACT_TABLE",
    "TODO_ARTIFACT_VERSION_TABLE",
    "TODO_DEPS_TABLE",
    "TODO_DISPATCH_CLAIMS_TABLE",
    "TODO_STATE_TABLE",
    "TODO_TABLE",
    "Todo",
    "TodoArtifact",
    "TodoArtifactVersion",
    "TodoDep",
    "TodoDispatchClaim",
    "TodoStateModel",
]
