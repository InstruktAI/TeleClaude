mod common;

use std::sync::Arc;

use reconciliation::{
    AppliedVersionLedger, ConvergenceExecutor, MemoryEventPublisher, ReconciliationEventPublisher,
    ReconciliationRunner, ReleaseSignal, RunnerConfig, RECONCILIATION_CONVERGED,
};
use tempfile::tempdir;

#[test]
fn applied_ledger_survives_restart() {
    let dir = tempdir().expect("tempdir");
    let path = dir.path().join("applied_versions.json");
    let target = ReleaseSignal::published_release("1.2.5", "delivery-1")
        .expect("signal")
        .target;

    let before = AppliedVersionLedger::at_path(&path);
    before.mark_applied(&target).expect("mark applied");
    let after = AppliedVersionLedger::at_path(&path);

    assert!(after.is_applied(&target).expect("ledger reads"));
}

#[tokio::test]
async fn reapplied_target_is_noop() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let signal = ReleaseSignal::published_release("1.2.5", "delivery-1").expect("signal");
    ledger.mark_applied(&signal.target).expect("mark applied");
    let state = common::desired_state(
        common::deployment(
            r#"
deployment:
  channel: beta
"#,
        ),
        "1.2.4",
    );
    let publisher = Arc::new(MemoryEventPublisher::new());
    let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
    let runner = test_runner(Arc::clone(&ledger), publisher_sink, state);

    runner
        .self_check_once()
        .await
        .expect("empty self-check succeeds");
    runner
        .handle_envelope(crate_envelope::release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("duplicate signal handled");

    assert!(publisher.envelopes().await.is_empty());
}

#[tokio::test]
async fn converged_event_carries_target_version() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let state = common::desired_state(
        common::deployment(
            r#"
deployment:
  channel: beta
"#,
        ),
        "1.2.4",
    );
    let publisher = Arc::new(MemoryEventPublisher::new());
    let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
    let runner = test_runner(Arc::clone(&ledger), publisher_sink, state);

    runner
        .handle_envelope(crate_envelope::release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("release handled");

    let envelopes = publisher.envelopes().await;
    let converged = envelopes
        .iter()
        .find(|envelope| envelope.channel == RECONCILIATION_CONVERGED)
        .expect("converged event emitted");
    assert_eq!(converged.payload["to_version"], "1.2.5");
}

#[tokio::test]
async fn current_target_after_restart_marks_applied_without_rerun() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let target = reconciliation::TargetVersion::new("1.2.5").expect("target");
    let state = common::desired_state(
        common::deployment(
            r#"
deployment:
  channel: beta
"#,
        ),
        "1.2.5",
    );
    let publisher = Arc::new(MemoryEventPublisher::new());
    let publisher_sink: Arc<dyn ReconciliationEventPublisher> = publisher.clone();
    let runner = test_runner(Arc::clone(&ledger), publisher_sink, state);

    runner
        .handle_envelope(crate_envelope::release_envelope("1.2.5", "delivery-1"))
        .await
        .expect("release handled");

    assert!(ledger.is_applied(&target).expect("ledger reads"));
    let envelopes = publisher.envelopes().await;
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, RECONCILIATION_CONVERGED);
    assert!(ledger.runs().expect("runs read").is_empty());
}

fn test_runner(
    ledger: Arc<AppliedVersionLedger>,
    publisher: Arc<dyn ReconciliationEventPublisher>,
    state: reconciliation::DesiredState,
) -> ReconciliationRunner {
    let convergence = Arc::new(ConvergenceExecutor::new(
        Arc::new(common::RecordingSteps::default()),
        Arc::clone(&ledger),
        common::full_capability_provider(),
    ));
    ReconciliationRunner::new(
        None,
        common::desired_provider(state),
        ledger,
        convergence,
        publisher,
        RunnerConfig::default(),
    )
}

mod crate_envelope {
    use chrono::Utc;
    use event_bus::{envelope::ENVELOPE_SCHEMA_VERSION, EventEnvelope, EventScope};
    use integration::INTEGRATION_INBOX_RECEIVED;
    use serde_json::json;

    pub fn release_envelope(version: &str, delivery_id: &str) -> EventEnvelope {
        EventEnvelope {
            schema_version: ENVELOPE_SCHEMA_VERSION,
            scope: EventScope::Cluster,
            channel: INTEGRATION_INBOX_RECEIVED.to_string(),
            idempotency_key: delivery_id.to_string(),
            emitted_at: Utc::now(),
            principal: None,
            payload: json!({
                "entry_id": delivery_id,
                "provider": "github",
                "event_name": "github.release",
                "payload": {"release": {"tag_name": version}},
                "properties": {"action": "published"},
                "received_at": Utc::now(),
                "verified": true,
                "idempotency_key": delivery_id,
            }),
        }
    }
}
