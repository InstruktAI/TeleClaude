//! Workflow error types.
//!
//! Every public surface in the `workflow` crate fails with `WorkflowError`.
//! Variants are typed so consumers can pattern-match. Storage, event-bus,
//! sqlx, and serde failures are wrapped via `#[from]` so call sites can
//! propagate with `?`.

use shared::Slug;

use crate::models::{ArtifactName, LifecyclePhase};

/// Errors returned by `workflow` service operations.
#[derive(Debug, thiserror::Error)]
pub enum WorkflowError {
    /// No todo matches the given slug.
    #[error("todo not found: slug={0}")]
    TodoNotFound(Slug),

    /// No roadmap entry matches the given slug.
    #[error("roadmap entry not found: slug={0}")]
    RoadmapEntryNotFound(Slug),

    /// A todo or roadmap entry with this slug already exists in the project.
    #[error("duplicate slug: {0}")]
    DuplicateSlug(Slug),

    /// `move_roadmap_entry` requires exactly one of `--before` or `--after`.
    #[error("move requires exactly one of before/after; got before={before} after={after}")]
    RoadmapMoveArguments { before: bool, after: bool },

    /// `create_todo` was invoked without an input artifact. v2 enforces that
    /// every todo starts life with a justified `PrdDrafting` phase backed by
    /// an `input` artifact (RV2 from the v2-mvp-bootstrap review).
    #[error("create_todo requires a non-empty input artifact")]
    EmptyInputArtifact,

    /// The update request tried to encode structured mutations as a JSON/YAML
    /// patch body instead of using typed update arguments.
    #[error("todo update refuses patch blobs; use typed update arguments")]
    PatchBlobRejected,

    /// The update request supplied mutually exclusive content routing flags.
    #[error("ambiguous todo update content routing")]
    AmbiguousTodoUpdate,

    /// Prepped update fast-paths require a human principal.
    #[error("prepped todo update requires a human principal")]
    PreppedUpdateRequiresHuman,

    /// The named artifact is retired for writes.
    #[error("artifact is retired for writes: name={name:?}")]
    RetiredArtifactWrite { name: ArtifactName },

    /// Kind can only be changed while the todo is still in the prepare stage.
    #[error("kind update is not compatible with phase {phase:?} for slug {slug}: kind={kind:?}")]
    KindUpdatePhaseMismatch {
        slug: Slug,
        phase: LifecyclePhase,
        kind: crate::models::TodoKind,
    },

    /// Rename requires distinct old/new slugs.
    #[error("todo rename requires distinct slugs: {slug}")]
    TodoRenameNoop { slug: Slug },

    /// The target slug is already owned by a non-removed roadmap entry.
    #[error("todo rename target slug is already held: {slug}")]
    TodoRenameCollision { slug: Slug },

    /// Delivered todos are historical records and cannot be re-keyed.
    #[error("delivered todo cannot be renamed: {slug}")]
    TodoRenameDelivered { slug: Slug },

    /// A snippet body contains the slug outside managed frontmatter.
    #[error("todo rename found unsafe snippet reference in {path}: slug={slug}")]
    TodoRenameUnsafeReference { path: String, slug: Slug },

    /// A non-terminal daemon operation still binds the source slug.
    #[error("todo rename blocked by non-terminal operation {operation_id}: slug={slug}")]
    TodoRenameOperationBound { slug: Slug, operation_id: String },

    /// An open daemon session still binds the source slug.
    #[error("todo rename blocked by open session {session_id}: slug={slug}")]
    TodoRenameSessionBound { slug: Slug, session_id: String },

    /// A project-local filesystem or git destination already exists.
    #[error("todo rename target surface already exists: surface={surface} target={target}")]
    TodoRenameSurfaceCollision { surface: String, target: String },

    /// The named artifact is not attached to the referenced todo.
    #[error("artifact not found for todo {todo}: name={name:?}")]
    ArtifactNotFound { todo: Slug, name: ArtifactName },

    /// No artifact version has the requested digest.
    #[error("artifact version not found for todo {todo}: name={name:?} digest={digest}")]
    ArtifactVersionNotFound {
        todo: Slug,
        name: ArtifactName,
        digest: String,
    },

    /// The requested lifecycle transition is not legal under the state
    /// machine.
    #[error("invalid lifecycle transition: from={from:?} to={to:?}")]
    InvalidTransition {
        from: LifecyclePhase,
        to: LifecyclePhase,
    },

    /// Underlying Postgres pool or migration failure surfaced by `storage`.
    #[error("storage error: {0}")]
    Storage(#[from] storage::StorageError),

    /// Underlying Redis pub/sub or stream failure surfaced by `event-bus`.
    #[error("event bus error: {0}")]
    EventBus(#[from] event_bus::EventBusError),

    /// Event emission failed *after* the database mutation had already
    /// committed. The DB state is durable but subscribers will not see the
    /// notification. Surfaced loud rather than swallowed so callers can
    /// reconcile (retry the emit, fire a manual refresh, log a SEV, etc.).
    /// Replaces the silent at-most-once WARN that the reviewer flagged as
    /// Critical-1.
    #[error(
        "event emit failed after commit on {channel} (idempotency_key={idempotency_key}): {source}"
    )]
    EventEmitAfterCommit {
        channel: String,
        idempotency_key: String,
        #[source]
        source: event_bus::EventBusError,
    },

    /// JSON (de)serialization failed while reading or writing a payload.
    #[error("serialization error: {0}")]
    Serde(#[from] serde_json::Error),

    /// Filesystem operation failed while mutating project-local workflow data.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    /// Git repository operation failed while mutating project-local workflow data.
    #[error("git error: {0}")]
    Git(#[from] git2::Error),

    /// A git CLI operation failed where the native Rust binding does not expose
    /// the required porcelain-equivalent behavior.
    #[error("git command failed: {command}: {stderr}")]
    GitCommand { command: String, stderr: String },

    /// Daemon SQLite reconciliation failed.
    #[error("daemon database error: {0}")]
    DaemonDb(String),

    /// A direct sqlx call (query, fetch, transaction) failed.
    #[error("database error: {0}")]
    Db(#[from] sqlx::Error),
}
