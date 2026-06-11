use std::env;
use std::path::PathBuf;
use std::process::ExitCode;

use anyhow::{anyhow, Context, Result};
use config::{ConfigOverlayPaths, ConfigService};
use telec_daemon::{DaemonRuntime, OsShutdownSource};
use tracing::{error, info};

const LOG_SOURCE: &str = "telec-daemon";

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
    let _config = ConfigService::new(config_paths)
        .load()
        .context("load effective config")?;

    let runtime = DaemonRuntime::empty();
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
