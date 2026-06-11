//! Environment / runtime configuration for `telec-cli`.
//!
//! Loads `DATABASE_URL`, `CLUSTER_REDIS_URL`, the deprecated `REDIS_URL`
//! alias, and optional `PUBLIC_REDIS_URL` from the process environment.
//! The caller (usually `main`) is expected to have already loaded `.env`
//! via `dotenvy::dotenv().ok()` so these lookups see overlay values.

use anyhow::{anyhow, Result};
use tracing::warn;

/// Environment variable holding the Postgres connection string.
pub const DATABASE_URL_ENV: &str = "DATABASE_URL";

/// Environment variable holding the deprecated Redis connection string alias.
pub const REDIS_URL_ENV: &str = "REDIS_URL";

/// Environment variable holding the cluster bus Redis connection string.
pub const CLUSTER_REDIS_URL_ENV: &str = "CLUSTER_REDIS_URL";

/// Environment variable holding the optional public Redis connection string.
pub const PUBLIC_REDIS_URL_ENV: &str = "PUBLIC_REDIS_URL";

/// Required runtime configuration loaded from the environment.
#[derive(Debug, Clone)]
pub struct CliConfig {
    /// Postgres connection string (e.g. `postgres://user:pass@host/db`).
    pub database_url: String,
    /// Canonical cluster bus Redis connection string.
    pub cluster_redis_url: Option<String>,
    /// Deprecated alias for [`CLUSTER_REDIS_URL_ENV`].
    pub redis_url: Option<String>,
    /// Optional public federation Redis connection string.
    pub public_redis_url: Option<String>,
}

impl CliConfig {
    /// Read [`CliConfig`] from the process environment.
    ///
    /// Returns an error when the database URL is absent, or when neither
    /// [`CLUSTER_REDIS_URL_ENV`] nor [`REDIS_URL_ENV`] is present.
    pub fn from_env() -> Result<Self> {
        let database_url = required_env(DATABASE_URL_ENV)?;
        let cluster_redis_url = optional_env(CLUSTER_REDIS_URL_ENV);
        let redis_url = optional_env(REDIS_URL_ENV);

        if cluster_redis_url.is_none() && redis_url.is_none() {
            return Err(anyhow!(
                "environment variable {CLUSTER_REDIS_URL_ENV} or {REDIS_URL_ENV} is required but both are unset"
            ));
        }

        if cluster_redis_url.is_none() && redis_url.is_some() {
            warn!("{REDIS_URL_ENV} is deprecated; set {CLUSTER_REDIS_URL_ENV} instead");
        }

        Ok(Self {
            database_url,
            cluster_redis_url,
            redis_url,
            public_redis_url: optional_env(PUBLIC_REDIS_URL_ENV),
        })
    }

    /// Resolve the cluster bus Redis URL from the canonical variable or
    /// its deprecated alias.
    pub fn cluster_bus_url(&self) -> Result<String> {
        self.cluster_redis_url
            .clone()
            .or_else(|| self.redis_url.clone())
            .ok_or_else(|| {
                anyhow!(
                    "environment variable {CLUSTER_REDIS_URL_ENV} or {REDIS_URL_ENV} is required but both are unset"
                )
            })
    }
}

fn required_env(key: &str) -> Result<String> {
    match std::env::var(key) {
        Ok(value) if !value.is_empty() => Ok(value),
        _ => Err(anyhow!("environment variable {key} is required but unset")),
    }
}

fn optional_env(key: &str) -> Option<String> {
    match std::env::var(key) {
        Ok(value) if !value.is_empty() => Some(value),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Mutex, MutexGuard, OnceLock};

    use super::*;

    const TEST_DATABASE_URL: &str = "postgres://telec:test@localhost/telec";
    const TEST_CLUSTER_REDIS_URL: &str = "redis://cluster.example:6379";
    const TEST_REDIS_URL: &str = "redis://legacy.example:6379";
    const TEST_PUBLIC_REDIS_URL: &str = "redis://public.example:6379";

    fn env_lock() -> MutexGuard<'static, ()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
            .lock()
            .expect("env test lock is not poisoned")
    }

    struct EnvGuard {
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl EnvGuard {
        fn clean() -> Self {
            let keys = [
                DATABASE_URL_ENV,
                CLUSTER_REDIS_URL_ENV,
                REDIS_URL_ENV,
                PUBLIC_REDIS_URL_ENV,
            ];
            let saved = keys
                .into_iter()
                .map(|key| (key, std::env::var(key).ok()))
                .collect();

            for key in keys {
                std::env::remove_var(key);
            }
            std::env::set_var(DATABASE_URL_ENV, TEST_DATABASE_URL);

            Self { saved }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            for (key, value) in &self.saved {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    #[test]
    fn cluster_redis_url_alone_resolves_cluster_bus() {
        let _lock = env_lock();
        let _env = EnvGuard::clean();
        std::env::set_var(CLUSTER_REDIS_URL_ENV, TEST_CLUSTER_REDIS_URL);

        let cfg = CliConfig::from_env().expect("cluster URL config loads");

        assert_eq!(
            cfg.cluster_redis_url.as_deref(),
            Some(TEST_CLUSTER_REDIS_URL)
        );
        assert!(cfg.redis_url.is_none());
        assert_eq!(cfg.cluster_bus_url().unwrap(), TEST_CLUSTER_REDIS_URL);
    }

    #[test]
    fn redis_url_alias_alone_resolves_cluster_bus() {
        let _lock = env_lock();
        let _env = EnvGuard::clean();
        std::env::set_var(REDIS_URL_ENV, TEST_REDIS_URL);

        let cfg = CliConfig::from_env().expect("legacy Redis URL config loads");

        assert!(cfg.cluster_redis_url.is_none());
        assert_eq!(cfg.redis_url.as_deref(), Some(TEST_REDIS_URL));
        assert_eq!(cfg.cluster_bus_url().unwrap(), TEST_REDIS_URL);
    }

    #[test]
    fn both_cluster_bus_names_unset_error_names_both() {
        let _lock = env_lock();
        let _env = EnvGuard::clean();

        let err = CliConfig::from_env().unwrap_err();

        insta::assert_snapshot!(err.to_string(), @"environment variable CLUSTER_REDIS_URL or REDIS_URL is required but both are unset");
    }

    #[test]
    fn public_redis_url_populates_when_set() {
        let _lock = env_lock();
        let _env = EnvGuard::clean();
        std::env::set_var(CLUSTER_REDIS_URL_ENV, TEST_CLUSTER_REDIS_URL);

        let cfg = CliConfig::from_env().expect("cluster URL config loads");
        assert!(cfg.public_redis_url.is_none());

        std::env::set_var(PUBLIC_REDIS_URL_ENV, TEST_PUBLIC_REDIS_URL);
        let cfg = CliConfig::from_env().expect("public URL config loads");

        assert_eq!(cfg.public_redis_url.as_deref(), Some(TEST_PUBLIC_REDIS_URL));
    }
}
