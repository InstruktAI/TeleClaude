//! Redis-backed ingress relay tests.
//!
//! Gated with `#[ignore]` by default. Run with:
//!
//! ```sh
//! REDIS_URL=redis://localhost:6379 cargo test -p integration -- --ignored --test-threads=1
//! ```

use std::collections::BTreeSet;
use std::io::ErrorKind;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use event_bus::{EventBus, EventBusConfig, SubscriptionScopes};
use futures::StreamExt;
use hmac::{Hmac, Mac};
use integration::{IngressServer, ProviderRegistry, INTEGRATION_INBOX_RECEIVED};
use serde_json::json;
use sha2::Sha256;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::oneshot;
use tokio::time::timeout;
use tower::ServiceExt;

type HmacSha256 = Hmac<Sha256>;

const TEST_SECRET: &str = "webhook-test-secret";
const TEST_SOURCE: IpAddr = IpAddr::V4(Ipv4Addr::LOCALHOST);
const TEST_BIND: SocketAddr = SocketAddr::new(IpAddr::V4(Ipv4Addr::new(192, 0, 2, 10)), 8080);
const TEST_EVENT_PATH: &str = "/webhooks/github";
const TEST_FORWARDED_SOURCE: &str = "203.0.113.250";
const TEST_RELEASE_ACTION: &str = "published";
const TEST_PING_ZEN: &str = "Mind your words...";

fn redis_url() -> String {
    std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string())
}

fn event_bus_config() -> EventBusConfig {
    EventBusConfig {
        cluster_bus: redis_url(),
        public: None,
    }
}

fn release_body() -> Vec<u8> {
    serde_json::to_vec(&json!({
        "action": TEST_RELEASE_ACTION,
        "repository": {"full_name": "InstruktAI/TeleClaude"},
        "sender": {"login": "mfaber"}
    }))
    .expect("release body serializes")
}

fn ping_body() -> Vec<u8> {
    serde_json::to_vec(&json!({
        "zen": TEST_PING_ZEN,
        "hook_id": 12345
    }))
    .expect("ping body serializes")
}

fn signature(body: &[u8]) -> String {
    let mut mac = HmacSha256::new_from_slice(TEST_SECRET.as_bytes()).expect("valid HMAC key");
    mac.update(body);
    format!("sha256={}", hex::encode(mac.finalize().into_bytes()))
}

async fn request(
    allowed_sources: BTreeSet<IpAddr>,
    peer: IpAddr,
    body: Vec<u8>,
    event: &str,
    delivery_id: &str,
    signature: &str,
) -> axum::response::Response {
    let bus = Arc::new(
        EventBus::connect(event_bus_config())
            .await
            .expect("event bus connects"),
    );
    let ingress = IngressServer::new(
        TEST_BIND,
        allowed_sources,
        ProviderRegistry::with_github(TEST_SECRET),
        bus,
    )
    .expect("ingress server builds");
    let peer = SocketAddr::new(peer, 51234);
    let mut request = axum::http::Request::post(TEST_EVENT_PATH)
        .header("x-github-event", event)
        .header("x-github-delivery", delivery_id)
        .header("x-hub-signature-256", signature)
        .header("x-forwarded-for", "203.0.113.250")
        .body(axum::body::Body::from(body))
        .expect("request builds");
    request
        .extensions_mut()
        .insert(axum::extract::ConnectInfo(peer));

    ingress
        .router()
        .oneshot(request)
        .await
        .expect("ingress handles request")
}

async fn tcp_request_status(
    allowed_sources: BTreeSet<IpAddr>,
    body: Vec<u8>,
    event: &str,
    delivery_id: &str,
    signature: &str,
    forwarded_for: &str,
) -> axum::http::StatusCode {
    let bus = Arc::new(
        EventBus::connect(event_bus_config())
            .await
            .expect("event bus connects"),
    );
    let ingress = IngressServer::new(
        SocketAddr::new(TEST_SOURCE, 0),
        allowed_sources,
        ProviderRegistry::with_github(TEST_SECRET),
        bus,
    )
    .expect("ingress server builds");
    let listener = ingress.bind().await.expect("ingress binds");
    let addr = listener.local_addr().expect("listener exposes local addr");
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let server = tokio::spawn(listener.serve(async move {
        shutdown_rx.await.expect("shutdown signal received");
    }));

    let status = send_tcp_webhook(addr, body, event, delivery_id, signature, forwarded_for).await;

    shutdown_tx.send(()).expect("shutdown signal sends");
    timeout(Duration::from_secs(2), server)
        .await
        .expect("server stops")
        .expect("server task joins")
        .expect("server exits cleanly");
    status
}

