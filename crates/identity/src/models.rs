//! Principal and Role types shared by every binary that resolves identity.
//!
//! Resolution is centralized in this crate. Authorization is decentralized:
//! each service pattern-matches on [`Principal`] to decide what callers can
//! do.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use shared::SessionId;
use uuid::Uuid;

/// A resolved caller identity. Every transport in TeleClaude converges on
/// this enum; services pattern-match on it for authorization decisions.
///
/// The `Anonymous` variant is marked `#[non_exhaustive]` so external crates
/// cannot construct it directly — they must go through
/// [`Principal::resolve_anonymous`]. Pattern matching still works (a
/// catch-all arm or matching on `Principal::Anonymous { .. }` is fine).
/// This encodes the auth-model invariant "Anonymous is the explicit
/// 'no auth evidence' outcome" in the type signature.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Principal {
    /// A human user identified by email.
    Human { email: String, role: Role },
    /// A daemon-spawned agent session.
    AgentSession { session_id: SessionId, role: Role },
    /// An internal system principal (worker, scheduler, etc.).
    System { service: String },
    /// An unauthenticated caller.
    ///
    /// `#[non_exhaustive]` prevents external crates from constructing this
    /// variant via `Principal::Anonymous`. Use
    /// [`Principal::resolve_anonymous`] instead.
    #[non_exhaustive]
    Anonymous,
}

impl Principal {
    /// The explicit constructor for [`Principal::Anonymous`].
    ///
    /// Resolution functions return Human / AgentSession for any authenticated
    /// caller and `Anonymous` for the explicit "no auth evidence" outcome.
    /// Callers that want an unauthenticated principal go through this method
    /// so the choice is visible at call sites; the type system enforces this
    /// via `#[non_exhaustive]` on the variant itself.
    pub fn resolve_anonymous() -> Self {
        Self::Anonymous
    }
}

/// Authorization role attached to a [`Principal`].
///
/// Stored in Postgres as `identity.role` enum (lower-snake_case literals).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(rename_all = "snake_case")]
#[sqlx(type_name = "identity.role", rename_all = "snake_case")]
pub enum Role {
    Owner,
    Admin,
    Member,
    Contributor,
    Newcomer,
}

/// Discriminator stored in `identity.principals.kind`.
///
/// Mirrors the variant tag of [`Principal`] for SQL filtering and joins.
/// Callers that work with full principals use [`Principal`] directly; this
/// enum is for storage-level queries that need to match by kind without
/// reconstructing the full variant.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(rename_all = "snake_case")]
#[sqlx(type_name = "identity.principal_kind", rename_all = "snake_case")]
pub enum PrincipalKind {
    Human,
    AgentSession,
    System,
    Anonymous,
}

impl PrincipalKind {
    /// Kind tag for the given principal.
    pub fn of(principal: &Principal) -> Self {
        match principal {
            Principal::Human { .. } => Self::Human,
            Principal::AgentSession { .. } => Self::AgentSession,
            Principal::System { .. } => Self::System,
            Principal::Anonymous => Self::Anonymous,
        }
    }
}

/// Opaque session-token handle.
///
/// Wraps the UUID stored in `identity.session_tokens.token`. The string
/// representation is what callers paste into `TELEC_SESSION_TOKEN` and what
/// is carried over HTTP — same shape as v1's `str(uuid.uuid4())` tokens so
/// v1 and v2 token issuers are interchangeable during the parallel period.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct Token(pub Uuid);

impl Token {
    /// Generate a fresh random token (UUID v4).
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }

    /// Parse a token from its textual representation.
    pub fn parse(value: &str) -> Result<Self, uuid::Error> {
        Uuid::parse_str(value).map(Self)
    }
}

