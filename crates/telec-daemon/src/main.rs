use std::env;
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;

use anyhow::{anyhow, Context, Result};
use config::{ConfigOverlayPaths, ConfigService};
use event_bus::{EventBus, EventBusConfig};
use integration::IngressServer;
use telec_daemon::{DaemonRuntime, IngressServiceLoop, OsShutdownSource};
use tracing::{error, info, warn};

const LOG_SOURCE: &str = "telec-daemon";
const CLUSTER_REDIS_URL_ENV: &str = "CLUSTER_REDIS_URL";
const REDIS_URL_ENV: &str = "REDIS_URL";
const PUBLIC_REDIS_URL_ENV: &str = "PUBLIC_REDIS_URL";

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            error!(error = %err, "telec-daemon exited with error");
            ExitCode::FAILURE
        }
    }
}

async fn run() -> Result<()> {
    let _ = dotenvy::dotenv();

    let _log_guard = match observability::init(LOG_SOURCE) {
        Ok(guard) => Some(guard),
        Err(observability::InitError::AlreadyInitialized) => None,
        Err(other) => return Err(other).context("initialize tracing subscriber"),
    };

    info!(source = LOG_SOURCE, "telec-daemon starting");

    let config_paths = config_overlay_paths().context("resolve config overlay paths")?;
    let config = ConfigService::new(config_paths)
        .load()
        .context("load effective config")?;

    let mut runtime = DaemonRuntime::empty();
    if config.global.ingress.enabled {
        let event_bus = Arc::new(
            EventBus::connect(EventBusConfig {
                cluster_bus: cluster_bus_url()?,
                public: optional_env(PUBLIC_REDIS_URL_ENV),
            })
            .await
            .context("connect cluster event bus for ingress")?,
        );
        let server = IngressServer::from_config(&config.global.ingress, event_bus)
            .context("build ingress server")?;
        runtime.register_loop(Arc::new(IngressServiceLoop::new(server)));
    }

    runtime
        .run(&OsShutdownSource)
        .await
        .context("run daemon runtime")?;

    info!(source = LOG_SOURCE, "telec-daemon stopped");
    Ok(())
}

fn config_overlay_paths() -> Result<ConfigOverlayPaths> {
    let teleclaude_home = match env::var("TELECLAUDE_HOME") {
        Ok(value) if !value.is_empty() => PathBuf::from(value),
        _ => PathBuf::from(required_env("HOME")?).join(".teleclaude"),
    };

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
