use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use config::DeploymentConfig;
use reconciliation::{
    AppliedVersionLedger, ConvergenceExecutor, ConvergencePlan, ConvergenceStepExecutor,
    DesiredState, FleetCapabilityMap, MemoryEventPublisher, ReconciliationRunner, RunnerConfig,
    StaticCapabilityMapProvider, StaticDesiredStateProvider,
};
use telec_daemon::{ReconciliationServiceLoop, ServiceLoop};
use tempfile::tempdir;
use tokio::time::timeout;

struct UnusedSteps;

#[async_trait]
impl ConvergenceStepExecutor for UnusedSteps {
    async fn checkout_build(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        panic!("shutdown test does not converge")
    }

    async fn migrate(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        panic!("shutdown test does not converge")
    }

    async fn restart(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        panic!("shutdown test does not converge")
    }
}

#[tokio::test]
async fn reconciliation_loop_shutdown_completes_bounded_runner() {
    let dir = tempdir().expect("tempdir");
    let ledger = Arc::new(AppliedVersionLedger::at_path(
        dir.path().join("applied_versions.json"),
    ));
    let runner = Arc::new(ReconciliationRunner::new(
        None,
        Arc::new(StaticDesiredStateProvider::new(DesiredState {
            computer: "local-node".to_string(),
            deployment: DeploymentConfig::default(),
            current_version: "0.1.0".to_string(),
        })),
        Arc::clone(&ledger),
        Arc::new(ConvergenceExecutor::new(
            Arc::new(UnusedSteps),
            ledger,
            StaticCapabilityMapProvider::shared(FleetCapabilityMap::default()),
        )),
        Arc::new(MemoryEventPublisher::new()),
        RunnerConfig::default(),
    ));
    let service_loop = Arc::new(ReconciliationServiceLoop::new(runner));

    let task = {
        let service_loop = Arc::clone(&service_loop);
        tokio::spawn(async move { service_loop.run().await })
    };
    tokio::time::sleep(Duration::from_millis(50)).await;

    service_loop.shutdown().await.expect("shutdown signals");
    timeout(Duration::from_secs(2), task)
        .await
        .expect("run completes within bounded timeout")
        .expect("run task joins")
        .expect("loop exits cleanly");
}
