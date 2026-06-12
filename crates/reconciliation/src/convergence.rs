use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use chrono::Utc;
use config::DeploymentChannel;
use tokio::process::Command;
use tokio::time::timeout;
use uuid::Uuid;

use crate::capability_map::{CapabilityMapProvider, FLEET_CROSS_VERSION_INTEROP_FEATURE_ID};
use crate::errors::ReconciliationError;
use crate::ledger::{AppliedVersionLedger, ConvergenceRunRecord, ConvergenceRunStatus};
use crate::policy::TargetVersion;

const INSTALL_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConvergenceStep {
    CheckoutBuild,
    Migrate,
    Restart,
}

impl ConvergenceStep {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::CheckoutBuild => "checkout_build",
            Self::Migrate => "migrate",
            Self::Restart => "restart",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationGateKind {
    Require,
    Contract,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MigrationGate {
    pub feature_id: String,
    pub kind: MigrationGateKind,
}

impl MigrationGate {
    pub fn require(feature_id: impl Into<String>) -> Self {
        Self {
            feature_id: feature_id.into(),
            kind: MigrationGateKind::Require,
        }
    }

    pub fn contract(feature_id: impl Into<String>) -> Self {
        Self {
            feature_id: feature_id.into(),
            kind: MigrationGateKind::Contract,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConvergencePlan {
    pub computer: String,
    pub channel: DeploymentChannel,
    pub from_version: String,
    pub to_version: TargetVersion,
    pub migration_gates: Vec<MigrationGate>,
}

impl ConvergencePlan {
    pub fn new(
        computer: impl Into<String>,
        channel: DeploymentChannel,
        from_version: impl Into<String>,
        to_version: TargetVersion,
    ) -> Self {
        Self {
            computer: computer.into(),
            channel,
            from_version: from_version.into(),
            to_version,
            migration_gates: vec![MigrationGate::require(
                FLEET_CROSS_VERSION_INTEROP_FEATURE_ID,
            )],
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConvergenceFailure {
    pub computer: String,
    pub run_id: String,
    pub from_version: String,
    pub to_version: TargetVersion,
    pub failed_step: String,
    pub failure_context: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConvergenceOutcome {
    Converged { run_id: String },
    Failed(ConvergenceFailure),
}

#[async_trait]
pub trait ConvergenceStepExecutor: Send + Sync {
    async fn checkout_build(&self, plan: &ConvergencePlan) -> Result<(), String>;
    async fn migrate(&self, plan: &ConvergencePlan) -> Result<(), String>;
    async fn restart(&self, plan: &ConvergencePlan) -> Result<(), String>;
}

pub struct ConvergenceExecutor {
    steps: Arc<dyn ConvergenceStepExecutor>,
    ledger: Arc<AppliedVersionLedger>,
    capability_map_provider: Arc<dyn CapabilityMapProvider>,
}

impl ConvergenceExecutor {
    pub fn new(
        steps: Arc<dyn ConvergenceStepExecutor>,
        ledger: Arc<AppliedVersionLedger>,
        capability_map_provider: Arc<dyn CapabilityMapProvider>,
    ) -> Self {
        Self {
            steps,
            ledger,
            capability_map_provider,
        }
    }

    pub async fn run(
        &self,
        plan: ConvergencePlan,
    ) -> Result<ConvergenceOutcome, ReconciliationError> {
        let run_id = Uuid::new_v4().to_string();
        if let Err(context) = self.steps.checkout_build(&plan).await {
            return self.fail(&run_id, &plan, ConvergenceStep::CheckoutBuild, context);
        }
        if let Err(context) = self.check_migration_gates(&plan).await {
            return self.fail(&run_id, &plan, ConvergenceStep::Migrate, context);
        }
        if let Err(context) = self.steps.migrate(&plan).await {
            return self.fail(&run_id, &plan, ConvergenceStep::Migrate, context);
        }
        if let Err(context) = self.steps.restart(&plan).await {
            return self.fail(&run_id, &plan, ConvergenceStep::Restart, context);
        }
        self.ledger.mark_applied(&plan.to_version)?;
        self.ledger.record_run(ConvergenceRunRecord {
            run_id: run_id.clone(),
            from_version: plan.from_version,
            to_version: plan.to_version,
            status: ConvergenceRunStatus::Converged,
            failed_step: None,
            failure_context: None,
            recorded_at: Utc::now(),
        })?;
        Ok(ConvergenceOutcome::Converged { run_id })
    }

    fn fail(
        &self,
        run_id: &str,
        plan: &ConvergencePlan,
        step: ConvergenceStep,
        context: String,
    ) -> Result<ConvergenceOutcome, ReconciliationError> {
        let failure = ConvergenceFailure {
            computer: plan.computer.clone(),
            run_id: run_id.to_string(),
            from_version: plan.from_version.clone(),
            to_version: plan.to_version.clone(),
            failed_step: step.as_str().to_string(),
            failure_context: context,
        };
        self.ledger.record_run(ConvergenceRunRecord {
            run_id: failure.run_id.clone(),
            from_version: failure.from_version.clone(),
            to_version: failure.to_version.clone(),
            status: ConvergenceRunStatus::Failed,
            failed_step: Some(failure.failed_step.clone()),
            failure_context: Some(failure.failure_context.clone()),
            recorded_at: Utc::now(),
        })?;
        Ok(ConvergenceOutcome::Failed(failure))
    }

    async fn check_migration_gates(&self, plan: &ConvergencePlan) -> Result<(), String> {
        if plan.migration_gates.is_empty() {
            return Ok(());
        }
        let map = self
            .capability_map_provider
            .fleet_capability_map()
            .await
            .map_err(|error| error.to_string())?;
        for gate in &plan.migration_gates {
            let safe = match gate.kind {
                MigrationGateKind::Require => map.safe_to_require(&gate.feature_id),
                MigrationGateKind::Contract => map.safe_to_contract(&gate.feature_id),
            };
            if !safe {
                return Err(format!(
                    "feature {} is not safe for {:?}",
                    gate.feature_id, gate.kind
                ));
            }
        }
        Ok(())
    }
}

pub struct CommandStepExecutor {
    repo_root: PathBuf,
}

impl CommandStepExecutor {
    pub fn new(repo_root: impl Into<PathBuf>) -> Self {
        Self {
            repo_root: repo_root.into(),
        }
    }

    async fn run_command(&self, program: &str, args: &[&str]) -> Result<(), String> {
        // External binaries are the deployment substrate here: git selects the
        // target checkout and make installs the daemon artifact managed by the
        // host service manager.
        let output = Command::new(program)
            .args(args)
            .current_dir(&self.repo_root)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|error| error.to_string())?;
        if output.status.success() {
            return Ok(());
        }
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);
        let detail = if stderr.trim().is_empty() {
            stdout.trim()
        } else {
            stderr.trim()
        };
        Err(detail.to_string())
    }
}

#[async_trait]
impl ConvergenceStepExecutor for CommandStepExecutor {
    async fn checkout_build(&self, plan: &ConvergencePlan) -> Result<(), String> {
        match plan.channel {
            DeploymentChannel::Alpha => {
                self.run_command("git", &["pull", "--ff-only", "origin", "main"])
                    .await?;
            }
            DeploymentChannel::Beta | DeploymentChannel::Stable => {
                self.run_command("git", &["fetch", "--tags"]).await?;
                let tag = format!("v{}", plan.to_version.as_str());
                self.run_command("git", &["checkout", &tag]).await?;
            }
        }
        timeout(INSTALL_TIMEOUT, self.run_command("make", &["install"]))
            .await
            .map_err(|_| "make install timed out".to_string())?
    }

    async fn migrate(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        Ok(())
    }

    async fn restart(&self, _plan: &ConvergencePlan) -> Result<(), String> {
        // Restart is a process exit: the host service manager's KeepAlive brings
        // the daemon back on the freshly installed version. Exit 42 is the agreed
        // restart-requested signal the supervisor watches for.
        std::process::exit(42);
    }
}
