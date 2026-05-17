//! Identity event channel constants and typed payload schemas.
//!
//! Channels follow the v2 naming convention `{service}.{aggregate}.{verb_past}`
//! (see `docs/project/design/architecture-v2/event-bus-transports.md`). Each
//! channel constant pairs with exactly one payload struct. Payloads
//! serialize to/from JSON via `serde` for the Redis Streams envelope.
//!
//! Per `auth-model.md` and `transport-rules.md`, identity emits a fact every
//! time a principal is created or a token transitions. Subscribers (v1
//! daemon during the parallel period; v2 services post-cutover) react.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use shared::SessionId;
use uuid::Uuid;

use crate::models::{PrincipalKind, Role};

/// Channel for [`PrincipalCreated`] events.
pub const CHANNEL_PRINCIPAL_CREATED: &str = "identity.principal.created";

/// Channel for [`TokenIssued`] events.
pub const CHANNEL_TOKEN_ISSUED: &str = "identity.token.issued";

/// Channel for [`TokenRevoked`] events.
pub const CHANNEL_TOKEN_REVOKED: &str = "identity.token.revoked";

/// Emitted when a new principal is durably persisted.
///
/// Email is included for human principals so subscribers (e.g. v1 daemon
/// cache invalidation) do not need a follow-up lookup. AgentSession session
/// ids and System service names are equivalent natural keys for their
/// respective kinds.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PrincipalCreated {
    /// Storage-level UUID of the principal row.
    pub principal_uuid: Uuid,
    /// Kind discriminator (human / agent_session / system).
    pub kind: PrincipalKind,
    /// Email when `kind == human`, otherwise `None`.
    pub email: Option<String>,
    /// Session id when `kind == agent_session`, otherwise `None`.
    pub session_id: Option<SessionId>,
    /// Service name when `kind == system`, otherwise `None`.
    pub service: Option<String>,
    /// Role attached to the principal (always `None` for system / anonymous).
    pub role: Option<Role>,
    /// UTC timestamp the principal row was written.
    pub created_at: DateTime<Utc>,
}

/// Emitted when a session token is issued and stored.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TokenIssued {
    /// Storage-level UUID of the owning principal row.
    pub principal_uuid: Uuid,
    /// Session id this token authorizes.
    pub session_id: SessionId,
    /// Role attached to the token at issuance.
    pub role: Role,
    /// UTC timestamp the token row was written.
    pub issued_at: DateTime<Utc>,
}

/// Emitted when one or more tokens for a session are revoked.
///
/// Carried at session-level rather than per-token because v1 and v2 both
/// revoke on session close, never per-token. Subscribers that want a per-
/// token signal can query the storage layer via the identity service.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TokenRevoked {
    /// Session id whose tokens were revoked.
    pub session_id: SessionId,
    /// How many token rows transitioned to `revoked_at = now()`.
    pub tokens_revoked: u32,
    /// UTC timestamp the revocation was applied.
    pub revoked_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn principal_created_serde_round_trip() {
        let event = PrincipalCreated {
            principal_uuid: Uuid::new_v4(),
            kind: PrincipalKind::Human,
            email: Some("owner@example.com".into()),
            session_id: None,
            service: None,
            role: Some(Role::Owner),
            created_at: Utc::now(),
        };
        let encoded = serde_json::to_string(&event).expect("serialize");
        let decoded: PrincipalCreated = serde_json::from_str(&encoded).expect("deserialize");
        assert_eq!(decoded, event);
    }

    #[test]
    fn token_issued_serde_round_trip() {
        let event = TokenIssued {
            principal_uuid: Uuid::new_v4(),
            session_id: SessionId::new(),
            role: Role::Member,
            issued_at: Utc::now(),
        };
        let encoded = serde_json::to_string(&event).expect("serialize");
        let decoded: TokenIssued = serde_json::from_str(&encoded).expect("deserialize");
        assert_eq!(decoded, event);
    }

    #[test]
    fn token_revoked_serde_round_trip() {
        let event = TokenRevoked {
            session_id: SessionId::new(),
            tokens_revoked: 3,
            revoked_at: Utc::now(),
        };
        let encoded = serde_json::to_string(&event).expect("serialize");
        let decoded: TokenRevoked = serde_json::from_str(&encoded).expect("deserialize");
        assert_eq!(decoded, event);
    }

    #[test]
    fn channel_constants_use_snake_case_segments() {
        assert_eq!(CHANNEL_PRINCIPAL_CREATED, "identity.principal.created");
        assert_eq!(CHANNEL_TOKEN_ISSUED, "identity.token.issued");
        assert_eq!(CHANNEL_TOKEN_REVOKED, "identity.token.revoked");
    }

    #[test]
    fn principal_kind_serializes_snake_case() {
        let encoded = serde_json::to_value(PrincipalKind::AgentSession).expect("serialize kind");
        assert_eq!(encoded, json!("agent_session"));
    }
}
