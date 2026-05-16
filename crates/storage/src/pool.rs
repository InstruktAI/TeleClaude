//! Postgres connection pool builders.
//!
//! Provides a small, opinionated wrapper around `sqlx::PgPoolOptions` so every
//! v2 service crate that needs a Postgres pool builds it through one place.

use std::time::Duration;

use sqlx::postgres::{PgPool, PgPoolOptions};

use crate::errors::StorageError;

/// Default upper bound on simultaneous connections held by the pool.
const DEFAULT_MAX_CONNECTIONS: u32 = 10;

/// Default time the pool waits for a free connection before erroring out.
const DEFAULT_ACQUIRE_TIMEOUT: Duration = Duration::from_secs(5);

/// Build a Postgres connection pool against `database_url` with v2 defaults
/// (`max_connections = 10`, `acquire_timeout = 5s`).
///
/// Thin wrapper over [`build_pool_with`] for the common case.
pub async fn build_pool(database_url: &str) -> Result<PgPool, StorageError> {
    build_pool_with(
        database_url,
        DEFAULT_MAX_CONNECTIONS,
        DEFAULT_ACQUIRE_TIMEOUT,
    )
    .await
}

/// Build a Postgres connection pool against `database_url` with the supplied
/// `max_connections` and `acquire_timeout`.
///
/// All callers ultimately funnel through this helper so the construction
/// configuration is uniform across services.
pub async fn build_pool_with(
    database_url: &str,
    max_connections: u32,
    acquire_timeout: Duration,
) -> Result<PgPool, StorageError> {
    let pool = PgPoolOptions::new()
        .max_connections(max_connections)
        .acquire_timeout(acquire_timeout)
        .connect(database_url)
        .await?;
    Ok(pool)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A bad `database_url` that cannot reach Postgres surfaces as
    /// [`StorageError::Connection`] rather than panicking.
    #[tokio::test]
    async fn build_pool_with_unreachable_host_returns_connection_error() {
        let result = build_pool_with(
            "postgres://postgres:postgres@127.0.0.1:1/nonexistent",
            1,
            Duration::from_millis(200),
        )
        .await;

        match result {
            Err(StorageError::Connection(_)) => {}
            Err(other) => panic!("expected Connection error, got: {other:?}"),
            Ok(_) => panic!("expected connect failure, got Ok"),
        }
    }
}