async fn send_tcp_webhook(
    addr: SocketAddr,
    body: Vec<u8>,
    event: &str,
    delivery_id: &str,
    signature: &str,
    forwarded_for: &str,
) -> axum::http::StatusCode {
    let mut stream = tokio::net::TcpStream::connect(addr)
        .await
        .expect("TCP client connects");
    let headers = format!(
        "POST {TEST_EVENT_PATH} HTTP/1.1\r\n\
         Host: {addr}\r\n\
         x-github-event: {event}\r\n\
         x-github-delivery: {delivery_id}\r\n\
         x-hub-signature-256: {signature}\r\n\
         x-forwarded-for: {forwarded_for}\r\n\
         content-length: {}\r\n\
         connection: close\r\n\
         \r\n",
        body.len()
    );
    stream
        .write_all(headers.as_bytes())
        .await
        .expect("request headers write");
    stream.write_all(&body).await.expect("request body writes");

    let mut response = Vec::new();
    let mut buffer = [0_u8; 1024];
    loop {
        let read = timeout(Duration::from_secs(2), stream.read(&mut buffer))
            .await
            .expect("response arrives");
        match read {
            Ok(0) => break,
            Ok(count) => response.extend_from_slice(&buffer[..count]),
            Err(error) if error.kind() == ErrorKind::ConnectionReset && !response.is_empty() => {
                break;
            }
            Err(error) => panic!("response reads: {error}"),
        }
    }
    response_status(&response)
}

