use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use redis::aio::ConnectionManager;
use redis::Client;
use serde_json::Value;
use tokio::sync::Mutex;
use tracing::warn;

use crate::errors::ReconciliationError;

pub const FLEET_CROSS_VERSION_INTEROP_FEATURE_ID: &str =
    "project/spec/feature/reconciliation/fleet-cross-version-interop";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FleetCapabilityEntry {
    pub computer: String,
    pub version: Option<String>,
    pub channel: Option<String>,
    pub capability_set: BTreeSet<String>,
    pub last_advertised_at: DateTime<Utc>,
}

impl FleetCapabilityEntry {
    pub fn new(
        computer: impl Into<String>,
        version: Option<String>,
        channel: Option<String>,
        capability_set: impl IntoIterator<Item = String>,
        last_advertised_at: DateTime<Utc>,
    ) -> Result<Self, ReconciliationError> {
        let computer = computer.into();
        if computer.trim().is_empty() {
            return Err(ReconciliationError::InvalidHeartbeatEntry(
                "computer must be non-empty".to_string(),
            ));
        }
        Ok(Self {
            computer,
            version,
            channel,
            capability_set: capability_set
                .into_iter()
                .filter(|feature_id| !feature_id.is_empty())
                .collect(),
            last_advertised_at,
        })
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct FleetCapabilityMap {
    pub entries: Vec<FleetCapabilityEntry>,
}

impl FleetCapabilityMap {
    pub fn materialize(
        entries: impl IntoIterator<Item = FleetCapabilityEntry>,
        now: DateTime<Utc>,
        heartbeat_ttl: Duration,
    ) -> Result<Self, ReconciliationError> {
        if heartbeat_ttl.is_zero() {
            return Err(ReconciliationError::InvalidHeartbeatTtl(heartbeat_ttl));
        }
        let ttl = chrono::Duration::from_std(heartbeat_ttl)
            .map_err(|_| ReconciliationError::InvalidHeartbeatTtl(heartbeat_ttl))?;
        let mut entries = entries
            .into_iter()
            .filter(|entry| now.signed_duration_since(entry.last_advertised_at) <= ttl)
            .collect::<Vec<_>>();
        entries.sort_by(|left, right| left.computer.cmp(&right.computer));
        Ok(Self { entries })
    }

    pub fn safe_to_require(&self, feature_id: &str) -> bool {
        self.every_live_node_carries(feature_id)
    }

    pub fn safe_to_contract(&self, feature_id: &str) -> bool {
        self.every_live_node_carries(feature_id)
    }

    fn every_live_node_carries(&self, feature_id: &str) -> bool {
        !feature_id.is_empty()
            && !self.entries.is_empty()
            && self
                .entries
                .iter()
                .all(|entry| entry.capability_set.contains(feature_id))
    }
}

#[async_trait]
pub trait CapabilityMapProvider: Send + Sync {
    async fn fleet_capability_map(&self) -> Result<FleetCapabilityMap, ReconciliationError>;
}

pub struct StaticCapabilityMapProvider {
    map: FleetCapabilityMap,
}

impl StaticCapabilityMapProvider {
    pub fn new(map: FleetCapabilityMap) -> Self {
        Self { map }
    }

    pub fn shared(map: FleetCapabilityMap) -> Arc<dyn CapabilityMapProvider> {
        Arc::new(Self::new(map))
    }
}

#[async_trait]
impl CapabilityMapProvider for StaticCapabilityMapProvider {
    async fn fleet_capability_map(&self) -> Result<FleetCapabilityMap, ReconciliationError> {
        Ok(self.map.clone())
    }
}

pub struct RedisHeartbeatCapabilityMapProvider {
    conn: Mutex<ConnectionManager>,
    heartbeat_ttl: Duration,
}

impl RedisHeartbeatCapabilityMapProvider {
    pub async fn connect(
        redis_url: &str,
        heartbeat_ttl: Duration,
    ) -> Result<Self, ReconciliationError> {
        let client = Client::open(redis_url)?;
        let conn = ConnectionManager::new(client).await?;
        Ok(Self {
            conn: Mutex::new(conn),
            heartbeat_ttl,
        })
    }
}

#[async_trait]
impl CapabilityMapProvider for RedisHeartbeatCapabilityMapProvider {
    async fn fleet_capability_map(&self) -> Result<FleetCapabilityMap, ReconciliationError> {
        let mut conn = self.conn.lock().await;
        let mut cursor = 0_u64;
        let mut keys = Vec::new();
        loop {
            let (next_cursor, batch): (u64, Vec<String>) = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg("computer:*:heartbeat")
                .query_async(&mut *conn)
                .await?;
            keys.extend(batch);
            if next_cursor == 0 {
                break;
            }
            cursor = next_cursor;
        }

        let mut entries = Vec::new();
        for key in keys {
            let raw: Option<String> = redis::cmd("GET").arg(&key).query_async(&mut *conn).await?;
            let Some(raw) = raw else {
                continue;
            };
            let value: Value = match serde_json::from_str(&raw) {
                Ok(value) => value,
                Err(error) => {
                    warn!(key = %key, error = %error, "skipping malformed heartbeat payload");
                    continue;
                }
            };
            match heartbeat_entry_from_value(&value) {
                Ok(entry) => entries.push(entry),
                Err(error) => {
                    warn!(key = %key, error = %error, "skipping invalid heartbeat entry");
                }
            }
        }
        FleetCapabilityMap::materialize(entries, Utc::now(), self.heartbeat_ttl)
    }
}

pub fn decode_capability_set(value: &Value) -> BTreeSet<String> {
    value
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .filter(|item| !item.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

pub fn heartbeat_entry_from_value(
    value: &Value,
) -> Result<FleetCapabilityEntry, ReconciliationError> {
    let computer = value
        .get("computer_name")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            ReconciliationError::InvalidHeartbeatEntry("computer_name is required".to_string())
        })?;
    let advertised = value
        .get("last_seen")
        .and_then(Value::as_str)
        .and_then(|raw| DateTime::parse_from_rfc3339(raw).ok())
        .map(|timestamp| timestamp.with_timezone(&Utc))
        .ok_or_else(|| {
            ReconciliationError::InvalidHeartbeatEntry("last_seen is required".to_string())
        })?;
    let version = value
        .get("version")
        .and_then(Value::as_str)
        .map(str::to_string);
    let channel = value
        .get("channel")
        .and_then(Value::as_str)
        .map(str::to_string);
    let capability_set = decode_capability_set(value.get("capability_set").unwrap_or(&Value::Null));
    FleetCapabilityEntry::new(computer, version, channel, capability_set, advertised)
}
