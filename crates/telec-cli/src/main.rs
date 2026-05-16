//! telec-cli — v2 replacement for `telec todo` and `telec roadmap`.
//!
//! Composes the primitive crates (observability, storage, event-bus,
//! identity, workflow) and dispatches todo/roadmap subcommands. Other
//! v1 top-level commands stay in Python during the transition; the F1 CLI
//! intentionally focuses on CRUD-level operations against
//! [`workflow::WorkflowService`].
//!
//! ## Exit codes
//!
//! * `0` — success.
//! * `1` — unexpected error (printed via `anyhow`).
//! * `2` — subcommand is intentionally deferred to the v1 Python shim
//!   (orchestrator-level commands like `todo design`, `migrate-icebox`,
//!   and `migrate-workflow-v1` until G1 lands).

use std::process::ExitCode;
use std::sync::Arc;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use event_bus::EventBus;
use workflow::WorkflowService;

mod config;
mod migrate;
mod output;
mod project;
mod roadmap;
mod todo;

/// Logical source name passed to [`observability::init`]. Matches the v1
/// logger's `source` field (`telec`) so the merged
/// `instrukt-ai-logs` view stays unified.
const LOG_SOURCE: &str = "telec";

/// Top-level CLI surface.
#[derive(Parser, Debug)]
#[command(
    name = "telec-cli",
    version,
    about = "v2 TeleClaude workflow CLI",
    long_about = "Rust replacement for `telec todo` and `telec roadmap`. \
                  Routes CRUD operations through workflow::WorkflowService; \
                  orchestrator-level subcommands defer to the v1 Python shim."
)]
struct Cli {
    /// Override the project context. By default the project name is
    /// derived from the current working directory's basename.
    #[arg(long, global = true)]
    project: Option<String>,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Manage todos.
    Todo(todo::TodoArgs),
    /// Manage the roadmap.
    Roadmap(roadmap::RoadmapArgs),
    /// One-shot data migration from v1 SQLite to v2 Postgres (stub; G1).
    MigrateWorkflowV1(migrate::MigrateArgs),
}

#[tokio::main]
async fn main() -> ExitCode {
    match run().await {
        Ok(code) => ExitCode::from(u8::try_from(code).unwrap_or(1)),
        Err(err) => {
            eprintln!("telec-cli: {err:#}");
            ExitCode::from(1)
        }
    }
}

async fn run() -> Result<i32> {
    // Load .env silently so DATABASE_URL / REDIS_URL / TELECLAUDE_OWNER_EMAIL
    // overlays apply. Failure to find an .env is not an error — the env
    // may already be populated by the parent shell.
    let _ = dotenvy::dotenv();

    let cli = Cli::parse();

    // Observability initialization is best-effort: a previously-installed
    // subscriber returns AlreadyInitialized which we treat as success.
    if let Err(err) = observability::init(LOG_SOURCE) {
        match err {
            observability::InitError::AlreadyInitialized => {}
            other => return Err(other).context("initialize tracing subscriber"),
        }
    }

    let cfg = config::CliConfig::from_env().context("read CLI configuration from environment")?;
    let principal = identity::resolve_from_env().context("resolve principal identity")?;

    let pool = storage::build_pool(&cfg.database_url)
        .await
        .context("build Postgres pool")?;

    let events = Arc::new(
        EventBus::connect(&cfg.redis_url)
            .await
            .context("connect to Redis event bus")?,
    );

    let service = WorkflowService::new(pool, events);
    let project = project::resolve_project(&service, cli.project.as_deref())
        .await
        .context("resolve project context")?;

    match cli.command {
        Command::Todo(args) => todo::dispatch(args, &service, project, &principal).await,
        Command::Roadmap(args) => roadmap::dispatch(args, &service, project, &principal).await,
        Command::MigrateWorkflowV1(args) => migrate::run(args, &service).await,
    }
}
