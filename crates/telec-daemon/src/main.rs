use std::env;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

use anyhow::{anyhow, Context, Result};
use config::{ConfigOverlayPaths, ConfigService};
use event_bus::{EventBus, EventBusConfig};
use integration::IngressServer;
use reconciliation::{
    AppliedVersionLedger, CommandStepExecutor, ConfigServiceDesiredStateProvider,
    ConvergenceExecutor, ReconciliationRunner, RedisHeartbeatCapabilityMapProvider,
};
use telec_daemon::{
    DaemonRuntime, IngressServiceLoop, OsShutdownSource, ReconciliationServiceLoop,
};
use tracing::{error, info, warn};

const LOG_SOURCE: &str = "telec-daemon";
const CLUSTER_REDIS_URL_ENV: &str = "CLUSTER_REDIS_URL";
const REDIS_URL_ENV: &str = "REDIS_URL";
const PUBLIC_REDIS_URL_ENV: &str = "PUBLIC_REDIS_URL";
const TELECLAUDE_COMPUTER_NAME_ENV: &str = "TELECLAUDE_COMPUTER_NAME";
const HOSTNAME_ENV: &str = "HOSTNAME";
const HEARTBEAT_TTL_SECONDS: u64 = 60;

#[tokio::main]
async fn main() -> ExitCode {
    let _ = dotenvy::dotenv();

    // The guard must outlive the error handler below: a guard scoped inside
    // run() is dropped before the error is logged, losing the fatal line.
    let _log_guard = match observability::init(LOG_SOURCE) {
        Ok(guard) => Some(guard),
        Err(observability::InitError::AlreadyInitialized) => None,
        Err(other) => {
            eprintln!("telec-daemon: failed to initialize tracing: {other}");
            return ExitCode::FAILURE;
        }
    };

    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            error!(error = format!("{err:#}"), "telec-daemon exited with error");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<()> {
    info!(source = LOG_SOURCE, "telec-daemon starting");

    let config_paths = config_overlay_paths().context("resolve config overlay paths")?;
    let config = ConfigService::new(config_paths.clone())
        .load()
        .context("load effective config")?;

    let event_bus_config = EventBusConfig {
        cluster_bus: cluster_bus_url()?,
        public: optional_env(PUBLIC_REDIS_URL_ENV),
    };
    let cluster_bus = event_bus_config.cluster_bus.clone();
    let event_bus = Arc::new(
        EventBus::connect(event_bus_config)
            .await
            .context("connect cluster event bus for daemon loops")?,
    );

    let mut runtime = DaemonRuntime::empty();
    if config.global.ingress.enabled {
        let server = IngressServer::from_config(&config.global.ingress, Arc::clone(&event_bus))
            .context("build ingress server")?;
        runtime.register_loop(Arc::new(IngressServiceLoop::new(server)));
    }
    runtime.register_loop(Arc::new(ReconciliationServiceLoop::new(Arc::new(
        reconciliation_runner(
            Arc::clone(&event_bus),
            config_paths.clone(),
            cluster_bus,
            env::current_dir().context("resolve repository root")?,
        )
        .await?,
    ))));

    runtime
        .run(&OsShutdownSource)
        .await
        .context("run daemon runtime")?;

    info!(source = LOG_SOURCE, "telec-daemon stopped");
    Ok(())
}

fn config_overlay_paths() -> Result<ConfigOverlayPaths> {
    let teleclaude_home = teleclaude_home()?;

    let project = match env::var("TELECLAUDE_PROJECT_CONFIG_PATH") {
        Ok(value) if !value.is_empty() => Some(PathBuf::from(value)),
        _ => Some(
            env::current_dir()
                .context("read current directory")?
                .join("teleclaude.yml"),
        ),
    };

    Ok(ConfigOverlayPaths {
        global: teleclaude_home.join("teleclaude.yml"),
        project,
        person: None,
    })
}

async fn reconciliation_runner(
    event_bus: Arc<EventBus>,
    config_paths: ConfigOverlayPaths,
    cluster_bus: String,
    repo_root: PathBuf,
) -> Result<ReconciliationRunner> {
    let home = teleclaude_home()?;
    let ledger = Arc::new(AppliedVersionLedger::under_home(&home));
    let capability_map = Arc::new(
        RedisHeartbeatCapabilityMapProvider::connect(
            &cluster_bus,
            std::time::Duration::from_secs(HEARTBEAT_TTL_SECONDS),
        )
        .await
        .context("connect heartbeat capability map")?,
    );
    let convergence = Arc::new(ConvergenceExecutor::new(
        Arc::new(CommandStepExecutor::new(repo_root)),
        Arc::clone(&ledger),
        capability_map,
    ));
    let desired_state = Arc::new(ConfigServiceDesiredStateProvider::new(
        config_paths,
        computer_name(),
        env!("CARGO_PKG_VERSION").to_string(),
    ));
    Ok(ReconciliationRunner::with_event_bus_publisher(
        event_bus,
        desired_state,
        ledger,
        convergence,
    ))
}

fn teleclaude_home() -> Result<PathBuf> {
    match env::var("TELECLAUDE_HOME") {
        Ok(value) if !value.is_empty() => Ok(PathBuf::from(value)),
        _ => Ok(PathBuf::from(required_env("HOME")?).join(".teleclaude")),
    }
}

fn required_env(key: &str) -> Result<String> {
    match env::var(key) {
        Ok(value) if !value.is_empty() => Ok(value),
        _ => Err(anyhow!("environment variable {key} is required but unset")),
    }
}

fn optional_env(key: &str) -> Option<String> {
    match env::var(key) {
        Ok(value) if !value.is_empty() => Some(value),
        _ => None,
    }
}

fn computer_name() -> String {
    optional_env(TELECLAUDE_COMPUTER_NAME_ENV)
        .or_else(|| optional_env(HOSTNAME_ENV))
        .unwrap_or_else(|| "local".to_string())
}

fn cluster_bus_url() -> Result<String> {
    if let Some(value) = optional_env(CLUSTER_REDIS_URL_ENV) {
        return Ok(value);
    }
    if let Some(value) = optional_env(REDIS_URL_ENV) {
        warn!("{REDIS_URL_ENV} is deprecated; set {CLUSTER_REDIS_URL_ENV} instead");
        return Ok(value);
    }
    Err(anyhow!(
        "environment variable {CLUSTER_REDIS_URL_ENV} or {REDIS_URL_ENV} is required but both are unset"
    ))
}
