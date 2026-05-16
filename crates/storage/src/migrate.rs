//! Migration runner helper.
//!
//! Service crates own their migrations under `<crate>/migrations/` and build
//! the [`sqlx::migrate::Migrator`] at compile time via the
//! [`sqlx::migrate!`] macro. This wrapper invokes the migrator at runtime,
//! emits structured `tracing` spans/events, and converts errors into
//! [`StorageError`].

use std::time::Instant;

use sqlx::migrate::Migrator;
use sqlx::PgPool;
use tracing::info;

use crate::errors::StorageError;

/// Run every migration in `migrator` against `pool`, logging the count and
/// elapsed wall-clock time on success.
///
/// Callers typically construct `migrator` with
/// `static MIGRATOR: Migrator = sqlx::migrate!("./migrations");`
/// inside their own crate.
pub async fn run_migrations(pool: &PgPool, migrator: &Migrator) -> Result<(), StorageError> {
    let total = migrator.migrations.len();
    let started = Instant::now();
    migrator.run(pool).await?;
    let elapsed = started.elapsed();
    info!(
        migrations = total,
        elapsed_ms = elapsed.as_millis() as u64,
        "ran sqlx migrations"
    );
    Ok(())
}
