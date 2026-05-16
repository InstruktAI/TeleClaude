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

    /// The named artifact is not attached to the referenced todo.
    #[error("artifact not found for todo {todo}: name={name:?}")]
    ArtifactNotFound { todo: Slug, name: ArtifactName },

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

    /// A direct sqlx call (query, fetch, transaction) failed.
    #[error("database error: {0}")]
    Db(#[from] sqlx::Error),
}
