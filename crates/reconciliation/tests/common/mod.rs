use std::sync::Arc;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use config::{DeploymentConfig, ProjectConfig};
use reconciliation::{
    ConvergencePlan, ConvergenceStepExecutor, DesiredState, FleetCapabilityEntry,
    FleetCapabilityMap, StaticCapabilityMapProvider, StaticDesiredStateProvider,
    FLEET_CROSS_VERSION_INTEROP_FEATURE_ID,
};

pub fn deployment(yaml: &str) -> DeploymentConfig {
    serde_yaml::from_str::<ProjectConfig>(yaml)
        .expect("project config parses")
        .deployment
}

pub fn desired_state(deployment: DeploymentConfig, current_version: &str) -> DesiredState {
    DesiredState {
        computer: "local-node".to_string(),
        deployment,
        current_version: current_version.to_string(),
    }
}

pub fn desired_provider(state: DesiredState) -> Arc<StaticDesiredStateProvider> {
    Arc::new(StaticDesiredStateProvider::new(state))
}

pub fn full_capability_provider() -> Arc<dyn reconciliation::CapabilityMapProvider> {
    let now = DateTime::parse_from_rfc3339("2026-06-12T00:00:00Z")
        .expect("timestamp")
        .with_timezone(&Utc);
    let entry = FleetCapabilityEntry::new(
        "local-node",
        Some("1.2.4".to_string()),
        Some("stable".to_string()),
        [FLEET_CROSS_VERSION_INTEROP_FEATURE_ID.to_string()],
        now,
    )
    .expect("entry");
    StaticCapabilityMapProvider::shared(
        FleetCapabilityMap::materialize([entry], now, std::time::Duration::from_secs(60))
            .expect("map"),
    )
}

#[derive(Default)]
pub struct RecordingSteps {
    pub fail_step: Option<&'static str>,
}

#[async_trait]
impl ConvergenceStepExecutor for RecordingSteps {
    async fn checkout_build(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        if self.fail_step == Some("checkout_build") {
            Err("checkout failed".to_string())
        } else {
            Ok(())
        }
    }

    async fn migrate(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        if self.fail_step == Some("migrate") {
            Err("migration failed".to_string())
        } else {
            Ok(())
        }
    }

    async fn restart(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        if self.fail_step == Some("restart") {
            Err("restart failed".to_string())
        } else {
            Ok(())
        }
    }
}
