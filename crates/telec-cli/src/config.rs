//! Environment / runtime configuration for `telec-cli`.
//!
//! Loads `DATABASE_URL` and `REDIS_URL` from the process environment. The
//! caller (usually `main`) is expected to have already loaded `.env` via
//! `dotenvy::dotenv().ok()` so these lookups see overlay values.

use anyhow::{anyhow, Result};

/// Environment variable holding the Postgres connection string.
pub const DATABASE_URL_ENV: &str = "DATABASE_URL";

/// Environment variable holding the Redis connection string.
pub const REDIS_URL_ENV: &str = "REDIS_URL";

/// Required runtime configuration loaded from the environment.
#[derive(Debug, Clone)]
pub struct CliConfig {
    /// Postgres connection string (e.g. `postgres://user:pass@host/db`).
    pub database_url: String,
    /// Redis connection string (e.g. `redis://localhost:6379`).
    pub redis_url: String,
}

impl CliConfig {
    /// Read [`CliConfig`] from the process environment.
    ///
    /// Returns an error naming the first missing variable. Both variables
    /// must be present and non-empty.
    pub fn from_env() -> Result<Self> {
        Ok(Self {
            database_url: required_env(DATABASE_URL_ENV)?,
            redis_url: required_env(REDIS_URL_ENV)?,
        })
    }
}

fn required_env(key: &str) -> Result<String> {
    match std::env::var(key) {
        Ok(value) if !value.is_empty() => Ok(value),
        _ => Err(anyhow!("environment variable {key} is required but unset")),
    }
}
