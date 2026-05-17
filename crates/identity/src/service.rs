//! IdentityService — composes principal storage, token lifecycle, and event
//! emission.
//!
//! The service owns the `identity` Postgres schema (writes) and emits the
//! `identity.*` Redis events on every mutation per the v2 emit posture:
//! **commit-then-emit, loud fail**.
//!
//! Retry safety (RV-1 contract):
//!
//! 1. Postgres state change is idempotent on the natural key: `ensure_principal`
//!    upserts on `(kind, natural_key)`; `issue_session_token` upserts on the
//!    `(principal_id, session_id)` partial unique index (live tokens only).
//! 2. The service ALWAYS emits the corresponding event after a successful
//!    DB call, regardless of whether the row was newly inserted or already
//!    existed. The envelope's `idempotency_key` is derived from the stable
//!    row identifier (principal `uuid_id`, token `uuid`, session id), so a
//!    retry after [`IdentityError::EmitFailed`] re-emits the same envelope
//!    and subscribers deduplicate via their LRU idempotency cache (see
//!    `teleclaude/transport/identity_bridge.py`).
//! 3. On emit failure the service returns
//!    [`IdentityError::EmitFailed { state_committed: true }`] so callers
//!    know the durable state is safe to re-observe. A retry of the same
//!    operation either re-emits and succeeds, or returns the same error
//!    until Redis recovers.
//!
//! Event-bus coupling: identity does NOT depend on the `event-bus` crate
//! (event-bus already depends on identity for `Principal`, so a back-edge
//! would create a cycle). Instead the service takes an
//! [`IdentityEventSink`] trait; the binary that composes identity with
//! `event-bus` provides an adapter.

use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use shared::SessionId;
use sqlx::PgPool;
use sqlx::Row;
use uuid::Uuid;

use crate::errors::IdentityError;
use crate::events::{PrincipalCreated, TokenIssued, TokenRevoked};
use crate::models::{Principal, PrincipalKind, Role, Token};
use crate::tokens::{
    issue_session_token, revoke_session_tokens, validate_session_token, PgTokenValidator,
};

/// Trait identity uses to publish events to the bus.
///
/// Implementations sit in the binary that wires identity to event-bus.
/// Each method returns the per-channel event the bus delivers; the
/// service struct fans out [`IdentityError::EmitFailed`] when any of
/// these returns an error, after the corresponding state change has
/// already committed.
#[async_trait]
pub trait IdentityEventSink: Send + Sync {
    /// Publish an [`identity.principal.created`] event.
    async fn emit_principal_created(&self, event: PrincipalCreated) -> Result<(), IdentityError>;

    /// Publish an [`identity.token.issued`] event.
    async fn emit_token_issued(&self, event: TokenIssued) -> Result<(), IdentityError>;

    /// Publish an [`identity.token.revoked`] event.
    async fn emit_token_revoked(&self, event: TokenRevoked) -> Result<(), IdentityError>;
}

/// Service struct.
///
/// Holds a pool plus an event sink; clones are cheap because both are
/// reference-counted internally.
pub struct IdentityService {
    pool: PgPool,
    events: Arc<dyn IdentityEventSink>,
}

impl IdentityService {
    /// Build a service from a connected pool and an event sink.
    pub fn new(pool: PgPool, events: Arc<dyn IdentityEventSink>) -> Self {
        Self { pool, events }
    }

    /// Borrow the underlying pool (read-only / testing convenience).
    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    /// Borrow the event sink (used by tooling that needs to emit
    /// identity envelopes outside the service surface).
    pub fn events(&self) -> &Arc<dyn IdentityEventSink> {
        &self.events
    }

    /// Upsert a [`Principal`] into `identity.principals` and emit
    /// `identity.principal.created`.
    ///
    /// Idempotent on the natural key. The event is emitted on every call;
    /// the envelope's `idempotency_key` is `principal.created:{uuid}` so
    /// subscriber-side dedup makes re-emission free under retry.
    pub async fn ensure_principal(&self, principal: &Principal) -> Result<Uuid, IdentityError> {
        let uuid = match principal {
            Principal::Human { email, role } => self.upsert_human(email, *role).await?,
            Principal::AgentSession { session_id, role } => {
                self.upsert_agent_session(*session_id, *role).await?
            }
            Principal::System { service } => self.upsert_system(service).await?,
            _ => {
                return Err(IdentityError::AuthMalformed(
                    "anonymous principals are not persisted".into(),
                ))
            }
        };

        let event = PrincipalCreated {
            principal_uuid: uuid,
            kind: PrincipalKind::of(principal),
            email: human_email(principal),
            session_id: agent_session_id(principal),
            service: system_service(principal),
            role: principal_role(principal),
            created_at: Utc::now(),
        };
        self.events
            .emit_principal_created(event)
            .await
            .map_err(|err| Self::wrap_emit(err, "principal.created"))?;

        Ok(uuid)
    }

