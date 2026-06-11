//! Integration test for `EventBus` against a real Redis.
//!
//! Gated with `#[ignore]` by default. Run with:
//!
//! ```sh
//! REDIS_URL=redis://localhost:6379 \
//!   cargo test -p event-bus -- --ignored
//! ```

use chrono::Utc;
use event_bus::{
    envelope::ENVELOPE_SCHEMA_VERSION, EventBus, EventBusConfig, EventEnvelope, EventScope,
    SubscriptionScopes,
};
use futures::StreamExt;
use serde_json::json;
use std::collections::HashSet;
use std::time::Duration;
use tokio::time::timeout;

fn redis_url() -> String {
    std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string())
}

fn event_bus_config(url: &str, public: Option<&str>) -> EventBusConfig {
    EventBusConfig {
        cluster_bus: url.to_string(),
        public: public.map(str::to_string),
    }
}

fn unique_channel(label: &str) -> String {
    format!(
        "event_bus_test.{label}.{}",
        Utc::now().timestamp_nanos_opt().unwrap_or(0)
    )
}

fn envelope(channel: &str, idempotency_key: &str, scope: EventScope) -> EventEnvelope {
    EventEnvelope {
        schema_version: ENVELOPE_SCHEMA_VERSION,
        scope,
        channel: channel.to_string(),
        idempotency_key: idempotency_key.to_string(),
        emitted_at: Utc::now(),
        principal: Some(identity::Principal::Human {
            email: "test-user@example.com".to_owned(),
            role: identity::Role::Owner,
        }),
        payload: json!({"scope": scope}),
    }
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn local_cluster_and_all_subscriptions_are_isolated_on_shared_bus() {
    let url = redis_url();

    // Subscriber must be ready before the publisher emits — pub/sub drops
    // messages with no live subscriber.
    let bus_sub = EventBus::connect(event_bus_config(&url, None))
        .await
        .expect("subscriber connects to Redis");
    let bus_pub = EventBus::connect(event_bus_config(&url, None))
        .await
        .expect("publisher connects to Redis");

    assert!(bus_sub.has_scope(EventScope::Local));
    assert!(bus_sub.has_scope(EventScope::Cluster));
    assert!(!bus_sub.has_scope(EventScope::Public));

    let channel = unique_channel("scope_isolation");
    let local_stream = bus_sub
        .subscribe(&channel, SubscriptionScopes::local())
        .await
        .expect("local subscribe succeeds");
    let cluster_stream = bus_sub
        .subscribe(&channel, SubscriptionScopes::cluster())
        .await
        .expect("cluster subscribe succeeds");
    let all_stream = bus_sub
        .subscribe(&channel, SubscriptionScopes::all())
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(local_stream);
    futures::pin_mut!(cluster_stream);
    futures::pin_mut!(all_stream);

    // Give Redis a moment to register the subscription before publishing.
    tokio::time::sleep(Duration::from_millis(50)).await;

    let local = envelope(&channel, "test-key-local", EventScope::Local);
    let cluster = envelope(&channel, "test-key-cluster", EventScope::Cluster);

    bus_pub.emit(&local).await.expect("local emit succeeds");
    bus_pub.emit(&cluster).await.expect("cluster emit succeeds");

    let local_received = timeout(Duration::from_secs(2), local_stream.next())
        .await
        .expect("local envelope arrives within timeout")
        .expect("stream yields a message")
        .expect("envelope decodes");
    assert_eq!(local_received.scope, EventScope::Local);
    assert_eq!(local_received.idempotency_key, local.idempotency_key);

    let no_second_local = timeout(Duration::from_millis(200), local_stream.next()).await;
    assert!(no_second_local.is_err());

    let cluster_received = timeout(Duration::from_secs(2), cluster_stream.next())
        .await
        .expect("cluster envelope arrives within timeout")
        .expect("stream yields a message")
        .expect("envelope decodes");
    assert_eq!(cluster_received.scope, EventScope::Cluster);
    assert_eq!(cluster_received.idempotency_key, cluster.idempotency_key);

    let no_second_cluster = timeout(Duration::from_millis(200), cluster_stream.next()).await;
    assert!(no_second_cluster.is_err());

    let all_first = timeout(Duration::from_secs(2), all_stream.next())
        .await
        .expect("first all-scope envelope arrives within timeout")
        .expect("stream yields a message")
        .expect("envelope decodes");
    let all_second = timeout(Duration::from_secs(2), all_stream.next())
        .await
        .expect("second all-scope envelope arrives within timeout")
        .expect("stream yields a message")
        .expect("envelope decodes");

    let all_scopes = HashSet::from([all_first.scope, all_second.scope]);
    assert_eq!(
        all_scopes,
        HashSet::from([EventScope::Local, EventScope::Cluster])
    );
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn public_emit_without_public_redis_is_dropped() {
    let url = redis_url();
    let bus_sub = EventBus::connect(event_bus_config(&url, None))
        .await
        .expect("subscriber connects to Redis");
    let bus_pub = EventBus::connect(event_bus_config(&url, None))
        .await
        .expect("publisher connects to Redis");

    let channel = unique_channel("public_drop");
    let stream = bus_sub
        .subscribe(&channel, SubscriptionScopes::all())
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(stream);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let public = envelope(&channel, "test-key-public-drop", EventScope::Public);
    bus_pub.emit(&public).await.expect("public emit is a no-op");

    let no_delivery = timeout(Duration::from_millis(200), stream.next()).await;
    assert!(no_delivery.is_err());
}

#[tokio::test]
#[ignore = "requires a running Redis at REDIS_URL or localhost:6379"]
async fn cluster_and_public_overlap_is_deduped_by_idempotency_key() {
    let url = redis_url();
    let bus_sub = EventBus::connect(event_bus_config(&url, Some(&url)))
        .await
        .expect("subscriber connects to Redis");
    let bus_pub = EventBus::connect(event_bus_config(&url, Some(&url)))
        .await
        .expect("publisher connects to Redis");

    assert!(bus_sub.has_scope(EventScope::Public));

    let channel = unique_channel("federation_dedup");
    let stream = bus_sub
        .subscribe(
            &channel,
            SubscriptionScopes::cluster().with(EventScope::Public),
        )
        .await
        .expect("subscribe succeeds");
    futures::pin_mut!(stream);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let cluster = envelope(&channel, "test-key-federated", EventScope::Cluster);
    let public = envelope(&channel, "test-key-federated", EventScope::Public);
    bus_pub.emit(&cluster).await.expect("cluster emit succeeds");
    bus_pub.emit(&public).await.expect("public emit succeeds");

    let received = timeout(Duration::from_secs(2), stream.next())
        .await
        .expect("envelope arrives within timeout")
        .expect("stream yields a message")
        .expect("envelope decodes");
    assert_eq!(received.idempotency_key, "test-key-federated");

    let no_duplicate = timeout(Duration::from_millis(200), stream.next()).await;
    assert!(no_duplicate.is_err());
}