impl Default for Token {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for Token {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}

/// A row from `identity.session_tokens`.
///
/// Returned by token-lookup helpers so callers can inspect issuance metadata
/// and revocation status without re-querying.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionTokenRecord {
    pub token: Token,
    pub session_id: SessionId,
    pub role: Role,
    pub principal: Principal,
    pub created_at: DateTime<Utc>,
    pub revoked_at: Option<DateTime<Utc>>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn principal_human_round_trip() {
        let principal = Principal::Human {
            email: "owner@example.com".to_string(),
            role: Role::Owner,
        };

        let encoded = serde_json::to_string(&principal).expect("serialize human");
        let decoded: Principal = serde_json::from_str(&encoded).expect("deserialize human");

        assert!(matches!(
            decoded,
            Principal::Human { email, role: Role::Owner } if email == "owner@example.com"
        ));
    }

    #[test]
    fn principal_agent_session_round_trip() {
        let session_id = SessionId::new();
        let principal = Principal::AgentSession {
            session_id,
            role: Role::Member,
        };

        let encoded = serde_json::to_string(&principal).expect("serialize agent session");
        let decoded: Principal = serde_json::from_str(&encoded).expect("deserialize agent session");

        assert!(matches!(
            decoded,
            Principal::AgentSession { session_id: decoded_id, role: Role::Member }
                if decoded_id == session_id
        ));
    }

    #[test]
    fn principal_system_round_trip() {
        let principal = Principal::System {
            service: "agent_runtime".to_string(),
        };

        let encoded = serde_json::to_string(&principal).expect("serialize system");
        let decoded: Principal = serde_json::from_str(&encoded).expect("deserialize system");

        assert!(matches!(
            decoded,
            Principal::System { service } if service == "agent_runtime"
        ));
    }

    #[test]
    fn principal_anonymous_round_trip() {
        let principal = Principal::resolve_anonymous();

        let encoded = serde_json::to_string(&principal).expect("serialize anonymous");
        let decoded: Principal = serde_json::from_str(&encoded).expect("deserialize anonymous");

        // Within the defining crate `Principal::Anonymous` is constructable
        // and pattern-matchable; the `#[non_exhaustive]` shield kicks in
        // only at external crate boundaries (covered by the integration
        // tests in tests/sealed_anonymous.rs).
        assert!(matches!(decoded, Principal::Anonymous));
    }

    #[test]
    fn principal_human_serializes_with_snake_case_kind() {
        let principal = Principal::Human {
            email: "owner@example.com".to_string(),
            role: Role::Owner,
        };

        let encoded = serde_json::to_value(&principal).expect("serialize human");

        assert_eq!(encoded["kind"], "human");
    }

    #[test]
    fn role_contributor_serializes_as_snake_case() {
        let encoded = serde_json::to_value(Role::Contributor).expect("serialize role");

        assert_eq!(encoded, json!("contributor"));
    }

    #[test]
    fn principal_kind_of_variants() {
        assert_eq!(
            PrincipalKind::of(&Principal::Human {
                email: "x@y.z".into(),
                role: Role::Owner
            }),
            PrincipalKind::Human
        );
        assert_eq!(
            PrincipalKind::of(&Principal::AgentSession {
                session_id: SessionId::new(),
                role: Role::Member
            }),
            PrincipalKind::AgentSession
        );
        assert_eq!(
            PrincipalKind::of(&Principal::System {
                service: "x".into()
            }),
            PrincipalKind::System
        );
        assert_eq!(
            PrincipalKind::of(&Principal::Anonymous),
            PrincipalKind::Anonymous
        );
    }

    #[test]
    fn token_round_trip_through_string() {
        let token = Token::new();
        let display = token.to_string();
        let parsed = Token::parse(&display).expect("parse token");
        assert_eq!(parsed, token);
    }

    #[test]
    fn token_serializes_transparently() {
        let token = Token::new();
        let encoded = serde_json::to_value(token).expect("serialize token");
        // sqlx(transparent)/serde(transparent) means the UUID renders bare.
        assert_eq!(encoded.as_str().unwrap().len(), 36);
    }
}
