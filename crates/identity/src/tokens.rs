//! Postgres-backed session token storage.
//!
//! Implements the durable side of [`crate::resolve::TokenValidator`] plus
//! the issue / revoke operations called from the daemon at session start
//! and close. Token lifecycle has one boundary — `revoked_at` — per
//! [`docs/project/design/architecture-v2/auth-model.md`]: no TTL, no
//! background sweeper.
//!
//! Persistence shape matches the migration in
//! `crates/identity/migrations/0001_init.sql`. Rows in
//! `identity.session_tokens` carry the principal foreign key plus a
//! denormalized `session_id` so revoke-by-session is a fast indexed
//! update.

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use shared::SessionId;
use sqlx::PgPool;
use sqlx::Row;
use uuid::Uuid;

use crate::errors::IdentityError;
use crate::models::{Principal, Role, SessionTokenRecord, Token};
use crate::resolve::TokenValidator;

/// Issue (or recover) the live session token for an existing principal.
///
/// Idempotent by `(principal_uuid, session_id)`: re-calling with the same
/// arguments returns the same token, so a retry after the
/// commit-then-emit posture's emit failure re-attempts the emit on the
/// same envelope rather than minting a fresh token. The partial unique
/// index `session_tokens_active_per_session_uq` (migration 0002) enforces
/// the "one live token per (principal, session)" invariant.
pub async fn issue_session_token(
    pool: &PgPool,
    principal_uuid: Uuid,
    session_id: SessionId,
    role: Role,
) -> Result<Token, IdentityError> {
    // Principal-not-found surfaces before the upsert so the caller sees a
    // typed error rather than a generic FK violation.
    let principal_row = sqlx::query("select id from identity.principals where uuid_id = $1")
        .bind(principal_uuid)
        .fetch_optional(pool)
        .await?;
    let principal_row = principal_row
        .ok_or_else(|| IdentityError::PrincipalNotFound(format!("uuid_id={principal_uuid}")))?;
    let principal_id: i64 = principal_row.try_get("id")?;

    // Upsert: insert when no live token exists for the pair; otherwise
    // return the existing live token. The partial unique index makes
    // `on conflict do nothing` deterministic.
    let row = sqlx::query(
        r#"
        with ins as (
            insert into identity.session_tokens (principal_id, session_id, role)
            values ($1, $2, $3)
            on conflict do nothing
            returning token
        )
        select token from ins
        union all
        select token
            from identity.session_tokens
            where principal_id = $1 and session_id = $2 and revoked_at is null
        limit 1
        "#,
    )
    .bind(principal_id)
    .bind(session_id.0)
    .bind(role)
    .fetch_optional(pool)
    .await?;

    let row = row.ok_or_else(|| IdentityError::Db(sqlx::Error::RowNotFound))?;
    let token: Token = row.try_get("token")?;
    Ok(token)
}

/// Insert a v1 session token verbatim — token uuid, session uuid, role
/// — preserving the v1 ledger row during migration.
///
/// Idempotent on `token` (the primary key): re-running the migration
/// observes the existing row and returns `Ok(false)`. New rows return
/// `Ok(true)` so the migration can emit `TokenIssued` for newly imported
/// rows.
pub async fn import_session_token(
    pool: &PgPool,
    principal_uuid: Uuid,
    token: Token,
    session_id: SessionId,
    role: Role,
) -> Result<bool, IdentityError> {
    let principal_row = sqlx::query("select id from identity.principals where uuid_id = $1")
        .bind(principal_uuid)
        .fetch_optional(pool)
        .await?;
    let principal_row = principal_row
        .ok_or_else(|| IdentityError::PrincipalNotFound(format!("uuid_id={principal_uuid}")))?;
    let principal_id: i64 = principal_row.try_get("id")?;

    let result = sqlx::query(
        r#"
        insert into identity.session_tokens (token, principal_id, session_id, role)
        values ($1, $2, $3, $4)
        on conflict (token) do nothing
        "#,
    )
    .bind(token.0)
    .bind(principal_id)
    .bind(session_id.0)
    .bind(role)
    .execute(pool)
    .await?;

    Ok(result.rows_affected() == 1)
}

