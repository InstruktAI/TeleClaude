//! integration — inbound and outbound external provider boundary.
//!
//! This crate owns provider-facing protocol logic. Runtime lifecycle wiring
//! belongs to the binary that hosts it.

pub mod errors;
pub mod ingress;
pub mod provider;
pub mod providers;
pub mod relay;

pub use errors::IntegrationError;
pub use ingress::IngressServer;
pub use provider::{
    NormalizedEvent, Provider, ProviderRegistry, ProviderRequest, GITHUB_PROVIDER_NAME,
};
pub use relay::{
    relay_verified_event, EventBusRelay, VerifiedEventRelay, INTEGRATION_INBOX_RECEIVED,
};
