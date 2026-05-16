//! Principal and Role types shared by every binary that resolves identity.
//!
//! Resolution is centralized in this crate. Authorization is decentralized:
//! each service pattern-matches on [`Principal`] to decide what callers can
//! do.

use shared::SessionId;

/// A resolved caller identity. Every transport in TeleClaude converges on
/// this enum; services pattern-match on it for authorization decisions.
#[derive(Debug, Clone, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Principal {
    /// A human user identified by email.
    Human { email: String, role: Role },
    /// A daemon-spawned agent session.
    AgentSession { session_id: SessionId, role: Role },
    /// An internal system principal (worker, scheduler, etc.).
    System { service: String },
    /// An unauthenticated caller.
    Anonymous,
}

/// Authorization role attached to a [`Principal`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Owner,
    Admin,
    Member,
    Contributor,
    Newcomer,
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let principal = Principal::Anonymous;

        let encoded = serde_json::to_string(&principal).expect("serialize anonymous");
        let decoded: Principal = serde_json::from_str(&encoded).expect("deserialize anonymous");

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

        assert_eq!(encoded, serde_json::json!("contributor"));
    }
}
