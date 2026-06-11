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

use futures::future;
use futures::stream::{select_all, BoxStream};
use futures::{Stream, StreamExt};
use redis::aio::ConnectionManager;
use redis::Client;
use tokio::sync::Mutex;

use crate::envelope::{EventEnvelope, EventScope};
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

/// Runtime configuration for the event bus.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EventBusConfig {
    /// Resolved cluster bus Redis URL. `CLUSTER_REDIS_URL` vs `REDIS_URL`
    /// name resolution happens in the caller.
    pub cluster_bus: String,
    /// Optional public federation Redis URL.
    pub public: Option<String>,
}

/// Subscription scope selector.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SubscriptionScopes {
    bits: u8,
}

impl SubscriptionScopes {
    const LOCAL: u8 = 0b001;
    const CLUSTER: u8 = 0b010;
    const PUBLIC: u8 = 0b100;
    const ALL: u8 = Self::LOCAL | Self::CLUSTER | Self::PUBLIC;

    /// Subscribe to every configured scope.
    pub fn all() -> Self {
        Self { bits: Self::ALL }
    }

    /// Subscribe to Local envelopes only.
    pub fn local() -> Self {
        Self { bits: Self::LOCAL }
    }

    /// Subscribe to Cluster envelopes only.
    pub fn cluster() -> Self {
        Self {
            bits: Self::CLUSTER,
        }
    }

    /// Subscribe to Public envelopes only.
    pub fn public() -> Self {
        Self { bits: Self::PUBLIC }
    }

    /// Return a scope set that also includes `scope`.
    pub fn with(mut self, scope: EventScope) -> Self {
        self.bits |= bit_for_scope(scope);
        self
    }

    fn contains(self, scope: EventScope) -> bool {
        self.bits & bit_for_scope(scope) != 0
    }

    fn wants_bus(self) -> bool {
        self.bits & (Self::LOCAL | Self::CLUSTER) != 0
    }

    fn wants_public(self) -> bool {
        self.bits & Self::PUBLIC != 0
    }

    fn is_all(self) -> bool {
        self.bits == Self::ALL
    }
}

impl Default for SubscriptionScopes {
    fn default() -> Self {
        Self::all()
    }
}

fn bit_for_scope(scope: EventScope) -> u8 {
    match scope {
        EventScope::Local => SubscriptionScopes::LOCAL,
        EventScope::Cluster => SubscriptionScopes::CLUSTER,
        EventScope::Public => SubscriptionScopes::PUBLIC,
    }
}

struct ScopeClient {
    client: Client,
    conn: Mutex<ConnectionManager>,
}

impl ScopeClient {
    async fn connect(redis_url: &str) -> Result<Self, EventBusError> {
        let client = Client::open(redis_url)?;
        let conn = ConnectionManager::new(client.clone()).await?;
        Ok(Self {
            client,
            conn: Mutex::new(conn),
        })
    }

    async fn emit(&self, envelope: &EventEnvelope) -> Result<(), EventBusError> {
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

    async fn subscribe(
        &self,
        channel_pattern: &str,
    ) -> Result<BoxStream<'static, Result<EventEnvelope, EventBusError>>, EventBusError> {
        let mut pubsub = self.client.get_async_pubsub().await?;
        pubsub.psubscribe(channel_pattern).await?;
        Ok(pubsub.into_on_message().map(decode_message).boxed())
    }
}

/// Redis-backed event bus.
///
/// Holds:
/// - a mandatory cluster bus Redis client for Local and Cluster scopes,
/// - an optional public Redis client for Public scope,
/// - an in-memory idempotency-key cache.
///
/// Wrap in an `Arc` to share across tasks/services.
pub struct EventBus {
    bus: ScopeClient,
    public: Option<ScopeClient>,
    seen: Mutex<IdempotencyCache>,
}

