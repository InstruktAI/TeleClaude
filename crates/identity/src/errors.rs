//! Error type for the identity crate.
//!
//! Identity functions surface failures as [`IdentityError`]. The variant set
//! is the one pinned by the prepare artifact — every variant maps to a
//! real failure mode the surface code needs to distinguish (revoked token
//! vs missing token vs malformed evidence, etc.).
//!
//! Per the v2 emit posture (commit-then-emit, loud fail) the
//! [`IdentityError::EmitFailed`] variant signals that a state-changing
//! operation committed but the resulting Redis event could not be published.
//! Callers are expected to be idempotent: a retry observes the existing
//! state and re-attempts the emit (subscribers dedupe via idempotency key).

/// Errors returned by identity-resolution and identity-service operations.
#[derive(thiserror::Error, Debug)]
pub enum IdentityError {
    /// Lookup found no principal matching the supplied evidence.
    #[error("principal not found: {0}")]
    PrincipalNotFound(String),

    /// Session token not present in the ledger.
    #[error("token not found")]
    TokenNotFound,

    /// Session token previously issued but revoked (revoked_at is set).
    #[error("token revoked")]
    TokenRevoked,

    /// Session token did not parse as a UUID.
    #[error("invalid token format")]
    InvalidToken,

    /// Role string is not one of the canonical [`crate::Role`] variants.
    #[error("invalid role: {0}")]
    InvalidRole(String),

    /// Authentication evidence (env var / header / login file / token) was
    /// absent on a request that requires it.
    #[error("authentication evidence missing")]
    AuthMissing,

    /// Authentication evidence was present but malformed in a kind-specific
    /// way that is not covered by [`IdentityError::InvalidToken`].
    #[error("authentication evidence malformed: {0}")]
    AuthMalformed(String),

    /// Persisted state was modified but the resulting Redis event could not
    /// be published.
    ///
    /// `state_committed` is always true: per the v2 emit posture, identity
    /// commits the Postgres transaction first, then emits. A failure here
    /// means the durable state already changed; only the notification is
    /// lost. Idempotent callers may retry the operation; subscribers
    /// deduplicate via the envelope's stable idempotency key.
    #[error("emit failed after commit (state durable, event lost): {message}")]
    EmitFailed {
        message: String,
        state_committed: bool,
    },

    /// A Postgres operation failed for a reason not otherwise classified.
    #[error(transparent)]
    Db(#[from] sqlx::Error),
}

impl IdentityError {
    /// Parse a role string into a [`crate::Role`], surfacing
    /// [`IdentityError::InvalidRole`] for unknown values.
    ///
    /// Centralized so every code path that maps from configuration / v1
    /// data into a typed role fails with the same explicit variant.
    pub fn parse_role(raw: &str) -> Result<crate::Role, IdentityError> {
        match raw {
            "owner" => Ok(crate::Role::Owner),
            "admin" => Ok(crate::Role::Admin),
            "member" => Ok(crate::Role::Member),
            "contributor" => Ok(crate::Role::Contributor),
            "newcomer" => Ok(crate::Role::Newcomer),
            other => Err(IdentityError::InvalidRole(other.to_string())),
        }
    }
}
