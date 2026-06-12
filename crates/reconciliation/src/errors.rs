use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum ReconciliationError {
    #[error(transparent)]
    Config(#[from] config::ConfigError),
    #[error(transparent)]
    EventBus(#[from] event_bus::EventBusError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Redis(#[from] redis::RedisError),
    #[error(transparent)]
    Serde(#[from] serde_json::Error),
    #[error("invalid target version: {0}")]
    InvalidTargetVersion(String),
    #[error("invalid heartbeat ttl: {0:?}")]
    InvalidHeartbeatTtl(std::time::Duration),
    #[error("invalid heartbeat entry: {0}")]
    InvalidHeartbeatEntry(String),
    #[error("ledger parent directory is unavailable for {0}")]
    MissingLedgerParent(PathBuf),
}
