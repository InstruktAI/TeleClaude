//! Integration test for `EventBus` against a real Redis.
//!
//! Gated with `#[ignore]` by default. Run with:
//!
//! ```sh
//! REDIS_URL=redis://localhost:6379 \
//!   cargo test -p event-bus -- --ignored
//! ```

use chrono::Utc;
use event_bus::{EventBus, EventEnvelope};
use futures::StreamExt;
use serde_json::json;
use std::time::Duration;
use tokio::time::timeout;

fn redis_url() -> String {
    std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string())
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn emit_then_subscribe_round_trips_envelope_via_pubsub() {
    let url = redis_url();

    // Subscriber must be ready before the publisher emits — pub/sub drops
    // messages with no live subscriber.
    let bus_sub = EventBus::connect(&url)
        .await
        .expect("subscriber connects to Redis");
    let bus_pub = EventBus::connect(&url)
        .await
        .expect("publisher connects to Redis");

    let channel = format!(
        "event_bus_test.round_trip.{}",
        Utc::now().timestamp_nanos_opt().unwrap_or(0)
    );
    let mut stream = bus_sub
        .subscribe(&channel)
        .await
        .expect("subscribe succeeds");

    // Give Redis a moment to register the subscription before publishing.
    tokio::time::sleep(Duration::from_millis(50)).await;

    let envelope = EventEnvelope {
        channel: channel.clone(),
        idempotency_key: "test-key-1".to_string(),
        emitted_at: Utc::now(),
        principal: Some(identity::Principal::Human {
            email: "test-user@example.com".to_owned(),
            role: identity::Role::Owner,
        }),
        payload: json!({"hello": "world"}),
    };

    bus_pub.emit(&envelope).await.expect("emit succeeds");

    let received = timeout(Duration::from_secs(2), stream.next())
        .await
        .expect("envelope arrives within timeout")
        .expect("stream yields a message")
        .expect("envelope decodes");

    assert_eq!(received.channel, envelope.channel);
    assert_eq!(received.idempotency_key, envelope.idempotency_key);
    assert_eq!(received.payload, envelope.payload);
}
