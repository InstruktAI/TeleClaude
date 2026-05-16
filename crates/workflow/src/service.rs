//! `WorkflowService` — the v2 workflow service composition root.
//!
//! Composes the primitive crates ([`storage::PgPool`], [`event_bus::EventBus`],
//! [`identity::Principal`]) with the workflow domain models, event payloads,
//! and lifecycle state machine into a single behavior aggregator. F1's CLI
//! and any future HTTP transport call this struct's methods rather than
//! talking to Postgres or Redis directly.
//!
//! ## Topic split
//!
//! The public surface is large; methods are organized by topic into private
//! submodules:
//!
//! * [`todos`]      — todo CRUD
//! * [`roadmap`]    — roadmap reordering, freeze/unfreeze, delivery
//! * [`artifacts`]  — versioned artifact read/write/remove
//! * [`transitions`] — lifecycle phase advancement (state-machine driven)
//!
//! Each topic adds methods via `impl WorkflowService { … }` blocks against
//! the struct declared here.
//!
//! ## Event semantics
//!
//! Every mutation follows the **commit-then-emit** pattern:
//!
//! 1. Begin a transaction.
//! 2. Apply the DB change.
//! 3. For lifecycle transitions, append to `workflow.state_transitions`.
//! 4. Build the typed payload from `crate::events`.
//! 5. Commit.
//! 6. Emit the envelope via the [`EventSink`].
//!
//! Step 6 is **at-most-once**: if the emit fails the DB change is not rolled
//! back. The failure is logged at WARN with the envelope's idempotency key
//! so a subscriber gap can be reconciled later. The rationale is that the
//! durable source of truth is Postgres; the bus carries notifications. A
//! lost notification is preferable to a phantom event that did not happen.
//!
//! ## Project resolution
//!
//! v1 had no explicit projects table — context was implicit per `todos.db`
//! path. v2 makes projects first-class. [`WorkflowService::find_or_create_project`]
//! upserts on `(name)` and is the single entry point CLI callers use to
//! resolve a [`ProjectId`] before any todo/roadmap/artifact call.

use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use event_bus::{EventBus, EventBusError, EventEnvelope};
use identity::Principal;
use serde::Serialize;
use shared::ProjectId;
use sqlx::PgPool;
use uuid::Uuid;

use crate::errors::WorkflowError;

pub mod artifacts;
pub mod roadmap;
pub mod todos;
pub mod transitions;

pub use todos::TodoPatch;

/// Pluggable sink for [`EventEnvelope`] emission.
///
/// Production binds this to [`EventBus`]; tests bind it to an in-memory
/// capture so they can assert on emitted envelopes without a running Redis.
#[async_trait]
pub trait EventSink: Send + Sync {
    /// Emit an envelope. The implementation is responsible for any retry
    /// or durability semantics; the service treats this as fire-and-forget
    /// after a successful Postgres commit.
    async fn emit(&self, envelope: &EventEnvelope) -> Result<(), EventBusError>;
}

#[async_trait]
impl EventSink for EventBus {
    async fn emit(&self, envelope: &EventEnvelope) -> Result<(), EventBusError> {
        EventBus::emit(self, envelope).await
    }
}

/// Service that owns every mutation against the `workflow` Postgres schema
/// and the workflow event surface on Redis.
///
/// Cheap to construct, cheap to clone via [`Arc`]; the embedded `PgPool`
/// and event sink are themselves connection managers and may be shared
/// across tasks.
pub struct WorkflowService {
    pool: PgPool,
    events: Arc<dyn EventSink>,
}

impl WorkflowService {
    /// Build a service from a connected pool and an event sink.
    ///
    /// Production callers pass an `Arc<EventBus>`; tests pass an in-memory
    /// capture implementation.
    pub fn new(pool: PgPool, events: Arc<dyn EventSink>) -> Self {
        Self { pool, events }
    }

    /// Borrow the underlying pool. Useful for tests and for callers that
    /// need to run read-only queries outside the service surface.
    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    /// Find or create a project by name.
    ///
    /// Upserts on the `(name)` unique index. The `root_path` is updated on
    /// every call so a moved project root is reflected without a separate
    /// migration step. Returns the project's stable [`ProjectId`].
    pub async fn find_or_create_project(
        &self,
        name: &str,
        root_path: &str,
    ) -> Result<ProjectId, WorkflowError> {
        let row: (ProjectId,) = sqlx::query_as(
            "insert into workflow.projects (name, root_path)
             values ($1, $2)
             on conflict (name) do update set root_path = excluded.root_path
             returning id",
        )
        .bind(name)
        .bind(root_path)
        .fetch_one(&self.pool)
        .await?;
        Ok(row.0)
    }

    /// Build and publish an event envelope after a successful commit.
    ///
    /// At-most-once: a failure to publish is logged at WARN and **not**
    /// surfaced to the caller — the Postgres mutation has already committed
    /// and the lost notification will be reconciled by a future read.
    pub(crate) async fn publish<P: Serialize>(
        &self,
        channel: &str,
        payload: &P,
        principal: &Principal,
    ) -> Result<(), WorkflowError> {
        let envelope = EventEnvelope {
            channel: channel.to_owned(),
            idempotency_key: Uuid::new_v4().to_string(),
            emitted_at: Utc::now(),
            principal: Some(principal.clone()),
            payload: serde_json::to_value(payload)?,
        };
        if let Err(err) = self.events.emit(&envelope).await {
            tracing::error!(
                channel = channel,
                idempotency_key = %envelope.idempotency_key,
                error = ?err,
                "workflow event emit failed after commit; surfacing to caller",
            );
            return Err(WorkflowError::EventEmitAfterCommit {
                channel: channel.to_owned(),
                idempotency_key: envelope.idempotency_key,
                source: err,
            });
        }
        Ok(())
    }
}