fn response_status(response: &[u8]) -> axum::http::StatusCode {
    let first_line_end = response
        .windows(2)
        .position(|window| window == b"\r\n")
        .expect("response includes a status line");
    let status_line = &response[..first_line_end];
    let code_start = status_line
        .iter()
        .position(|byte| *byte == b' ')
        .expect("status line includes status code")
        + 1;
    let code_end = status_line[code_start..]
        .iter()
        .position(|byte| *byte == b' ')
        .map(|offset| code_start + offset)
        .unwrap_or(status_line.len());
    let code = std::str::from_utf8(&status_line[code_start..code_end])
        .expect("status code is utf8")
        .parse()
        .expect("status code is numeric");
    axum::http::StatusCode::from_u16(code).expect("status code is valid")
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn verified_release_relay_emits_cluster_event() {
    // spec: single-ingress-webhook-termination UC-SIT-1
    // spec: single-ingress-webhook-termination UC-SIT-2
    let subscriber = EventBus::connect(event_bus_config())
        .await
        .expect("subscriber connects");
    let stream = subscriber
        .subscribe(INTEGRATION_INBOX_RECEIVED, SubscriptionScopes::cluster())
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(stream);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let body = release_body();
    let delivery_id = format!("delivery-{}", Utc::now().timestamp_nanos_opt().unwrap_or(0));
    let response = request(
        BTreeSet::from([TEST_SOURCE]),
        TEST_SOURCE,
        body.clone(),
        "release",
        &delivery_id,
        &signature(&body),
    )
    .await;

    assert_eq!(response.status(), axum::http::StatusCode::ACCEPTED);

    let envelope = timeout(Duration::from_secs(2), stream.next())
        .await
        .expect("event arrives")
        .expect("stream yields")
        .expect("envelope decodes");

    assert_eq!(envelope.channel, INTEGRATION_INBOX_RECEIVED);
    assert_eq!(envelope.idempotency_key, delivery_id);
    assert_eq!(envelope.payload["provider"], json!("github"));
    assert_eq!(envelope.payload["event_name"], json!("github.release"));
    assert_eq!(envelope.payload["verified"], json!(true));
    assert_eq!(
        envelope.payload["properties"]["action"],
        json!(TEST_RELEASE_ACTION)
    );
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn invalid_signature_rejects_without_relay() {
    // spec: single-ingress-webhook-termination UC-SIT-3
    let subscriber = EventBus::connect(event_bus_config())
        .await
        .expect("subscriber connects");
    let stream = subscriber
        .subscribe(INTEGRATION_INBOX_RECEIVED, SubscriptionScopes::cluster())
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(stream);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let body = release_body();
    let response = request(
        BTreeSet::from([TEST_SOURCE]),
        TEST_SOURCE,
        body,
        "release",
        "bad-delivery",
        "sha256=00",
    )
    .await;

    assert_eq!(response.status(), axum::http::StatusCode::FORBIDDEN);
    let no_relay = timeout(Duration::from_millis(200), stream.next()).await;
    assert!(no_relay.is_err());
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn wrong_source_is_refused_before_processing() {
    // spec: single-ingress-webhook-termination UC-SIT-4
    let subscriber = EventBus::connect(event_bus_config())
        .await
        .expect("subscriber connects");
    let stream = subscriber
        .subscribe(INTEGRATION_INBOX_RECEIVED, SubscriptionScopes::cluster())
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(stream);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let disallowed = IpAddr::V4(Ipv4Addr::new(203, 0, 113, 1));
    let body = release_body();
    let response = request(
        BTreeSet::from([disallowed]),
        TEST_SOURCE,
        body.clone(),
        "release",
        "wrong-source",
        &signature(&body),
    )
    .await;

    assert_eq!(response.status(), axum::http::StatusCode::FORBIDDEN);
    let no_relay = timeout(Duration::from_millis(200), stream.next()).await;
    assert!(no_relay.is_err());
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn real_tcp_source_restriction_uses_socket_peer_not_forwarded_headers() {
    // spec: single-ingress-webhook-termination UC-SIT-4
    let body = release_body();
    let accepted_delivery = format!(
        "tcp-accepted-{}",
        Utc::now().timestamp_nanos_opt().unwrap_or(0)
    );
    let accepted = tcp_request_status(
        BTreeSet::from([TEST_SOURCE]),
        body.clone(),
        "release",
        &accepted_delivery,
        &signature(&body),
        TEST_FORWARDED_SOURCE,
    )
    .await;

    assert_eq!(accepted, axum::http::StatusCode::ACCEPTED);

    let rejected_delivery = format!(
        "tcp-rejected-{}",
        Utc::now().timestamp_nanos_opt().unwrap_or(0)
    );
    let rejected = tcp_request_status(
        BTreeSet::from([IpAddr::V4(Ipv4Addr::new(203, 0, 113, 250))]),
        body.clone(),
        "release",
        &rejected_delivery,
        &signature(&body),
        &TEST_SOURCE.to_string(),
    )
    .await;

    assert_eq!(rejected, axum::http::StatusCode::FORBIDDEN);
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn ping_payload_is_relayed_as_normalized_github_event() {
    // spec: github-webhook-normalization UC-GH3
    let subscriber = EventBus::connect(event_bus_config())
        .await
        .expect("subscriber connects");
    let stream = subscriber
        .subscribe(INTEGRATION_INBOX_RECEIVED, SubscriptionScopes::cluster())
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(stream);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let body = ping_body();
    let delivery_id = format!("ping-{}", Utc::now().timestamp_nanos_opt().unwrap_or(0));
    let response = request(
        BTreeSet::from([TEST_SOURCE]),
        TEST_SOURCE,
        body.clone(),
        "ping",
        &delivery_id,
        &signature(&body),
    )
    .await;

    assert_eq!(response.status(), axum::http::StatusCode::ACCEPTED);

    let envelope = timeout(Duration::from_secs(2), stream.next())
        .await
        .expect("event arrives")
        .expect("stream yields")
        .expect("envelope decodes");

    assert_eq!(envelope.payload["event_name"], json!("github.ping"));
    assert_eq!(envelope.payload["properties"]["zen"], json!(TEST_PING_ZEN));
}
