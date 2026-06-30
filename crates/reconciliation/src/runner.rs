use std::env;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use config::{ConfigOverlayPaths, ConfigService, DeploymentChannel, DeploymentConfig};
use event_bus::{EventBus, EventBusError, EventEnvelope, SubscriptionScopes};
use futures::stream::BoxStream;
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
const DEFAULT_RESUBSCRIBE_BACKOFF: Duration = Duration::from_secs(1);

/// Hands out fresh release-signal subscription streams on demand.
///
/// Abstracted so the runner's resubscribe-on-stream-end loop is testable
/// without a live Redis pub/sub connection; the production implementation is
/// backed by `EventBus`.
#[async_trait]
pub(crate) trait ReleaseSubscriptionSource: Send + Sync {
    async fn subscribe(
        &self,
    ) -> Result<BoxStream<'static, Result<EventEnvelope, EventBusError>>, EventBusError>;
}

struct EventBusSubscriptionSource {
    event_bus: Arc<EventBus>,
}

#[async_trait]
impl ReleaseSubscriptionSource for EventBusSubscriptionSource {
    async fn subscribe(
        &self,
    ) -> Result<BoxStream<'static, Result<EventEnvelope, EventBusError>>, EventBusError> {
        let stream = self
            .event_bus
            .subscribe(INTEGRATION_INBOX_RECEIVED, SubscriptionScopes::cluster())
            .await?;
        Ok(stream.boxed())
    }
}

/// Outcome of driving a single subscription stream to completion.
enum SubscriptionOutcome {
    /// The `shutdown` future resolved; the runner must stop.
    Shutdown,
    /// The stream ended (transport closed); the runner must resubscribe.
    StreamEnded,
}

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
    pub resubscribe_backoff: Duration,
}

impl Default for RunnerConfig {
    fn default() -> Self {
        Self {
            self_check_interval: DEFAULT_SELF_CHECK_INTERVAL,
            resubscribe_backoff: DEFAULT_RESUBSCRIBE_BACKOFF,
        }
    }
}

