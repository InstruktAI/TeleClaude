//! Error types for the integration boundary.

use std::net::SocketAddr;

use event_bus::EventBusError;

/// Errors surfaced by the integration crate.
#[derive(Debug, thiserror::Error)]
pub enum IntegrationError {
    #[error("bind address is invalid: {0}")]
    InvalidBindAddress(String),
    #[error("bind address is required")]
    MissingBindAddress,
    #[error("allowed source is required")]
    MissingAllowedSource,
    #[error("provider is not configured: {0}")]
    UnknownProvider(String),
    #[error("provider secret is not configured: {0}")]
    MissingProviderSecret(String),
    #[error("signature verification failed")]
    VerificationFailed,
    #[error("provider payload normalization failed: {0}")]
    NormalizationFailed(String),
    #[error("request source is not allowed: {0}")]
    SourceNotAllowed(SocketAddr),
    #[error("HTTP server failed: {0}")]
    Server(#[from] std::io::Error),
    #[error("event bus emit failed: {0}")]
    EventBus(#[from] EventBusError),
}
