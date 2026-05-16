//! Canonical event envelope.
//!
//! Every event flowing through the bus is wrapped in an `EventEnvelope`. The
//! envelope carries the channel name, an idempotency key for handler-success
//! dedup, the emission timestamp, the principal that triggered the event, and
//! the schema-validated payload.

use chrono::{DateTime, Utc};
use identity::Principal;
use serde::{Deserialize, Serialize};

/// The canonical event envelope.
///
/// See `docs/project/design/architecture-v2/event-bus-transports.md` for the
/// design contract. The bus serializes envelopes to JSON before pushing them
/// onto Redis Streams and pub/sub.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EventEnvelope {
    /// Channel name in `{service}.{aggregate}.{verb_past}` form.
    pub channel: String,
    /// Stable per-logical-event key used for handler-success dedup.
    pub idempotency_key: String,
    /// UTC timestamp at which the envelope was emitted.
    pub emitted_at: DateTime<Utc>,
    /// Principal that triggered the event, if any.
    pub principal: Option<Principal>,
    /// Payload, schema-validated against the emitting service's `events.rs`.
    pub payload: serde_json::Value,
}

#[cfg(test)]
mod tests {
    use super::*;
    use identity::Role;
    use serde_json::json;

    #[test]
    fn envelope_serde_round_trip_preserves_fields() {
        let original = EventEnvelope {
            channel: "workflow.todo.created".to_string(),
            idempotency_key: "todo-42-created".to_string(),
            emitted_at: DateTime::parse_from_rfc3339("2026-05-16T12:00:00Z")
                .expect("static timestamp parses")
                .with_timezone(&Utc),
            principal: Some(Principal::Human {
                email: "owner@example.com".to_string(),
                role: Role::Owner,
            }),
            payload: json!({"slug": "demo", "title": "Demo"}),
        };

        let serialized = serde_json::to_string(&original).expect("envelope serializes");
        let restored: EventEnvelope =
            serde_json::from_str(&serialized).expect("envelope deserializes");

        assert_eq!(restored, original);
    }
}
