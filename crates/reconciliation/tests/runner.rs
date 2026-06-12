use std::sync::Arc;

use async_trait::async_trait;
use config::{DeploymentConfig, ProjectConfig};
use event_bus::{envelope::ENVELOPE_SCHEMA_VERSION, EventEnvelope, EventScope};
use integration::INTEGRATION_INBOX_RECEIVED;
use reconciliation::{
    AppliedVersionLedger, ConvergenceExecutor, ConvergencePlan, ConvergenceStepExecutor,
    DesiredState, FleetCapabilityEntry, FleetCapabilityMap, MemoryEventPublisher,
    ReconciliationEventPublisher, ReconciliationRunner, RunnerConfig, StaticCapabilityMapProvider,
    StaticDesiredStateProvider, FLEET_CROSS_VERSION_INTEROP_FEATURE_ID, RECONCILIATION_CONVERGED,
    RECONCILIATION_DRIFT_DETECTED,
};
use serde_json::json;
use tempfile::tempdir;

#[derive(Default)]
struct SuccessfulSteps;

#[async_trait]
impl ConvergenceStepExecutor for SuccessfulSteps {
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

#[tokio::test]
async fn relayed_release_triggers_convergence_and_drift_event() {
    let harness = Harness::new(desired_state(deployment("beta", ""), "1.2.4"));

    harness
        .runner
        .handle_envelope(release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("release handled");

    let envelopes = harness.publisher.envelopes().await;
    assert!(envelopes
        .iter()
        .any(|envelope| envelope.channel == RECONCILIATION_DRIFT_DETECTED));
    assert!(envelopes
        .iter()
        .any(|envelope| envelope.channel == RECONCILIATION_CONVERGED));
    let target = reconciliation::TargetVersion::new("1.2.5").expect("target");
    assert!(harness.ledger.is_applied(&target).expect("ledger reads"));
}

#[tokio::test]
async fn self_check_tick_reevaluates_drift_after_config_change() {
    let provider = Arc::new(StaticDesiredStateProvider::new(desired_state(
        deployment("stable", "1.2"),
        "1.2.4",
    )));
    let harness = Harness::with_provider(Arc::clone(&provider));
    harness
        .runner
        .handle_envelope(release_envelope("1.3.0", "delivery-1"))
        .await
        .expect("out-of-pin release handled");
    assert!(harness.publisher.envelopes().await.is_empty());

    provider.set_deployment(deployment("stable", "1.3")).await;
    harness
        .runner
        .self_check_once()
        .await
        .expect("self-check reevaluates");

    let envelopes = harness.publisher.envelopes().await;
    assert!(envelopes
        .iter()
        .any(|envelope| envelope.channel == RECONCILIATION_DRIFT_DETECTED));
}

#[tokio::test]
async fn malformed_payload_is_skipped_not_crash() {
    let harness = Harness::new(desired_state(deployment("beta", ""), "1.2.4"));

    harness
        .runner
        .handle_envelope(malformed_release_envelope())
        .await
        .expect("malformed payload is absorbed");

    assert!(harness.publisher.envelopes().await.is_empty());
}

#[tokio::test]
async fn duplicate_signal_for_applied_target_is_noop() {
    let harness = Harness::new(desired_state(deployment("beta", ""), "1.2.4"));
    let target = reconciliation::TargetVersion::new("1.2.5").expect("target");
    harness.ledger.mark_applied(&target).expect("mark applied");

    harness
        .runner
        .handle_envelope(release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("duplicate handled");

    assert!(harness.publisher.envelopes().await.is_empty());
}

struct Harness {
    runner: ReconciliationRunner,
    ledger: Arc<AppliedVersionLedger>,
    publisher: Arc<MemoryEventPublisher>,
    _dir: tempfile::TempDir,
}

impl Harness {
    fn new(state: DesiredState) -> Self {
        Self::with_provider(Arc::new(StaticDesiredStateProvider::new(state)))
    }

    fn with_provider(provider: Arc<StaticDesiredStateProvider>) -> Self {
        let dir = tempdir().expect("tempdir");
        let ledger = Arc::new(AppliedVersionLedger::at_path(
            dir.path().join("applied_versions.json"),
        ));
        let publisher = Arc::new(MemoryEventPublisher::new());
        let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
        let runner = ReconciliationRunner::new(
            None,
            provider,
            Arc::clone(&ledger),
            Arc::new(ConvergenceExecutor::new(
                Arc::new(SuccessfulSteps),
                Arc::clone(&ledger),
                capability_provider(),
            )),
            publisher_sink,
            RunnerConfig::default(),
        );
        Self {
            runner,
            ledger,
            publisher,
            _dir: dir,
        }
    }
}

fn desired_state(deployment: DeploymentConfig, current_version: &str) -> DesiredState {
    DesiredState {
        computer: "local-node".to_string(),
        deployment,
        current_version: current_version.to_string(),
    }
}

fn deployment(channel: &str, pinned_minor: &str) -> DeploymentConfig {
    let yaml = format!(
        r#"
deployment:
  channel: {channel}
  pinned_minor: '{pinned_minor}'
"#
    );
    serde_yaml::from_str::<ProjectConfig>(&yaml)
        .expect("project config")
        .deployment
}

fn capability_provider() -> Arc<dyn reconciliation::CapabilityMapProvider> {
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
        FleetCapabilityMap::materialize([entry], now, std::time::Duration::from_secs(60))
            .expect("map"),
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

fn malformed_release_envelope() -> EventEnvelope {
    EventEnvelope {
        schema_version: ENVELOPE_SCHEMA_VERSION,
        scope: EventScope::Cluster,
        channel: INTEGRATION_INBOX_RECEIVED.to_string(),
        idempotency_key: "delivery-malformed".to_string(),
        emitted_at: chrono::Utc::now(),
        principal: None,
        payload: json!({
            "entry_id": "delivery-malformed",
            "provider": "github",
            "event_name": "github.release",
            "payload": {"release": {}},
            "properties": {"action": "published"},
            "received_at": chrono::Utc::now(),
            "verified": true,
            "idempotency_key": "delivery-malformed",
        }),
    }
}
