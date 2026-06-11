//! Canonical event envelope.
//!
//! Every event flowing through the bus is wrapped in an `EventEnvelope`. The
//! envelope carries the channel name, an idempotency key for handler-success
//! dedup, the emission timestamp, the principal that triggered the event, and
//! the schema-validated payload.

use chrono::{DateTime, Utc};
use identity::Principal;
use serde::{Deserialize, Serialize};

/// Current JSON envelope schema version.
pub const ENVELOPE_SCHEMA_VERSION: u32 = 1;

fn default_envelope_schema_version() -> u32 {
    ENVELOPE_SCHEMA_VERSION
}

/// Routing scope for an event envelope.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventScope {
    Local,
    Cluster,
    Public,
}

impl Default for EventScope {
    fn default() -> Self {
        Self::Local
    }
}

/// The canonical event envelope.
///
/// See `docs/project/design/architecture-v2/event-bus-transports.md` for the
/// design contract. The bus serializes envelopes to JSON before pushing them
/// onto Redis Streams and pub/sub.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EventEnvelope {
    /// Current shape is v1; absence on decode means a legacy baseline envelope.
    ///
    /// Future non-additive changes must bump [`ENVELOPE_SCHEMA_VERSION`].
    #[serde(default = "default_envelope_schema_version")]
    pub schema_version: u32,
    /// Routing directive that determines which scope carries the event.
    #[serde(default)]
    pub scope: EventScope,
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
            schema_version: ENVELOPE_SCHEMA_VERSION,
            scope: EventScope::Cluster,
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
        assert_eq!(restored.scope, EventScope::Cluster);
    }

    #[test]
    fn envelope_deserialize_defaults_absent_schema_version() {
        let restored: EventEnvelope = serde_json::from_value(json!({
            "channel": "workflow.todo.created",
            "idempotency_key": "todo-42-created",
            "emitted_at": "2026-05-16T12:00:00Z",
            "principal": null,
            "payload": {"slug": "demo", "title": "Demo"}
        }))
        .expect("legacy envelope without schema_version deserializes");

        assert_eq!(restored.schema_version, ENVELOPE_SCHEMA_VERSION);
    }

    #[test]
    fn envelope_deserialize_defaults_absent_scope() {
        let restored: EventEnvelope = serde_json::from_value(json!({
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "channel": "workflow.todo.created",
            "idempotency_key": "todo-42-created",
            "emitted_at": "2026-05-16T12:00:00Z",
            "principal": null,
            "payload": {"slug": "demo", "title": "Demo"}
        }))
        .expect("legacy envelope without scope deserializes");

        assert_eq!(restored.scope, EventScope::Local);
    }

    #[test]
    fn envelope_deserialize_ignores_unknown_top_level_fields() {
        let restored: EventEnvelope = serde_json::from_value(json!({
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "channel": "workflow.todo.created",
            "idempotency_key": "todo-42-created",
            "emitted_at": "2026-05-16T12:00:00Z",
            "principal": null,
            "payload": {"slug": "demo", "title": "Demo"},
            "future_capability": {"ignored": true}
        }))
        .expect("envelope with unknown top-level field deserializes");

        assert_eq!(restored.schema_version, ENVELOPE_SCHEMA_VERSION);
        assert_eq!(restored.channel, "workflow.todo.created");
    }
}