pub struct ReconciliationRunner {
    event_bus: Option<Arc<EventBus>>,
    subscription_source: Option<Arc<dyn ReleaseSubscriptionSource>>,
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
        let subscription_source: Option<Arc<dyn ReleaseSubscriptionSource>> =
            event_bus.as_ref().map(|bus| {
                Arc::new(EventBusSubscriptionSource {
                    event_bus: Arc::clone(bus),
                }) as Arc<dyn ReleaseSubscriptionSource>
            });
        Self {
            event_bus,
            subscription_source,
            desired_state,
            ledger,
            convergence,
            publisher,
            last_visible_release: Mutex::new(None),
            config,
        }
    }

    #[cfg(test)]
    pub(crate) fn with_subscription_source(
        mut self,
        source: Arc<dyn ReleaseSubscriptionSource>,
    ) -> Self {
        self.subscription_source = Some(source);
        self
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
        let Some(source) = &self.subscription_source else {
            shutdown.await;
            return Ok(());
        };
        let mut interval = tokio::time::interval(self.config.self_check_interval);
        let mut shutdown = shutdown;
        loop {
            let stream = match source.subscribe().await {
                Ok(stream) => stream,
                Err(error) => {
                    warn!(
                        error = %error,
                        "reconciliation release resubscribe failed; backing off before retry",
                    );
                    tokio::select! {
                        _ = &mut shutdown => return Ok(()),
                        _ = tokio::time::sleep(self.config.resubscribe_backoff) => continue,
                    }
                }
            };
            match self
                .drive_subscription(stream, &mut shutdown, &mut interval)
                .await?
            {
                SubscriptionOutcome::Shutdown => return Ok(()),
                SubscriptionOutcome::StreamEnded => {
                    warn!("reconciliation release subscription ended; resubscribing");
                }
            }
        }
    }

    async fn drive_subscription(
        &self,
        stream: BoxStream<'static, Result<EventEnvelope, EventBusError>>,
        shutdown: &mut Pin<Box<dyn Future<Output = ()> + Send>>,
        interval: &mut tokio::time::Interval,
    ) -> Result<SubscriptionOutcome, ReconciliationError> {
        let mut stream = stream;
        loop {
            tokio::select! {
                _ = &mut *shutdown => return Ok(SubscriptionOutcome::Shutdown),
                _ = interval.tick() => {
                    self.self_check_once().await?;
                }
                next = stream.next() => {
                    match next {
                        Some(Ok(envelope)) => {
                            self.handle_envelope(envelope).await?;
                        }
                        Some(Err(error)) => return Err(error.into()),
                        None => return Ok(SubscriptionOutcome::StreamEnded),
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

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicUsize, Ordering};

    use config::{DeploymentConfig, ProjectConfig};
    use event_bus::envelope::ENVELOPE_SCHEMA_VERSION;
    use event_bus::EventScope;
    use serde_json::json;
    use tempfile::tempdir;
    use tokio::sync::oneshot;

    use super::*;
    use crate::capability_map::{
        CapabilityMapProvider, FleetCapabilityEntry, FleetCapabilityMap,
        StaticCapabilityMapProvider, FLEET_CROSS_VERSION_INTEROP_FEATURE_ID,
    };
    use crate::convergence::{ConvergenceExecutor, ConvergencePlan, ConvergenceStepExecutor};
    use crate::events::{MemoryEventPublisher, ReconciliationEventPublisher};
    use crate::ledger::AppliedVersionLedger;
    use crate::RECONCILIATION_DRIFT_DETECTED;

    /// Scripted release-stream behavior handed out on each `subscribe` call.
    enum SubscribeScript {
        /// Stream that ends immediately (transport closed).
        Empty,
        /// Stream that stays open with no items (healthy subscription).
        Pending,
        /// Stream that yields one envelope then ends.
        OneThenEnd(EventEnvelope),
        /// Subscribe call itself fails.
        Error,
    }

    /// Test double for `ReleaseSubscriptionSource` that replays scripted streams
    /// and records how many times the runner (re)subscribed.
    struct ScriptedSource {
        scripts: Mutex<VecDeque<SubscribeScript>>,
        calls: AtomicUsize,
    }

    impl ScriptedSource {
        fn new(scripts: Vec<SubscribeScript>) -> Self {
            Self {
                scripts: Mutex::new(scripts.into_iter().collect()),
                calls: AtomicUsize::new(0),
            }
        }

        fn call_count(&self) -> usize {
            self.calls.load(Ordering::SeqCst)
        }
    }

    #[async_trait]
    impl ReleaseSubscriptionSource for ScriptedSource {
        async fn subscribe(
            &self,
        ) -> Result<BoxStream<'static, Result<EventEnvelope, EventBusError>>, EventBusError>
        {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let script = self
                .scripts
                .lock()
                .await
                .pop_front()
                .unwrap_or(SubscribeScript::Pending);
            match script {
                SubscribeScript::Empty => {
                    Ok(futures::stream::empty::<Result<EventEnvelope, EventBusError>>().boxed())
                }
                SubscribeScript::Pending => {
                    Ok(futures::stream::pending::<Result<EventEnvelope, EventBusError>>().boxed())
                }
                SubscribeScript::OneThenEnd(envelope) => Ok(futures::stream::once(async move {
                    Ok::<EventEnvelope, EventBusError>(envelope)
                })
                .boxed()),
                SubscribeScript::Error => Err(EventBusError::Disconnected),
            }
        }
    }

    struct NoopSteps;

    #[async_trait]
    impl ConvergenceStepExecutor for NoopSteps {
        async fn checkout_build(&self, _plan: &ConvergencePlan) -> Result<(), String> {
            Ok(())
        }
        async fn migrate(&self, _plan: &ConvergencePlan) -> Result<(), String> {
            Ok(())
        }
        async fn restart(&self, _plan: &ConvergencePlan) -> Result<(), String> {
            Ok(())
        }
    }

    fn deployment() -> DeploymentConfig {
        serde_yaml::from_str::<ProjectConfig>(
            r#"
deployment:
  channel: beta
  pinned_minor: ''
"#,
        )
        .expect("project config")
        .deployment
    }

    fn capability_provider() -> Arc<dyn CapabilityMapProvider> {
        let now = chrono::Utc::now();
        let entry = FleetCapabilityEntry::new(
            "local-node",
            Some("1.2.4".to_string()),
            Some("beta".to_string()),
            [FLEET_CROSS_VERSION_INTEROP_FEATURE_ID.to_string()],
            now,
        )
        .expect("entry");
        StaticCapabilityMapProvider::shared(
            FleetCapabilityMap::materialize([entry], now, Duration::from_secs(60)).expect("map"),
        )
    }

    fn release_envelope(version: &str, delivery_id: &str) -> EventEnvelope {
        EventEnvelope {
            schema_version: ENVELOPE_SCHEMA_VERSION,
            scope: EventScope::Cluster,
            channel: INTEGRATION_INBOX_RECEIVED.to_string(),
            idempotency_key: delivery_id.to_string(),
            emitted_at: chrono::Utc::now(),
            principal: None,
            payload: json!({
                "entry_id": delivery_id,
                "provider": "github",
                "event_name": "github.release",
                "payload": {"release": {"tag_name": version}},
                "properties": {"action": "published"},
                "received_at": chrono::Utc::now(),
                "verified": true,
                "idempotency_key": delivery_id,
            }),
        }
    }

    fn test_runner(
        source: Arc<dyn ReleaseSubscriptionSource>,
        resubscribe_backoff: Duration,
    ) -> (
        ReconciliationRunner,
        Arc<MemoryEventPublisher>,
        tempfile::TempDir,
    ) {
        let dir = tempdir().expect("tempdir");
        let ledger = Arc::new(AppliedVersionLedger::at_path(
            dir.path().join("applied_versions.json"),
        ));
        let publisher = Arc::new(MemoryEventPublisher::new());
        let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
        let provider = Arc::new(StaticDesiredStateProvider::new(DesiredState {
            computer: "local-node".to_string(),
            deployment: deployment(),
            current_version: "1.2.4".to_string(),
        }));
        let convergence = Arc::new(ConvergenceExecutor::new(
            Arc::new(NoopSteps),
            Arc::clone(&ledger),
            capability_provider(),
        ));
        let runner = ReconciliationRunner::new(
            None,
            provider,
            Arc::clone(&ledger),
            convergence,
            publisher_sink,
            RunnerConfig {
                resubscribe_backoff,
                ..RunnerConfig::default()
            },
        )
        .with_subscription_source(source);
        (runner, publisher, dir)
    }

    fn shutdown_signal() -> (
        oneshot::Sender<()>,
        Pin<Box<dyn Future<Output = ()> + Send>>,
    ) {
        let (tx, rx) = oneshot::channel::<()>();
        let fut: Pin<Box<dyn Future<Output = ()> + Send>> = Box::pin(async move {
            let _ = rx.await;
        });
        (tx, fut)
    }

    #[tokio::test]
    async fn stream_end_resubscribes_and_does_not_resolve_before_shutdown() {
        let source = Arc::new(ScriptedSource::new(vec![
            SubscribeScript::Empty,
            SubscribeScript::Pending,
        ]));
        let (runner, _publisher, _dir) = test_runner(source.clone(), Duration::from_millis(10));
        let (tx, shutdown) = shutdown_signal();

        let fut = runner.run_until_shutdown(shutdown);
        tokio::pin!(fut);

        // Stream #1 ends immediately. A correct runner resubscribes (stream #2)
        // and keeps running; the StreamEnded->Ok(()) mutant would resolve here.
        let pending = tokio::time::timeout(Duration::from_millis(100), &mut fut).await;
        assert!(
            pending.is_err(),
            "runner resolved before shutdown when the subscription stream ended"
        );
        assert!(
            source.call_count() >= 2,
            "runner did not resubscribe after stream-end (calls={})",
            source.call_count()
        );

        // A real shutdown signal still resolves it cleanly.
        tx.send(()).expect("send shutdown");
        let result = tokio::time::timeout(Duration::from_secs(1), &mut fut).await;
        assert!(
            matches!(result, Ok(Ok(()))),
            "shutdown did not resolve the runner: {result:?}"
        );
    }

    #[tokio::test]
    async fn resubscribe_error_retries_until_shutdown() {
        let source = Arc::new(ScriptedSource::new(vec![
            SubscribeScript::Empty,
            SubscribeScript::Error,
            SubscribeScript::Pending,
        ]));
        let (runner, _publisher, _dir) = test_runner(source.clone(), Duration::from_millis(10));
        let (tx, shutdown) = shutdown_signal();

        let fut = runner.run_until_shutdown(shutdown);
        tokio::pin!(fut);

        // Stream #1 ends -> resubscribe; subscribe #2 errors -> back off and
        // retry rather than propagating (which would crash the daemon).
        let pending = tokio::time::timeout(Duration::from_millis(200), &mut fut).await;
        assert!(
            pending.is_err(),
            "runner returned after a resubscribe error instead of retrying"
        );
        assert!(
            source.call_count() >= 3,
            "runner did not retry after the resubscribe error (calls={})",
            source.call_count()
        );

        tx.send(()).expect("send shutdown");
        let result = tokio::time::timeout(Duration::from_secs(1), &mut fut).await;
        assert!(matches!(result, Ok(Ok(()))));
    }

    #[tokio::test]
    async fn shutdown_during_resubscribe_backoff_exits_promptly() {
        let source = Arc::new(ScriptedSource::new(vec![
            SubscribeScript::Error,
            SubscribeScript::Pending,
        ]));
        // A long backoff: the only way to exit within the timeout is for the
        // backoff wait to honor the shutdown future.
        let (runner, _publisher, _dir) = test_runner(source.clone(), Duration::from_secs(30));
        let (tx, shutdown) = shutdown_signal();

        let fut = runner.run_until_shutdown(shutdown);
        tokio::pin!(fut);

        // Let the runner reach the backoff wait.
        let _ = tokio::time::timeout(Duration::from_millis(50), &mut fut).await;
        tx.send(()).expect("send shutdown");

        let result = tokio::time::timeout(Duration::from_secs(1), &mut fut).await;
        assert!(
            matches!(result, Ok(Ok(()))),
            "shutdown during the resubscribe backoff did not exit promptly: {result:?}"
        );
    }

    #[tokio::test]
    async fn envelope_is_handled_before_stream_end() {
        let source = Arc::new(ScriptedSource::new(vec![
            SubscribeScript::OneThenEnd(release_envelope("1.2.5", "delivery-1")),
            SubscribeScript::Pending,
        ]));
        let (runner, publisher, _dir) = test_runner(source.clone(), Duration::from_millis(10));
        let (tx, shutdown) = shutdown_signal();

        let fut = runner.run_until_shutdown(shutdown);
        tokio::pin!(fut);

        // Drive long enough to process the envelope and resubscribe.
        let _ = tokio::time::timeout(Duration::from_millis(150), &mut fut).await;

        let envelopes = publisher.envelopes().await;
        assert!(
            envelopes
                .iter()
                .any(|envelope| envelope.channel == RECONCILIATION_DRIFT_DETECTED),
            "release envelope was not handled before the stream ended"
        );
        assert!(
            source.call_count() >= 2,
            "runner did not resubscribe after handling the envelope (calls={})",
            source.call_count()
        );

        tx.send(()).expect("send shutdown");
        let result = tokio::time::timeout(Duration::from_secs(1), &mut fut).await;
        assert!(matches!(result, Ok(Ok(()))));
    }
}
