use std::env;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use config::{ConfigOverlayPaths, ConfigService, DeploymentChannel, DeploymentConfig};
use event_bus::{EventBus, EventEnvelope, SubscriptionScopes};
use futures::StreamExt;
use integration::INTEGRATION_INBOX_RECEIVED;
use serde_json::Value;
use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::convergence::{ConvergenceExecutor, ConvergenceOutcome, ConvergencePlan};
use crate::errors::ReconciliationError;
use crate::events::{
    converged, convergence_failed, drift_detected, EventBusPublisher, ReconciliationEventPublisher,
};
use crate::ledger::AppliedVersionLedger;
use crate::policy::{select_target, ReleaseSignal};

const DEFAULT_SELF_CHECK_INTERVAL: Duration = Duration::from_secs(300);

#[derive(Debug, Clone)]
pub struct DesiredState {
    pub computer: String,
    pub deployment: DeploymentConfig,
    pub current_version: String,
}

impl DesiredState {
    pub fn channel_name(&self) -> &'static str {
        match self
            .deployment
            .channel()
            .unwrap_or(DeploymentChannel::Alpha)
        {
            DeploymentChannel::Alpha => "alpha",
            DeploymentChannel::Beta => "beta",
            DeploymentChannel::Stable => "stable",
        }
    }
}

#[async_trait]
pub trait DesiredStateProvider: Send + Sync {
    async fn desired_state(&self) -> Result<DesiredState, ReconciliationError>;
}

pub struct StaticDesiredStateProvider {
    state: Mutex<DesiredState>,
}

impl StaticDesiredStateProvider {
    pub fn new(state: DesiredState) -> Self {
        Self {
            state: Mutex::new(state),
        }
    }

    pub async fn set_deployment(&self, deployment: DeploymentConfig) {
        self.state.lock().await.deployment = deployment;
    }
}

#[async_trait]
impl DesiredStateProvider for StaticDesiredStateProvider {
    async fn desired_state(&self) -> Result<DesiredState, ReconciliationError> {
        Ok(self.state.lock().await.clone())
    }
}

pub struct ConfigServiceDesiredStateProvider {
    service: ConfigService,
    computer: String,
    current_version: String,
}

impl ConfigServiceDesiredStateProvider {
    pub fn new(paths: ConfigOverlayPaths, computer: String, current_version: String) -> Self {
        Self {
            service: ConfigService::new(paths),
            computer,
            current_version,
        }
    }
}

#[async_trait]
impl DesiredStateProvider for ConfigServiceDesiredStateProvider {
    async fn desired_state(&self) -> Result<DesiredState, ReconciliationError> {
        let config = self.service.load()?;
        let deployment = config
            .project
            .map(|project| project.deployment)
            .unwrap_or_default();
        Ok(DesiredState {
            computer: self.computer.clone(),
            deployment,
            current_version: self.current_version.clone(),
        })
    }
}

pub struct RunnerConfig {
    pub self_check_interval: Duration,
}

impl Default for RunnerConfig {
    fn default() -> Self {
        Self {
            self_check_interval: DEFAULT_SELF_CHECK_INTERVAL,
        }
    }
}

pub struct ReconciliationRunner {
    event_bus: Option<Arc<EventBus>>,
    desired_state: Arc<dyn DesiredStateProvider>,
    ledger: Arc<AppliedVersionLedger>,
    convergence: Arc<ConvergenceExecutor>,
    publisher: Arc<dyn ReconciliationEventPublisher>,
    last_visible_release: Mutex<Option<ReleaseSignal>>,
    config: RunnerConfig,
}

impl ReconciliationRunner {
    pub fn new(
        event_bus: Option<Arc<EventBus>>,
        desired_state: Arc<dyn DesiredStateProvider>,
        ledger: Arc<AppliedVersionLedger>,
        convergence: Arc<ConvergenceExecutor>,
        publisher: Arc<dyn ReconciliationEventPublisher>,
        config: RunnerConfig,
    ) -> Self {
        Self {
            event_bus,
            desired_state,
            ledger,
            convergence,
            publisher,
            last_visible_release: Mutex::new(None),
            config,
        }
    }

    pub fn with_event_bus_publisher(
        event_bus: Arc<EventBus>,
        desired_state: Arc<dyn DesiredStateProvider>,
        ledger: Arc<AppliedVersionLedger>,
        convergence: Arc<ConvergenceExecutor>,
    ) -> Self {
        let publisher = Arc::new(EventBusPublisher::new(Arc::clone(&event_bus)));
        Self::new(
            Some(event_bus),
            desired_state,
            ledger,
            convergence,
            publisher,
            RunnerConfig::default(),
        )
    }

    pub async fn run_until_shutdown(
        &self,
        shutdown: Pin<Box<dyn Future<Output = ()> + Send>>,
    ) -> Result<(), ReconciliationError> {
        let Some(event_bus) = &self.event_bus else {
            shutdown.await;
            return Ok(());
        };
        let stream = event_bus
            .subscribe(INTEGRATION_INBOX_RECEIVED, SubscriptionScopes::cluster())
            .await?;
        futures::pin_mut!(stream);
        let mut interval = tokio::time::interval(self.config.self_check_interval);
        let mut shutdown = shutdown;
        loop {
            tokio::select! {
                _ = &mut shutdown => {
                    return Ok(());
                }
                _ = interval.tick() => {
                    self.self_check_once().await?;
                }
                next = stream.next() => {
                    match next {
                        Some(Ok(envelope)) => {
                            self.handle_envelope(envelope).await?;
                        }
                        Some(Err(error)) => return Err(error.into()),
                        None => return Ok(()),
                    }
                }
            }
        }
    }

