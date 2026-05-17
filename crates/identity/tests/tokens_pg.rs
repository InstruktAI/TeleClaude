//! Integration tests for the Postgres-backed token surface.
//!
//! `sqlx::test` spins up a fresh database per test and applies the
//! identity migrator. Each test exercises one stage of the token
//! lifecycle (issue / validate / revoke) plus the error paths the
//! [`IdentityError`] variants cover.

use identity::{
    errors::IdentityError, issue_session_token, revoke_session_tokens, validate_session_token,
    Principal, PrincipalKind, Role,
};
use shared::SessionId;
use sqlx::PgPool;
use sqlx::Row;
use uuid::Uuid;

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

async fn seed_human_principal(pool: &PgPool, email: &str) -> Uuid {
    let row = sqlx::query(
        "insert into identity.principals (kind, email, role) values ('human', $1, 'owner') returning uuid_id",
    )
    .bind(email)
    .fetch_one(pool)
    .await
    .expect("insert human principal");
    row.try_get("uuid_id").expect("uuid_id")
}

async fn seed_agent_session_principal(pool: &PgPool, sid: SessionId, role: Role) -> Uuid {
    let row = sqlx::query(
        "insert into identity.principals (kind, session_id, role) values ('agent_session', $1, $2) returning uuid_id",
    )
    .bind(sid.0)
    .bind(role)
    .fetch_one(pool)
    .await
    .expect("insert agent session principal");
    row.try_get("uuid_id").expect("uuid_id")
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn issue_then_validate_returns_principal(pool: PgPool) {
    let session_id = SessionId::new();
    let principal_uuid = seed_agent_session_principal(&pool, session_id, Role::Member).await;

    let token = issue_session_token(&pool, principal_uuid, session_id, Role::Member)
        .await
        .expect("issue token");

    let principal = validate_session_token(&pool, token)
        .await
        .expect("validate live token");

    assert_eq!(PrincipalKind::of(&principal), PrincipalKind::AgentSession);
    let Principal::AgentSession {
        session_id: resolved,
        role,
    } = principal
    else {
        panic!("expected AgentSession principal");
    };
    assert_eq!(resolved, session_id);
    assert_eq!(role, Role::Member);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn validate_missing_token_returns_not_found(pool: PgPool) {
    let err = validate_session_token(&pool, identity::Token::new())
        .await
        .expect_err("expected TokenNotFound");

    assert!(matches!(err, IdentityError::TokenNotFound));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn revoke_marks_token_revoked_and_validate_surfaces_revoked_error(pool: PgPool) {
    let session_id = SessionId::new();
    let principal_uuid = seed_agent_session_principal(&pool, session_id, Role::Member).await;
    let token = issue_session_token(&pool, principal_uuid, session_id, Role::Member)
        .await
        .expect("issue token");

    let revoked_count = revoke_session_tokens(&pool, session_id)
        .await
        .expect("revoke tokens");

    assert_eq!(revoked_count, 1);

    let err = validate_session_token(&pool, token)
        .await
        .expect_err("expected TokenRevoked");
    assert!(matches!(err, IdentityError::TokenRevoked));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn revoke_is_idempotent_when_no_live_tokens_exist(pool: PgPool) {
    let revoked = revoke_session_tokens(&pool, SessionId::new())
        .await
        .expect("revoke");
    assert_eq!(revoked, 0);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn issue_for_unknown_principal_returns_not_found(pool: PgPool) {
    let err = issue_session_token(&pool, Uuid::new_v4(), SessionId::new(), Role::Owner)
        .await
        .expect_err("expected PrincipalNotFound");

    assert!(matches!(err, IdentityError::PrincipalNotFound(_)));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn issue_human_then_validate_returns_human_principal(pool: PgPool) {
    let principal_uuid = seed_human_principal(&pool, "owner@example.com").await;
    let token = issue_session_token(&pool, principal_uuid, SessionId::new(), Role::Owner)
        .await
        .expect("issue token");

    let principal = validate_session_token(&pool, token)
        .await
        .expect("validate");

    let Principal::Human { email, role } = principal else {
        panic!("expected Human principal");
    };
    assert_eq!(email, "owner@example.com");
    assert_eq!(role, Role::Owner);
}
