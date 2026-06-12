//! Provider registry and normalized event model.

use std::collections::BTreeMap;

use axum::http::HeaderMap;
use config::models::IngressConfig;
use serde::{Deserialize, Serialize};

use crate::errors::IntegrationError;
use crate::providers::github::GitHubProvider;

/// Built-in GitHub provider key.
pub const GITHUB_PROVIDER_NAME: &str = "github";

/// Inbound request data passed to a concrete provider.
pub struct ProviderRequest<'a> {
    /// HTTP request headers from the provider.
    pub headers: &'a HeaderMap,
    /// Raw request body bytes used for signature verification.
    pub body: &'a [u8],
}

/// Provider-normalized event carried by the relay payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NormalizedEvent {
    pub provider: String,
    pub event_name: String,
    pub delivery_id: String,
    pub properties: serde_json::Value,
    pub payload: serde_json::Value,
}

/// Concrete provider implementation.
#[derive(Debug, Clone)]
pub enum Provider {
    GitHub(GitHubProvider),
}

impl Provider {
    /// Verify and normalize one provider request.
    pub fn verify_and_normalize(
        &self,
        request: &ProviderRequest<'_>,
    ) -> Result<NormalizedEvent, IntegrationError> {
        match self {
            Self::GitHub(provider) => provider.verify_and_normalize(request),
        }
    }
}

/// Provider lookup table keyed by provider name.
#[derive(Debug, Clone, Default)]
pub struct ProviderRegistry {
    providers: BTreeMap<String, Provider>,
}

impl ProviderRegistry {
    /// Build a registry from the typed ingress config.
    pub fn from_config(config: &IngressConfig) -> Self {
        let providers = config
            .providers
            .iter()
            .filter_map(|(name, provider)| {
                if name == GITHUB_PROVIDER_NAME {
                    Some((
                        name.clone(),
                        Provider::GitHub(GitHubProvider::new(provider.secret.clone())),
                    ))
                } else {
                    None
                }
            })
            .collect();

        Self { providers }
    }

    /// Build a registry containing the GitHub provider.
    pub fn with_github(secret: impl Into<String>) -> Self {
        let mut providers = BTreeMap::new();
        providers.insert(
            GITHUB_PROVIDER_NAME.to_string(),
            Provider::GitHub(GitHubProvider::new(Some(secret.into()))),
        );
        Self { providers }
    }

    /// Resolve a configured provider by name.
    pub fn resolve(&self, name: &str) -> Option<&Provider> {
        self.providers.get(name)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use config::models::{IngressConfig, IngressProvider};

    use super::*;

    #[test]
    fn registry_resolves_configured_github_provider() {
        let config = IngressConfig {
            providers: BTreeMap::from([(
                GITHUB_PROVIDER_NAME.to_string(),
                IngressProvider {
                    secret: Some("test-secret".to_string()),
                    ..IngressProvider::default()
                },
            )]),
            ..IngressConfig::default()
        };

        let registry = ProviderRegistry::from_config(&config);

        assert!(matches!(
            registry.resolve(GITHUB_PROVIDER_NAME),
            Some(Provider::GitHub(_))
        ));
    }

    #[test]
    fn registry_fails_closed_for_unknown_provider_name() {
        let registry = ProviderRegistry::with_github("test-secret");

        assert!(registry.resolve("unknown").is_none());
    }
}
