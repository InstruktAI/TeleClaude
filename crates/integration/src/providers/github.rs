//! GitHub webhook verifier and normalizer.

use axum::http::HeaderMap;
use hmac::{Hmac, Mac};
use serde_json::{Map, Value};
use sha2::Sha256;

use crate::errors::IntegrationError;
use crate::provider::{NormalizedEvent, ProviderRequest, GITHUB_PROVIDER_NAME};

type HmacSha256 = Hmac<Sha256>;

const HUB_SIGNATURE_256_HEADER: &str = "x-hub-signature-256";
const GITHUB_EVENT_HEADER: &str = "x-github-event";
const GITHUB_DELIVERY_HEADER: &str = "x-github-delivery";
const GITHUB_SIGNATURE_PREFIX: &str = "sha256=";
const UNKNOWN_GITHUB_EVENT: &str = "unknown";

/// Concrete GitHub provider implementation.
#[derive(Debug, Clone)]
pub struct GitHubProvider {
    secret: Option<String>,
}

impl GitHubProvider {
    pub fn new(secret: Option<String>) -> Self {
        Self { secret }
    }

    pub fn verify_and_normalize(
        &self,
        request: &ProviderRequest<'_>,
    ) -> Result<NormalizedEvent, IntegrationError> {
        self.verify(request)?;
        self.normalize(request)
    }

    fn verify(&self, request: &ProviderRequest<'_>) -> Result<(), IntegrationError> {
        let Some(secret) = self.secret.as_deref().filter(|secret| !secret.is_empty()) else {
            return Err(IntegrationError::MissingProviderSecret(
                GITHUB_PROVIDER_NAME.to_string(),
            ));
        };
        let signature = header_str(request.headers, HUB_SIGNATURE_256_HEADER)
            .and_then(|value| value.strip_prefix(GITHUB_SIGNATURE_PREFIX))
            .ok_or(IntegrationError::VerificationFailed)?;
        let signature = hex::decode(signature).map_err(|_| IntegrationError::VerificationFailed)?;

        let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
            .map_err(|_| IntegrationError::VerificationFailed)?;
        mac.update(request.body);
        mac.verify_slice(&signature)
            .map_err(|_| IntegrationError::VerificationFailed)
    }

    fn normalize(
        &self,
        request: &ProviderRequest<'_>,
    ) -> Result<NormalizedEvent, IntegrationError> {
        let payload: Value = serde_json::from_slice(request.body)
            .map_err(|source| IntegrationError::NormalizationFailed(source.to_string()))?;
        let raw_event = header_str(request.headers, GITHUB_EVENT_HEADER).unwrap_or("");
        let event_type = normalized_event_type(raw_event);
        let delivery_id = header_str(request.headers, GITHUB_DELIVERY_HEADER)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| {
                IntegrationError::NormalizationFailed("missing GitHub delivery id".to_string())
            })?
            .to_string();
        let properties = properties_for(&payload, &event_type);

        Ok(NormalizedEvent {
            provider: GITHUB_PROVIDER_NAME.to_string(),
            event_name: format!("{GITHUB_PROVIDER_NAME}.{event_type}"),
            delivery_id,
            properties,
            payload,
        })
    }
}

fn header_str<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name).and_then(|value| value.to_str().ok())
}

fn normalized_event_type(raw: &str) -> String {
    let value = raw.trim().to_ascii_lowercase();
    if value.is_empty() {
        UNKNOWN_GITHUB_EVENT.to_string()
    } else {
        value
    }
}

fn properties_for(payload: &Value, event_type: &str) -> Value {
    let mut properties = Map::from_iter([
        ("repo".to_string(), repo_name(payload)),
        ("sender".to_string(), sender_login(payload)),
        ("action".to_string(), field_value(payload, "action")),
        ("ref".to_string(), field_value(payload, "ref")),
    ]);

    if event_type == "ping" {
        properties.insert("zen".to_string(), field_value(payload, "zen"));
        properties.insert("hook_id".to_string(), field_value(payload, "hook_id"));
    }

    Value::Object(properties)
}

fn repo_name(payload: &Value) -> Value {
    payload
        .get("repository")
        .and_then(Value::as_object)
        .and_then(|repo| repo.get("full_name"))
        .cloned()
        .unwrap_or(Value::Null)
}

fn sender_login(payload: &Value) -> Value {
    payload
        .get("sender")
        .and_then(Value::as_object)
        .and_then(|sender| sender.get("login"))
        .cloned()
        .unwrap_or(Value::Null)
}

fn field_value(payload: &Value, name: &str) -> Value {
    payload.get(name).cloned().unwrap_or(Value::Null)
}

#[cfg(test)]
mod tests {
    use axum::http::{HeaderMap, HeaderValue};
    use serde_json::json;

    use super::*;

    const TEST_SECRET: &str = "webhook-test-secret";
    const TEST_DELIVERY_ID: &str = "delivery-1";
    const TEST_REPO: &str = "InstruktAI/TeleClaude";
    const TEST_SENDER: &str = "mfaber";
    const TEST_REF: &str = "refs/heads/main";
    const TEST_RELEASE_ACTION: &str = "published";
    const TEST_PING_ZEN: &str = "Mind your words...";
    const PUSH_EVENT_NAME: &str = "github.push";
    const RELEASE_EVENT_NAME: &str = "github.release";
    const PING_EVENT_NAME: &str = "github.ping";
    const UNKNOWN_EVENT_NAME: &str = "github.unknown";

