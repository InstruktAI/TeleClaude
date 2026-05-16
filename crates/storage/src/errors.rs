//! Error type for the storage crate.

/// Errors surfaced by storage helpers.
///
/// Wraps the upstream `sqlx` failures so callers can pattern-match on the
/// failure mode without depending on `sqlx` directly.
#[derive(thiserror::Error, Debug)]
pub enum StorageError {
    /// A connection-pool acquisition or query against Postgres failed.
    #[error("database connection error: {0}")]
    Connection(#[from] sqlx::Error),

    /// A migration step reported by `sqlx::migrate` failed.
    #[error("migration error: {0}")]
    Migration(#[from] sqlx::migrate::MigrateError),
}
