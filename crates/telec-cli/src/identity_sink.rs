//! Adapter that lets [`identity::IdentityService`] emit via the shared
//! [`event_bus::EventBus`].
//!
//! The `identity` crate cannot depend on `event-bus` (`event-bus` already
//! depends on `identity` for [`Principal`], so a back-edge would create a
//! cycle). Each identity service mutation publishes via the
//! [`identity::IdentityEventSink`] trait; this adapter constructs the
//! canonical [`event_bus::EventEnvelope`] and forwards to the connected
//! bus, surfacing emit failures as [`identity::IdentityError::EmitFailed`]
//! so callers honor the commit-then-emit posture documented in
//! `transport-rules.md`.

use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use event_bus::{envelope::ENVELOPE_SCHEMA_VERSION, EventBus, EventEnvelope, EventScope};
use identity::events::{PrincipalCreated, TokenIssued, TokenRevoked};
use identity::{IdentityError, IdentityEventSink, Principal};

const CHANNEL_PRINCIPAL_CREATED: &str = "identity.principal.created";
const CHANNEL_TOKEN_ISSUED: &str = "identity.token.issued";
const CHANNEL_TOKEN_REVOKED: &str = "identity.token.revoked";

/// Bridge between [`IdentityService`] and the global [`EventBus`].
///
/// Holds the principal that triggered the current process invocation so
/// the envelopes carry the correct attribution. The principal is the
/// resolved [`Principal`] from `identity::resolve_from_env_with` at CLI
/// startup; for daemon-spawned binaries it is the
/// [`Principal::AgentSession`] their session token maps to.
pub struct EventBusIdentitySink {
    bus: Arc<EventBus>,
    principal: Option<Principal>,
}

impl EventBusIdentitySink {
    pub fn new(bus: Arc<EventBus>, principal: Option<Principal>) -> Self {
        Self { bus, principal }
    }
}

#[async_trait]
impl IdentityEventSink for EventBusIdentitySink {
    async fn emit_principal_created(&self, event: PrincipalCreated) -> Result<(), IdentityError> {
        let envelope = build_envelope(
            CHANNEL_PRINCIPAL_CREATED,
            format!("principal.created:{}", event.principal_uuid),
            self.principal.clone(),
            &event,
        )?;
        self.bus
            .emit(&envelope)
            .await
            .map_err(|err| IdentityError::EmitFailed {
                message: err.to_string(),
                state_committed: true,
            })
    }

    async fn emit_token_issued(&self, event: TokenIssued) -> Result<(), IdentityError> {
        let envelope = build_envelope(
            CHANNEL_TOKEN_ISSUED,
            format!("token.issued:{}:{}", event.principal_uuid, event.session_id),
            self.principal.clone(),
            &event,
        )?;
        self.bus
            .emit(&envelope)
            .await
            .map_err(|err| IdentityError::EmitFailed {
                message: err.to_string(),
                state_committed: true,
            })
    }

    async fn emit_token_revoked(&self, event: TokenRevoked) -> Result<(), IdentityError> {
        let envelope = build_envelope(
            CHANNEL_TOKEN_REVOKED,
            format!("token.revoked:{}", event.session_id),
            self.principal.clone(),
            &event,
        )?;
        self.bus
            .emit(&envelope)
            .await
            .map_err(|err| IdentityError::EmitFailed {
                message: err.to_string(),
                state_committed: true,
            })
    }
}

fn build_envelope<T: serde::Serialize>(
    channel: &str,
    idempotency_key: String,
    principal: Option<Principal>,
    event: &T,
) -> Result<EventEnvelope, IdentityError> {
    let payload = serde_json::to_value(event).map_err(|err| IdentityError::EmitFailed {
        message: format!("serialize {channel}: {err}"),
        state_committed: true,
    })?;
    Ok(EventEnvelope {
        schema_version: ENVELOPE_SCHEMA_VERSION,
        scope: EventScope::Cluster,
        channel: channel.to_string(),
        idempotency_key,
        emitted_at: Utc::now(),
        principal,
        payload,
    })
}