/// Mark every token for the given session as revoked.
///
/// Returns the number of rows transitioned (zero is not an error — closing
/// a session that never issued a token is a routine case).
pub async fn revoke_session_tokens(
    pool: &PgPool,
    session_id: SessionId,
) -> Result<u32, IdentityError> {
    let result = sqlx::query(
        r#"
        update identity.session_tokens
        set revoked_at = now()
        where session_id = $1 and revoked_at is null
        "#,
    )
    .bind(session_id.0)
    .execute(pool)
    .await?;

    Ok(u32::try_from(result.rows_affected()).unwrap_or(u32::MAX))
}

/// Look up the principal associated with a token.
///
/// Returns
/// - `Ok(principal)` for a live token,
/// - `Err(IdentityError::TokenNotFound)` when no row matches,
/// - `Err(IdentityError::TokenRevoked)` when the row has `revoked_at` set.
pub async fn validate_session_token(
    pool: &PgPool,
    token: Token,
) -> Result<Principal, IdentityError> {
    let record = match fetch_token_record(pool, token).await? {
        Some(rec) => rec,
        None => return Err(IdentityError::TokenNotFound),
    };
    if record.revoked_at.is_some() {
        return Err(IdentityError::TokenRevoked);
    }
    Ok(record.principal)
}

/// Fetch the full [`SessionTokenRecord`] for a token, including the
/// associated principal.
///
/// Returns `Ok(None)` when no token row matches. Revoked tokens are still
/// returned so callers can inspect revocation metadata.
pub async fn fetch_token_record(
    pool: &PgPool,
    token: Token,
) -> Result<Option<SessionTokenRecord>, IdentityError> {
    let row = sqlx::query(
        r#"
        select
            t.token        as token,
            t.session_id   as session_id,
            t.role         as token_role,
            t.created_at   as created_at,
            t.revoked_at   as revoked_at,
            p.kind         as kind,
            p.email        as email,
            p.session_id   as principal_session_id,
            p.service      as service,
            p.role         as principal_role
        from identity.session_tokens t
        join identity.principals p on p.id = t.principal_id
        where t.token = $1
        "#,
    )
    .bind(token.0)
    .fetch_optional(pool)
    .await?;

    let Some(row) = row else {
        return Ok(None);
    };

    let kind: crate::models::PrincipalKind =
        row.try_get::<crate::models::PrincipalKind, _>("kind")?;
    let principal_role: Option<Role> = row.try_get::<Option<Role>, _>("principal_role")?;
    let principal = match kind {
        crate::models::PrincipalKind::Human => Principal::Human {
            email: row.try_get("email")?,
            role: principal_role.ok_or_else(|| {
                IdentityError::AuthMalformed("human principal missing role".into())
            })?,
        },
        crate::models::PrincipalKind::AgentSession => {
            let raw: Uuid = row.try_get("principal_session_id")?;
            Principal::AgentSession {
                session_id: SessionId(raw),
                role: principal_role.ok_or_else(|| {
                    IdentityError::AuthMalformed("agent session principal missing role".into())
                })?,
            }
        }
        crate::models::PrincipalKind::System => Principal::System {
            service: row.try_get("service")?,
        },
        crate::models::PrincipalKind::Anonymous => Principal::Anonymous,
    };

    let session_uuid: Uuid = row.try_get("session_id")?;
    Ok(Some(SessionTokenRecord {
        token: row.try_get("token")?,
        session_id: SessionId(session_uuid),
        role: row.try_get("token_role")?,
        principal,
        created_at: row.try_get::<DateTime<Utc>, _>("created_at")?,
        revoked_at: row.try_get::<Option<DateTime<Utc>>, _>("revoked_at")?,
    }))
}

/// [`TokenValidator`] adapter backed by an [`PgPool`].
///
/// The service struct in `service.rs` (Wave D1) holds an `Arc<PgPool>`
/// and forwards `validate` calls here. Exposed publicly so callers that
/// only need validation (HTTP middleware) can construct it directly.
pub struct PgTokenValidator<'a> {
    pool: &'a PgPool,
}

impl<'a> PgTokenValidator<'a> {
    pub fn new(pool: &'a PgPool) -> Self {
        Self { pool }
    }
}

#[async_trait]
impl<'a> TokenValidator for PgTokenValidator<'a> {
    async fn validate(&self, token: Token) -> Result<Principal, IdentityError> {
        validate_session_token(self.pool, token).await
    }
}
