//! Error type for the event bus crate.

/// Errors surfaced by `EventBus` operations.
///
/// Wraps the upstream Redis and serde errors so callers can pattern-match on
/// the failure mode without depending on those crates directly.
#[derive(thiserror::Error, Debug)]
pub enum EventBusError {
    /// A Redis command or connection failed.
    #[error("Redis error: {0}")]
    Redis(#[from] redis::RedisError),

    /// Envelope serialization or deserialization failed.
    #[error("Serialization error: {0}")]
    Serde(#[from] serde_json::Error),

    /// The bus is not currently connected to Redis.
    #[error("connection not available")]
    Disconnected,
}
