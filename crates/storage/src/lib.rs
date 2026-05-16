//! storage — Postgres connection pool builder and migration runner helpers.
//!
//! Every v2 service crate that talks to Postgres goes through this crate to
//! build its [`PgPool`] and to run its `sqlx::migrate!` migrations, so the
//! defaults stay uniform across services.

pub mod errors;
pub mod migrate;
pub mod pool;

pub use errors::StorageError;
pub use migrate::run_migrations;
pub use pool::{build_pool, build_pool_with};

// Re-export the upstream types callers need so downstream crates don't have
// to depend on `sqlx` directly for the common surface.
pub use sqlx::migrate::Migrator;
pub use sqlx::PgPool;