    /// Issue (or recover) the live session token for an existing principal
    /// and emit `identity.token.issued`.
    ///
    /// Idempotent by `(principal_uuid, session_id)`. The principal must
    /// already exist (call [`Self::ensure_principal`] first).
    pub async fn issue_session_token(
        &self,
        principal_uuid: Uuid,
        session_id: SessionId,
        role: Role,
    ) -> Result<Token, IdentityError> {
        let token = issue_session_token(&self.pool, principal_uuid, session_id, role).await?;
        let event = TokenIssued {
            principal_uuid,
            session_id,
            role,
            issued_at: Utc::now(),
        };
        self.events
            .emit_token_issued(event)
            .await
            .map_err(|err| Self::wrap_emit(err, "token.issued"))?;
        Ok(token)
    }

    /// Revoke every live token for a session.
    ///
    /// Emits [`TokenRevoked`] whenever at least one row transitions to
    /// `revoked_at = now()`. A no-op revoke (no live tokens) does not
    /// emit — there is nothing for subscribers to react to.
    pub async fn revoke_session_tokens(&self, session_id: SessionId) -> Result<u32, IdentityError> {
        let revoked_at = Utc::now();
        let tokens_revoked = revoke_session_tokens(&self.pool, session_id).await?;
        if tokens_revoked > 0 {
            let event = TokenRevoked {
                session_id,
                tokens_revoked,
                revoked_at,
            };
            self.events
                .emit_token_revoked(event)
                .await
                .map_err(|err| Self::wrap_emit(err, "token.revoked"))?;
        }
        Ok(tokens_revoked)
    }

    /// Validate a session token, returning the principal it authorizes.
    pub async fn validate_session_token(&self, token: Token) -> Result<Principal, IdentityError> {
        validate_session_token(&self.pool, token).await
    }

    /// Pool-backed [`crate::resolve::TokenValidator`] for callers that
    /// want to drive the resolve helpers directly.
    pub fn token_validator(&self) -> PgTokenValidator<'_> {
        PgTokenValidator::new(&self.pool)
    }

    async fn upsert_human(&self, email: &str, role: Role) -> Result<Uuid, IdentityError> {
        let row = sqlx::query(
            r#"
            with ins as (
                insert into identity.principals (kind, email, role)
                values ('human', $1, $2)
                on conflict do nothing
                returning uuid_id
            )
            select uuid_id from ins
            union all
            select uuid_id
                from identity.principals
                where kind = 'human' and email = $1
            limit 1
            "#,
        )
        .bind(email)
        .bind(role)
        .fetch_one(&self.pool)
        .await?;
        Ok(row.try_get("uuid_id")?)
    }

    async fn upsert_agent_session(
        &self,
        session_id: SessionId,
        role: Role,
    ) -> Result<Uuid, IdentityError> {
        let row = sqlx::query(
            r#"
            with ins as (
                insert into identity.principals (kind, session_id, role)
                values ('agent_session', $1, $2)
                on conflict do nothing
                returning uuid_id
            )
            select uuid_id from ins
            union all
            select uuid_id
                from identity.principals
                where kind = 'agent_session' and session_id = $1
            limit 1
            "#,
        )
        .bind(session_id.0)
        .bind(role)
        .fetch_one(&self.pool)
        .await?;
        Ok(row.try_get("uuid_id")?)
    }

    async fn upsert_system(&self, service: &str) -> Result<Uuid, IdentityError> {
        let row = sqlx::query(
            r#"
            with ins as (
                insert into identity.principals (kind, service)
                values ('system', $1)
                on conflict do nothing
                returning uuid_id
            )
            select uuid_id from ins
            union all
            select uuid_id
                from identity.principals
                where kind = 'system' and service = $1
            limit 1
            "#,
        )
        .bind(service)
        .fetch_one(&self.pool)
        .await?;
        Ok(row.try_get("uuid_id")?)
    }

    fn wrap_emit(err: IdentityError, channel: &str) -> IdentityError {
        match err {
            IdentityError::EmitFailed { message, .. } => IdentityError::EmitFailed {
                message: format!("{channel}: {message}"),
                state_committed: true,
            },
            other => IdentityError::EmitFailed {
                message: format!("{channel}: {other}"),
                state_committed: true,
            },
        }
    }
}

fn human_email(p: &Principal) -> Option<String> {
    match p {
        Principal::Human { email, .. } => Some(email.clone()),
        _ => None,
    }
}

fn agent_session_id(p: &Principal) -> Option<SessionId> {
    match p {
        Principal::AgentSession { session_id, .. } => Some(*session_id),
        _ => None,
    }
}

fn system_service(p: &Principal) -> Option<String> {
    match p {
        Principal::System { service } => Some(service.clone()),
        _ => None,
    }
}

fn principal_role(p: &Principal) -> Option<Role> {
    match p {
        Principal::Human { role, .. } | Principal::AgentSession { role, .. } => Some(*role),
        _ => None,
    }
}
