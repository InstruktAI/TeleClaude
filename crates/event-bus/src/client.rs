//! `EventBus` — the connection manager and public API of the crate.
//!
//! `emit` writes envelopes to two Redis surfaces:
//! 1. **Streams** (`XADD events:<channel>`) — durable, consumer-group friendly,
//!    used for replay and late subscribers.
//! 2. **Pub/Sub** (`PUBLISH <channel>`) — ephemeral live notifications for
//!    subscribers that are currently alive.
//!
//! `subscribe` opens a dedicated Redis pub/sub connection using `PSUBSCRIBE`
//! so callers can match channel patterns like `workflow.*`. The returned
//! `Stream` yields decoded envelopes until the underlying connection drops.
//!
//! Idempotency tracking is intentionally in-memory for the MVP. It dedups
//! handler successes within a single process for the configured TTL. A future
//! revision should move this into Redis itself so handler-success state is
//! shared across processes — until then, consumer-group redelivery across
//! restarts is **not** guaranteed at-most-once.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use futures::{Stream, StreamExt};
use redis::aio::ConnectionManager;
use redis::Client;
use tokio::sync::Mutex;

use crate::envelope::EventEnvelope;
use crate::errors::EventBusError;

/// How long a handled idempotency key is remembered before the entry is
/// evicted from the in-memory cache.
const IDEMPOTENCY_TTL: Duration = Duration::from_secs(60 * 60);

/// Prefix used for the per-channel Redis Stream key.
const STREAM_PREFIX: &str = "events:";

/// Field name used inside the Redis Stream entry for the serialized envelope.
const STREAM_FIELD: &str = "payload";

/// In-memory cache of idempotency keys recorded as successfully handled.
///
/// Each entry expires `IDEMPOTENCY_TTL` after insertion. Eviction is lazy:
/// expired entries are dropped the next time the cache is touched.
#[derive(Debug, Default)]
struct IdempotencyCache {
    entries: HashMap<String, Instant>,
    ttl: Duration,
}

impl IdempotencyCache {
    fn with_ttl(ttl: Duration) -> Self {
        Self {
            entries: HashMap::new(),
            ttl,
        }
    }

    fn mark(&mut self, key: &str) {
        self.purge_expired();
        self.entries.insert(key.to_string(), Instant::now());
    }

    fn contains(&mut self, key: &str) -> bool {
        self.purge_expired();
        self.entries.contains_key(key)
    }

    fn purge_expired(&mut self) {
        let ttl = self.ttl;
        self.entries
            .retain(|_, recorded_at| recorded_at.elapsed() < ttl);
    }
}

/// Redis-backed event bus.
///
/// Holds:
/// - a `Client` used to spawn dedicated pub/sub connections on demand,
/// - a multiplexed `ConnectionManager` for emit (XADD + PUBLISH),
/// - an in-memory idempotency-key cache.
///
/// Wrap in an `Arc` to share across tasks/services.
pub struct EventBus {
    client: Client,
    conn: Mutex<ConnectionManager>,
    seen: Mutex<IdempotencyCache>,
}

impl EventBus {
    /// Connect to Redis at `redis_url` (e.g. `redis://localhost:6379`).
    pub async fn connect(redis_url: &str) -> Result<Self, EventBusError> {
        let client = Client::open(redis_url)?;
        let conn = ConnectionManager::new(client.clone()).await?;
        Ok(Self {
            client,
            conn: Mutex::new(conn),
            seen: Mutex::new(IdempotencyCache::with_ttl(IDEMPOTENCY_TTL)),
        })
    }

    /// Emit an envelope to Redis: append to the per-channel Stream, then
    /// PUBLISH for live subscribers.
    pub async fn emit(&self, envelope: &EventEnvelope) -> Result<(), EventBusError> {
        let payload = serde_json::to_string(envelope)?;
        let stream_key = format!("{}{}", STREAM_PREFIX, envelope.channel);

        let mut conn = self.conn.lock().await;
        let _: String = redis::cmd("XADD")
            .arg(&stream_key)
            .arg("*")
            .arg(STREAM_FIELD)
            .arg(&payload)
            .query_async(&mut *conn)
            .await?;
        let _: i64 = redis::cmd("PUBLISH")
            .arg(&envelope.channel)
            .arg(&payload)
            .query_async(&mut *conn)
            .await?;
        Ok(())
    }

    /// Subscribe to a channel pattern via Redis `PSUBSCRIBE`.
    ///
    /// `channel_pattern` follows Redis pub/sub glob rules: `workflow.*`,
    /// `agent_runtime.session.?`, etc. The returned `Stream` decodes each
    /// incoming pub/sub message as an `EventEnvelope`.
    pub async fn subscribe(
        &self,
        channel_pattern: &str,
    ) -> Result<
        impl Stream<Item = Result<EventEnvelope, EventBusError>> + Send + 'static,
        EventBusError,
    > {
        let mut pubsub = self.client.get_async_pubsub().await?;
        pubsub.psubscribe(channel_pattern).await?;
        Ok(pubsub.into_on_message().map(decode_message))
    }

    /// Record that `key` has been handled successfully. Used by subscribers
    /// to dedup redelivered envelopes (consumer-group retry, etc.).
    pub async fn mark_handled(&self, key: &str) {
        self.seen.lock().await.mark(key);
    }

    /// Returns `true` if `key` was previously marked handled and the entry
    /// has not yet expired.
    pub async fn was_handled(&self, key: &str) -> bool {
        self.seen.lock().await.contains(key)
    }
}

fn decode_message(msg: redis::Msg) -> Result<EventEnvelope, EventBusError> {
    let payload: String = msg.get_payload()?;
    let envelope: EventEnvelope = serde_json::from_str(&payload)?;
    Ok(envelope)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn idempotency_cache_marks_and_checks_keys() {
        let mut cache = IdempotencyCache::with_ttl(IDEMPOTENCY_TTL);

        assert!(!cache.contains("k1"));
        cache.mark("k1");
        assert!(cache.contains("k1"));
        assert!(!cache.contains("k2"));
    }

    #[test]
    fn idempotency_cache_evicts_expired_entries() {
        let mut cache = IdempotencyCache::with_ttl(Duration::from_millis(0));
        cache.mark("ephemeral");
        // TTL=0 means anything inserted is already expired on next touch.
        assert!(!cache.contains("ephemeral"));
    }
}
