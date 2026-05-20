//! Shared fixtures for the workflow integration test suite.
//!
//! Tests use `sqlx::test` to get a fresh Postgres database per test, run
//! the `workflow` migrations against it, and pair the resulting `PgPool`
//! with an in-memory [`VecSink`] so they can assert on emitted envelopes
//! without a running Redis.

#![allow(dead_code)]

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use event_bus::{EventBusError, EventEnvelope};
use identity::{Principal, Role};
use shared::ProjectId;
use sqlx::PgPool;
use workflow::{EventSink, WorkflowService};

pub const HUMAN_PRINCIPAL_EMAIL: &str = "owner@example.com";
pub const TEST_PROJECT_ROOT: &str = "/tmp/test";

/// In-memory event sink used by the integration suite.
///
/// Captures every emitted envelope in insertion order. Cheap to clone via
/// `Arc`; the inner `Mutex` is uncontested because the suite is async but
/// single-threaded per test.
pub struct VecSink {
    pub envelopes: Mutex<Vec<EventEnvelope>>,
}

impl VecSink {
    /// Construct a new sink wrapped in `Arc<dyn EventSink>` suitable for
    /// passing to [`WorkflowService::new`].
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            envelopes: Mutex::new(Vec::new()),
        })
    }

    /// Drain and return every captured envelope.
    pub fn take(&self) -> Vec<EventEnvelope> {
        std::mem::take(&mut *self.envelopes.lock().expect("sink mutex poisoned"))
    }

    /// Borrow a snapshot of captured envelopes.
    pub fn snapshot(&self) -> Vec<EventEnvelope> {
        self.envelopes.lock().expect("sink mutex poisoned").clone()
    }

    /// Number of envelopes currently captured.
    pub fn count(&self) -> usize {
        self.envelopes.lock().expect("sink mutex poisoned").len()
    }
}

#[async_trait]
impl EventSink for VecSink {
    async fn emit(&self, envelope: &EventEnvelope) -> Result<(), EventBusError> {
        self.envelopes
            .lock()
            .expect("sink mutex poisoned")
            .push(envelope.clone());
        Ok(())
    }
}

/// Build a fresh `WorkflowService` wired to `pool` and a fresh `VecSink`.
pub fn build_service(pool: PgPool) -> (WorkflowService, Arc<VecSink>) {
    let sink = VecSink::new();
    let service = WorkflowService::new(pool, sink.clone() as Arc<dyn EventSink>);
    (service, sink)
}

/// Create a unique project for the running test and return its id.
///
/// Names are derived from `nanoid`-style randomness via `uuid::Uuid::new_v4`
/// so two tests in the same DB never collide on the `(name)` unique index.
pub async fn seed_project(svc: &WorkflowService) -> ProjectId {
    let name = format!("test-{}", uuid::Uuid::new_v4());
    svc.find_or_create_project(&name, TEST_PROJECT_ROOT)
        .await
        .expect("project upsert succeeds")
}

/// Owner principal used by every test that needs an actor identity.
pub fn human_principal() -> Principal {
    Principal::Human {
        email: HUMAN_PRINCIPAL_EMAIL.to_owned(),
        role: Role::Owner,
    }
}

/// Canonical input artifact body used by tests that don't care what the
/// content is — only that `create_todo`'s RV2 invariant (non-empty input)
/// is satisfied.
pub fn test_input() -> String {
    "## Test input\n\nSeeded by the workflow integration suite.\n".to_owned()
}
