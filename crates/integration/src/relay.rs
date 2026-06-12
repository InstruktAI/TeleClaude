//! Stateless relay for verified inbound events.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use chrono::Utc;
use event_bus::{envelope::ENVELOPE_SCHEMA_VERSION, EventBus, EventEnvelope, EventScope};
use serde_json::json;

use crate::errors::IntegrationError;
use crate::provider::NormalizedEvent;

/// Cluster event channel for verified inbound external events.
pub const INTEGRATION_INBOX_RECEIVED: &str = "integration.inbox.received";

/// Async relay target for verified provider events.
pub trait VerifiedEventRelay: Send + Sync {
    fn relay<'a>(
        &'a self,
        event: NormalizedEvent,
    ) -> Pin<Box<dyn Future<Output = Result<EventEnvelope, IntegrationError>> + Send + 'a>>;
}

/// EventBus-backed relay target.
pub struct EventBusRelay {
    event_bus: Arc<EventBus>,
}

impl EventBusRelay {
    pub fn new(event_bus: Arc<EventBus>) -> Self {
        Self { event_bus }
    }
}

impl VerifiedEventRelay for EventBusRelay {
    fn relay<'a>(
        &'a self,
        event: NormalizedEvent,
    ) -> Pin<Box<dyn Future<Output = Result<EventEnvelope, IntegrationError>> + Send + 'a>> {
        Box::pin(async move { relay_verified_event(self.event_bus.as_ref(), event).await })
    }
}

/// Emit a verified provider event onto the cluster bus.
pub async fn relay_verified_event(
    event_bus: &EventBus,
    event: NormalizedEvent,
) -> Result<EventEnvelope, IntegrationError> {
    let emitted_at = Utc::now();
    let delivery_id = event.delivery_id;
    let envelope = EventEnvelope {
        schema_version: ENVELOPE_SCHEMA_VERSION,
        scope: EventScope::Cluster,
        channel: INTEGRATION_INBOX_RECEIVED.to_string(),
        idempotency_key: delivery_id.clone(),
        emitted_at,
        principal: None,
        payload: json!({
            "entry_id": delivery_id.clone(),
            "provider": event.provider,
            "event_name": event.event_name,
            "payload": event.payload,
            "properties": event.properties,
            "received_at": emitted_at,
            "verified": true,
            "idempotency_key": delivery_id,
        }),
    };

    event_bus.emit(&envelope).await?;
    Ok(envelope)
}