    pub async fn handle_envelope(
        &self,
        envelope: EventEnvelope,
    ) -> Result<(), ReconciliationError> {
        let signal = match decode_release_signal(&envelope) {
            Ok(Some(signal)) => signal,
            Ok(None) => return Ok(()),
            Err(error) => {
                warn!(
                    error = %error,
                    channel = %envelope.channel,
                    "skipping malformed reconciliation release payload",
                );
                return Ok(());
            }
        };
        *self.last_visible_release.lock().await = Some(signal.clone());
        self.evaluate_signal(signal, "release signal").await?;
        if let Some(event_bus) = &self.event_bus {
            event_bus.mark_handled(&envelope.idempotency_key).await;
        }
        Ok(())
    }

    pub async fn self_check_once(&self) -> Result<(), ReconciliationError> {
        let Some(signal) = self.last_visible_release.lock().await.clone() else {
            info!("reconciliation self-check found no visible release signal yet");
            return Ok(());
        };
        self.evaluate_signal(signal, "self-check").await
    }

    async fn evaluate_signal(
        &self,
        signal: ReleaseSignal,
        reason: &str,
    ) -> Result<(), ReconciliationError> {
        let state = self.desired_state.desired_state().await?;
        let Some(target) = select_target(&signal, &state.deployment)? else {
            return Ok(());
        };
        if target.as_str() == state.current_version {
            if !self.ledger.is_applied(&target)? {
                self.ledger.mark_applied(&target)?;
                self.publisher
                    .publish(converged(&state, &state.current_version, &target))
                    .await?;
            }
            return Ok(());
        }
        if self.ledger.is_applied(&target)? {
            return Ok(());
        }
        self.publisher
            .publish(drift_detected(&state, &target, reason))
            .await?;
        let plan = ConvergencePlan::new(
            state.computer.clone(),
            state.deployment.channel()?,
            state.current_version.clone(),
            target.clone(),
        );
        match self.convergence.run(plan).await? {
            ConvergenceOutcome::Converged { .. } => {
                self.publisher
                    .publish(converged(&state, &state.current_version, &target))
                    .await?;
            }
            ConvergenceOutcome::Failed(failure) => {
                self.publisher.publish(convergence_failed(&failure)).await?;
            }
        }
        Ok(())
    }
}

pub fn decode_release_signal(
    envelope: &EventEnvelope,
) -> Result<Option<ReleaseSignal>, ReconciliationError> {
    if envelope.channel != INTEGRATION_INBOX_RECEIVED {
        return Ok(None);
    }
    let payload = &envelope.payload;
    if payload.get("verified").and_then(Value::as_bool) != Some(true) {
        return Ok(None);
    }
    let event_name = payload
        .get("event_name")
        .and_then(Value::as_str)
        .unwrap_or("");
    let properties = payload.get("properties").unwrap_or(&Value::Null);
    let provider_payload = payload.get("payload").unwrap_or(&Value::Null);
    match event_name {
        "github.push" => decode_github_push(payload, properties, provider_payload),
        "github.release" => decode_github_release(payload, properties, provider_payload),
        _ => Ok(None),
    }
}

fn decode_github_push(
    relay_payload: &Value,
    properties: &Value,
    provider_payload: &Value,
) -> Result<Option<ReleaseSignal>, ReconciliationError> {
    if properties.get("ref").and_then(Value::as_str) != Some("refs/heads/main") {
        return Ok(None);
    }
    let version = provider_payload
        .get("after")
        .and_then(Value::as_str)
        .or_else(|| {
            provider_payload
                .get("head_commit")
                .and_then(|head| head.get("id"))
                .and_then(Value::as_str)
        })
        .unwrap_or_else(|| idempotency_key(relay_payload));
    ReleaseSignal::mainline(version, idempotency_key(relay_payload)).map(Some)
}

fn decode_github_release(
    relay_payload: &Value,
    properties: &Value,
    provider_payload: &Value,
) -> Result<Option<ReleaseSignal>, ReconciliationError> {
    if properties.get("action").and_then(Value::as_str) != Some("published") {
        return Ok(None);
    }
    let version = provider_payload
        .get("release")
        .and_then(|release| release.get("tag_name").or_else(|| release.get("name")))
        .and_then(Value::as_str)
        .or_else(|| provider_payload.get("tag_name").and_then(Value::as_str))
        .or_else(|| provider_payload.get("version").and_then(Value::as_str))
        .ok_or_else(|| {
            ReconciliationError::InvalidTargetVersion("release payload has no version".to_string())
        })?;
    ReleaseSignal::published_release(version, idempotency_key(relay_payload)).map(Some)
}

fn idempotency_key(payload: &Value) -> &str {
    payload
        .get("idempotency_key")
        .and_then(Value::as_str)
        .or_else(|| payload.get("entry_id").and_then(Value::as_str))
        .unwrap_or("unknown")
}

pub fn default_teleclaude_home() -> PathBuf {
    match env::var("TELECLAUDE_HOME") {
        Ok(value) if !value.is_empty() => PathBuf::from(value),
        _ => Path::new(&env::var("HOME").unwrap_or_else(|_| ".".to_string())).join(".teleclaude"),
    }
}
