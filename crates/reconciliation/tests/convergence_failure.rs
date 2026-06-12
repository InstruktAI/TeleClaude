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
    RECONCILIATION_FAILED,
};
use serde_json::json;
use tempfile::tempdir;

struct FailingMigrateSteps;

#[async_trait]
impl ConvergenceStepExecutor for FailingMigrateSteps {
    async fn checkout_build(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Ok(())
    }

    async fn migrate(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Err("migration failed".to_string())
    }

    async fn restart(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Ok(())
    }
}

struct FailingRestartSteps;

#[async_trait]
impl ConvergenceStepExecutor for FailingRestartSteps {
    async fn checkout_build(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Ok(())
    }

    async fn migrate(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Ok(())
    }

    async fn restart(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Err("restart failed".to_string())
    }
}

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
async fn failed_step_halts_and_emits() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let publisher = Arc::new(MemoryEventPublisher::new());
    let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
    let runner = ReconciliationRunner::new(
        None,
        Arc::new(StaticDesiredStateProvider::new(DesiredState {
            computer: "local-node".to_string(),
            deployment: deployment(),
            current_version: "1.2.4".to_string(),
        })),
        Arc::clone(&ledger),
        Arc::new(ConvergenceExecutor::new(
            Arc::new(FailingMigrateSteps),
            Arc::clone(&ledger),
            capability_provider(),
        )),
        publisher_sink,
        RunnerConfig::default(),
    );

    runner
        .handle_envelope(release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("release handled");

    let envelopes = publisher.envelopes().await;
    let failed = envelopes
        .iter()
        .find(|envelope| envelope.channel == RECONCILIATION_FAILED)
        .expect("failure emitted");
    assert_eq!(failed.payload["failed_step"], "migrate");
    assert_eq!(failed.payload["failure_context"], "migration failed");
    assert!(envelopes
        .iter()
        .all(|envelope| envelope.channel != RECONCILIATION_CONVERGED));
    let runs = ledger.runs().expect("runs read");
    assert_eq!(runs[0].failed_step.as_deref(), Some("migrate"));
}

#[tokio::test]
async fn failed_restart_does_not_mark_target_applied() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let publisher = Arc::new(MemoryEventPublisher::new());
    let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
    let runner = ReconciliationRunner::new(
        None,
        Arc::new(StaticDesiredStateProvider::new(DesiredState {
            computer: "local-node".to_string(),
            deployment: deployment(),
            current_version: "1.2.4".to_string(),
        })),
        Arc::clone(&ledger),
        Arc::new(ConvergenceExecutor::new(
            Arc::new(FailingRestartSteps),
            Arc::clone(&ledger),
            capability_provider(),
        )),
        publisher_sink,
        RunnerConfig::default(),
    );
    let target = reconciliation::TargetVersion::new("1.2.5").expect("target");

    runner
        .handle_envelope(release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("release handled");

    let envelopes = publisher.envelopes().await;
    let failed = envelopes
        .iter()
        .find(|envelope| envelope.channel == RECONCILIATION_FAILED)
        .expect("failure emitted");
    assert_eq!(failed.payload["failed_step"], "restart");
    assert_eq!(failed.payload["failure_context"], "restart failed");
    assert!(!ledger.is_applied(&target).expect("ledger reads"));
}

#[tokio::test]
async fn unsafe_migration_gate_halts_and_emits_failure() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let publisher = Arc::new(MemoryEventPublisher::new());
    let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
    let runner = ReconciliationRunner::new(
        None,
        Arc::new(StaticDesiredStateProvider::new(DesiredState {
            computer: "local-node".to_string(),
            deployment: deployment(),
            current_version: "1.2.4".to_string(),
        })),
        Arc::clone(&ledger),
        Arc::new(ConvergenceExecutor::new(
            Arc::new(SuccessfulSteps),
            Arc::clone(&ledger),
            unsafe_capability_provider(),
        )),
        publisher_sink,
        RunnerConfig::default(),
    );
    let target = reconciliation::TargetVersion::new("1.2.5").expect("target");

    runner
        .handle_envelope(release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("release handled");

    let envelopes = publisher.envelopes().await;
    let failed = envelopes
        .iter()
        .find(|envelope| envelope.channel == RECONCILIATION_FAILED)
        .expect("failure emitted");
    assert_eq!(failed.payload["failed_step"], "migrate");
    assert_eq!(
        failed.payload["failure_context"],
        format!("feature {FLEET_CROSS_VERSION_INTEROP_FEATURE_ID} is not safe for Require")
    );
    assert!(envelopes
        .iter()
        .all(|envelope| envelope.channel != RECONCILIATION_CONVERGED));
    assert!(!ledger.is_applied(&target).expect("ledger reads"));
    let runs = ledger.runs().expect("runs read");
    assert_eq!(runs[0].failed_step.as_deref(), Some("migrate"));
}

fn deployment() -> DeploymentConfig {
    serde_yaml::from_str::<ProjectConfig>(
        r#"
deployment:
  channel: beta
"#,
    )
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

fn unsafe_capability_provider() -> Arc<dyn reconciliation::CapabilityMapProvider> {
    let now = chrono::Utc::now();
    let entry = FleetCapabilityEntry::new(
        "local-node",
        Some("1.2.4".to_string()),
        Some("beta".to_string()),
        [],
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
