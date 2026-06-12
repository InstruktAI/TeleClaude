use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use event_bus::{envelope::ENVELOPE_SCHEMA_VERSION, EventBus, EventEnvelope, EventScope};
use serde_json::json;
use tokio::sync::Mutex;

use crate::convergence::ConvergenceFailure;
use crate::errors::ReconciliationError;
use crate::policy::TargetVersion;
use crate::runner::DesiredState;

pub const RECONCILIATION_DRIFT_DETECTED: &str = "reconciliation.installation.drift_detected";
pub const RECONCILIATION_CONVERGED: &str = "reconciliation.installation.converged";
pub const RECONCILIATION_FAILED: &str = "reconciliation.convergence.failed";

#[async_trait]
pub trait ReconciliationEventPublisher: Send + Sync {
    async fn publish(&self, envelope: EventEnvelope) -> Result<(), ReconciliationError>;
}

pub struct EventBusPublisher {
    event_bus: Arc<EventBus>,
}

impl EventBusPublisher {
    pub fn new(event_bus: Arc<EventBus>) -> Self {
        Self { event_bus }
    }
}

#[async_trait]
impl ReconciliationEventPublisher for EventBusPublisher {
    async fn publish(&self, envelope: EventEnvelope) -> Result<(), ReconciliationError> {
        self.event_bus.emit(&envelope).await?;
        Ok(())
    }
}

#[derive(Default)]
pub struct MemoryEventPublisher {
    envelopes: Mutex<Vec<EventEnvelope>>,
}

impl MemoryEventPublisher {
    pub fn new() -> Self {
        Self::default()
    }

    pub async fn envelopes(&self) -> Vec<EventEnvelope> {
        self.envelopes.lock().await.clone()
    }
}

#[async_trait]
impl ReconciliationEventPublisher for MemoryEventPublisher {
    async fn publish(&self, envelope: EventEnvelope) -> Result<(), ReconciliationError> {
        self.envelopes.lock().await.push(envelope);
        Ok(())
    }
}

pub fn drift_detected(state: &DesiredState, target: &TargetVersion, reason: &str) -> EventEnvelope {
    envelope(
        RECONCILIATION_DRIFT_DETECTED,
        format!("{}:{}:drift", state.computer, target.as_str()),
        json!({
            "computer": state.computer,
            "channel": state.channel_name(),
            "current_version": state.current_version,
            "desired_version": target,
            "reason": reason,
        }),
    )
}

pub fn converged(
    state: &DesiredState,
    from_version: &str,
    target: &TargetVersion,
) -> EventEnvelope {
    envelope(
        RECONCILIATION_CONVERGED,
        format!("{}:{}:converged", state.computer, target.as_str()),
        json!({
            "computer": state.computer,
            "channel": state.channel_name(),
            "from_version": from_version,
            "to_version": target,
            "converged_at": Utc::now(),
        }),
    )
}

pub fn convergence_failed(failure: &ConvergenceFailure) -> EventEnvelope {
    envelope(
        RECONCILIATION_FAILED,
        format!("{}:{}:failed", failure.run_id, failure.to_version.as_str()),
        json!({
            "computer": failure.computer,
            "run_id": failure.run_id,
            "from_version": failure.from_version,
            "to_version": failure.to_version,
            "failed_step": failure.failed_step,
            "failure_context": failure.failure_context,
        }),
    )
}

fn envelope(
    channel: &'static str,
    idempotency_key: String,
    payload: serde_json::Value,
) -> EventEnvelope {
    EventEnvelope {
        schema_version: ENVELOPE_SCHEMA_VERSION,
        scope: EventScope::Cluster,
        channel: channel.to_string(),
        idempotency_key,
        emitted_at: Utc::now(),
        principal: None,
        payload,
    }
}
