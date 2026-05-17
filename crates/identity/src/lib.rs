//! identity — resolution authority and principal type model.
//!
//! Owns the `identity` Postgres schema. Public surface: domain models
//! ([`Principal`], [`Role`], [`Token`]), event schemas, resolution helpers,
//! and (from Wave D onward) the `IdentityService` struct.
//!
//! See `docs/project/design/architecture-v2/auth-model.md` for the
//! resolution flow per transport and the per-service authorization split.

pub mod errors;
pub mod events;
pub mod login;
pub mod models;
pub mod resolve;
pub mod service;
pub mod tokens;

pub use errors::IdentityError;
pub use models::{Principal, PrincipalKind, Role, SessionTokenRecord, Token};
pub use resolve::{
    resolve_from_env, resolve_from_env_with, resolve_from_env_with_login, resolve_from_environment,
    resolve_from_http_with, resolve_from_session_token_with, resolve_with, TokenValidator,
    HEADER_SESSION_TOKEN, HEADER_TELEC_EMAIL, OWNER_EMAIL_ENV, SESSION_TOKEN_ENV,
};
pub use service::{IdentityEventSink, IdentityService};
pub use tokens::{
    fetch_token_record, import_session_token, issue_session_token, revoke_session_tokens,
    validate_session_token, PgTokenValidator,
};

/// Identity schema migrator. Callers run it at startup via
/// [`storage::run_migrations`] so the `identity.*` tables exist before the
/// service issues queries.
pub static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");