impl EventBus {
    /// Connect to the configured Redis scopes.
    pub async fn connect(config: EventBusConfig) -> Result<Self, EventBusError> {
        let bus = ScopeClient::connect(&config.cluster_bus).await?;
        let public = match config.public {
            Some(url) => Some(ScopeClient::connect(&url).await?),
            None => None,
        };
        Ok(Self {
            bus,
            public,
            seen: Mutex::new(IdempotencyCache::with_ttl(IDEMPOTENCY_TTL)),
        })
    }

    /// Return whether this bus can emit or subscribe to `scope`.
    pub fn has_scope(&self, scope: EventScope) -> bool {
        match scope {
            EventScope::Local | EventScope::Cluster => true,
            EventScope::Public => self.public.is_some(),
        }
    }

    /// Emit an envelope to Redis: append to the per-channel Stream, then
    /// PUBLISH for live subscribers.
    pub async fn emit(&self, envelope: &EventEnvelope) -> Result<(), EventBusError> {
        match envelope.scope {
            EventScope::Local | EventScope::Cluster => self.bus.emit(envelope).await,
            EventScope::Public => match &self.public {
                Some(public) => public.emit(envelope).await,
                None => {
                    tracing::debug!(
                        scope = ?envelope.scope,
                        channel = %envelope.channel,
                        "dropping public event because public Redis is not configured",
                    );
                    Ok(())
                }
            },
        }
    }

    /// Subscribe to a channel pattern via Redis `PSUBSCRIBE`.
    ///
    /// `channel_pattern` follows Redis pub/sub glob rules: `workflow.*`,
    /// `agent_runtime.session.?`, etc. The returned `Stream` decodes each
    /// incoming pub/sub message as an `EventEnvelope`.
    pub async fn subscribe(
        &self,
        channel_pattern: &str,
        scopes: SubscriptionScopes,
    ) -> Result<
        impl Stream<Item = Result<EventEnvelope, EventBusError>> + Send + 'static,
        EventBusError,
    > {
        let mut streams = Vec::new();
        if scopes.wants_bus() {
            streams.push(self.bus.subscribe(channel_pattern).await?);
        }
        if scopes.wants_public() {
            if let Some(public) = &self.public {
                streams.push(public.subscribe(channel_pattern).await?);
            }
        }

        let mut yielded_keys = if streams.len() > 1 {
            Some(IdempotencyCache::with_ttl(IDEMPOTENCY_TTL))
        } else {
            None
        };
        Ok(select_all(streams).filter_map(move |result| {
            let item = match result {
                Ok(envelope) => {
                    if !scopes.is_all() && !scopes.contains(envelope.scope) {
                        None
                    } else if let Some(cache) = yielded_keys.as_mut() {
                        if cache.contains(&envelope.idempotency_key) {
                            None
                        } else {
                            cache.mark(&envelope.idempotency_key);
                            Some(Ok(envelope))
                        }
                    } else {
                        Some(Ok(envelope))
                    }
                }
                Err(err) => Some(Err(err)),
            };
            future::ready(item)
        }))
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
    use crate::envelope::ENVELOPE_SCHEMA_VERSION;
    use redis::Value;
    use serde_json::json;

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

    #[test]
    fn decode_message_ignores_unknown_top_level_envelope_fields() {
        let payload = json!({
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "channel": "workflow.todo.created",
            "idempotency_key": "todo-42-created",
            "emitted_at": "2026-05-16T12:00:00Z",
            "principal": null,
            "payload": {"slug": "demo", "title": "Demo"},
            "future_capability": {"ignored": true}
        })
        .to_string();
        let msg = redis::Msg::from_owned_value(Value::Array(vec![
            Value::BulkString(b"message".to_vec()),
            Value::BulkString(b"workflow.todo.created".to_vec()),
            Value::BulkString(payload.into_bytes()),
        ]))
        .expect("static Redis pub/sub message shape is valid");

        let decoded = decode_message(msg).expect("message decodes with unknown field");

        assert_eq!(decoded.schema_version, ENVELOPE_SCHEMA_VERSION);
        assert_eq!(decoded.channel, "workflow.todo.created");
    }
}