    fn signed_headers(body: &[u8], event: Option<&str>) -> HeaderMap {
        let mut headers = HeaderMap::new();
        let mut mac = HmacSha256::new_from_slice(TEST_SECRET.as_bytes()).expect("valid HMAC key");
        mac.update(body);
        let signature = mac.finalize().into_bytes();
        headers.insert(
            HUB_SIGNATURE_256_HEADER,
            HeaderValue::from_str(&format!(
                "{GITHUB_SIGNATURE_PREFIX}{}",
                hex::encode(signature)
            ))
            .expect("signature header"),
        );
        headers.insert(
            GITHUB_DELIVERY_HEADER,
            HeaderValue::from_static(TEST_DELIVERY_ID),
        );
        if let Some(event) = event {
            headers.insert(
                GITHUB_EVENT_HEADER,
                HeaderValue::from_str(event).expect("event header"),
            );
        }
        headers
    }

    fn verify_and_normalize(body: &[u8], headers: &HeaderMap) -> NormalizedEvent {
        GitHubProvider::new(Some(TEST_SECRET.to_string()))
            .verify_and_normalize(&ProviderRequest { headers, body })
            .expect("request verifies and normalizes")
    }

    #[test]
    fn signed_body_verifies() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"}}"#;
        let headers = signed_headers(body, Some("push"));

        let event = verify_and_normalize(body, &headers);

        assert_eq!(event.provider, GITHUB_PROVIDER_NAME);
        assert_eq!(event.delivery_id, TEST_DELIVERY_ID);
    }

    #[test]
    fn wrong_signature_rejects() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"}}"#;
        let mut headers = signed_headers(body, Some("push"));
        headers.insert(
            HUB_SIGNATURE_256_HEADER,
            HeaderValue::from_static("sha256=000000"),
        );

        let err = GitHubProvider::new(Some(TEST_SECRET.to_string()))
            .verify_and_normalize(&ProviderRequest {
                headers: &headers,
                body,
            })
            .expect_err("wrong signature rejected");

        assert!(matches!(err, IntegrationError::VerificationFailed));
    }

    #[test]
    fn missing_signature_rejects() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"}}"#;
        let headers = HeaderMap::new();

        let err = GitHubProvider::new(Some(TEST_SECRET.to_string()))
            .verify_and_normalize(&ProviderRequest {
                headers: &headers,
                body,
            })
            .expect_err("missing signature rejected");

        assert!(matches!(err, IntegrationError::VerificationFailed));
    }

    #[test]
    fn absent_secret_rejects() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"}}"#;
        let headers = signed_headers(body, Some("push"));

        let err = GitHubProvider::new(None)
            .verify_and_normalize(&ProviderRequest {
                headers: &headers,
                body,
            })
            .expect_err("absent secret rejected");

        assert!(matches!(err, IntegrationError::MissingProviderSecret(_)));
    }

    #[test]
    fn push_payload_normalizes_to_documented_properties() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"},"sender":{"login":"mfaber"},"ref":"refs/heads/main"}"#;
        let headers = signed_headers(body, Some("push"));

        let event = verify_and_normalize(body, &headers);

        assert_eq!(event.event_name, PUSH_EVENT_NAME);
        assert_eq!(event.properties["repo"], json!(TEST_REPO));
        assert_eq!(event.properties["sender"], json!(TEST_SENDER));
        assert_eq!(event.properties["action"], Value::Null);
        assert_eq!(event.properties["ref"], json!(TEST_REF));
    }

    #[test]
    fn release_payload_normalizes_action() {
        let body = br#"{"action":"published","repository":{"full_name":"InstruktAI/TeleClaude"},"sender":{"login":"mfaber"}}"#;
        let headers = signed_headers(body, Some("release"));

        let event = verify_and_normalize(body, &headers);

        assert_eq!(event.event_name, RELEASE_EVENT_NAME);
        assert_eq!(event.properties["repo"], json!(TEST_REPO));
        assert_eq!(event.properties["sender"], json!(TEST_SENDER));
        assert_eq!(event.properties["action"], json!(TEST_RELEASE_ACTION));
        assert_eq!(event.properties["ref"], Value::Null);
    }

    #[test]
    fn ping_payload_passes_through_handshake_properties() {
        let body = br#"{"zen":"Mind your words...","hook_id":12345}"#;
        let headers = signed_headers(body, Some("ping"));

        let event = verify_and_normalize(body, &headers);

        assert_eq!(event.event_name, PING_EVENT_NAME);
        assert_eq!(event.properties["zen"], json!(TEST_PING_ZEN));
        assert_eq!(event.properties["hook_id"], json!(12345));
    }

    #[test]
    fn missing_event_header_normalizes_to_unknown() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"}}"#;
        let headers = signed_headers(body, None);

        let event = verify_and_normalize(body, &headers);

        assert_eq!(event.event_name, UNKNOWN_EVENT_NAME);
    }

    #[test]
    fn titled_and_lowercase_event_headers_normalize_identically() {
        let body = br#"{"repository":{"full_name":"InstruktAI/TeleClaude"}}"#;
        let titled = signed_headers(body, Some("push"));
        let mut lowercase = signed_headers(body, None);
        lowercase.insert("x-github-event", HeaderValue::from_static("push"));

        let titled_event = verify_and_normalize(body, &titled);
        let lowercase_event = verify_and_normalize(body, &lowercase);

        assert_eq!(titled_event.event_name, lowercase_event.event_name);
        assert_eq!(lowercase_event.event_name, PUSH_EVENT_NAME);
    }

    #[test]
    fn malformed_repository_or_sender_normalizes_to_null_properties() {
        let body = br#"{"repository":"malformed","sender":"malformed"}"#;
        let headers = signed_headers(body, Some("push"));

        let event = verify_and_normalize(body, &headers);

        assert_eq!(event.properties["repo"], Value::Null);
        assert_eq!(event.properties["sender"], Value::Null);
    }
}
