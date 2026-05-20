//! telec-cli — v2 replacement for selected workflow surfaces.
//!
//! Composes the primitive crates (observability, storage, event-bus,
//! identity, workflow) and dispatches todo/roadmap/workflow subcommands. Other
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
use identity::IdentityService;
use workflow::WorkflowService;

mod config;
mod identity_sink;
mod migrate;
mod migrate_identity;
mod output;
mod project;
mod roadmap;
mod todo;
mod workflow_cli;

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
    long_about = "Rust replacement for selected workflow surfaces. \
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
    /// Manage v2 workflow surfaces.
    Workflow(workflow_cli::WorkflowArgs),
    /// One-shot data migration from v1 SQLite to v2 Postgres (stub; G1).
    MigrateWorkflowV1(migrate::MigrateArgs),
    /// One-shot import of the v1 people roster and v1 session tokens
    /// into the v2 `identity` schema (Wave E1).
    MigrateIdentityV1(migrate_identity::MigrateIdentityArgs),
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
    //
    // The returned `WorkerGuard` must be held for the process's lifetime —
    // dropping it drains the non-blocking writer's queue and joins the
    // background I/O thread. Binding it here keeps it alive until `run`
    // returns; the `_guard` prefix marks it as intentionally unused while
    // still binding.
    let _log_guard = match observability::init(LOG_SOURCE) {
        Ok(guard) => Some(guard),
        Err(observability::InitError::AlreadyInitialized) => None,
        Err(other) => return Err(other).context("initialize tracing subscriber"),
    };

    let cfg = config::CliConfig::from_env().context("read CLI configuration from environment")?;

    let pool = storage::build_pool(&cfg.database_url)
        .await
        .context("build Postgres pool")?;

    storage::run_migrations(&pool, &identity::MIGRATOR)
        .await
        .context("apply identity schema migrations")?;

    let events = Arc::new(
        EventBus::connect(&cfg.redis_url)
            .await
            .context("connect to Redis event bus")?,
    );

    // Resolve identity: prefer TELEC_SESSION_TOKEN (validated against the
    // identity schema in Postgres), else TELECLAUDE_OWNER_EMAIL. The
    // session-token path requires the pool, so it builds on top of the
    // freshly-constructed connection.
    let identity_sink = Arc::new(identity_sink::EventBusIdentitySink::new(
        events.clone(),
        None,
    ));
    let identity_service = IdentityService::new(pool.clone(), identity_sink.clone());
    let principal = {
        let token_validator = identity_service.token_validator();
        identity::resolve_from_environment(&token_validator)
            .await
            .context("resolve principal identity")?
    };

    let service = WorkflowService::new(pool, events);
    let project = project::resolve_project(&service, cli.project.as_deref())
        .await
        .context("resolve project context")?;

    match cli.command {
        Command::Todo(args) => todo::dispatch(args, &service, project, &principal).await,
        Command::Roadmap(args) => roadmap::dispatch(args, &service, project, &principal).await,
        Command::Workflow(args) => {
            workflow_cli::dispatch(args, &service, project, &principal).await
        }
        Command::MigrateWorkflowV1(args) => migrate::run(args, &service).await,
        Command::MigrateIdentityV1(args) => {
            let summary = migrate_identity::migrate_identity_v1(&identity_service, &args)
                .await
                .context("run migrate-identity-v1")?;
            println!(
                "migrate-identity-v1: humans inserted={}, skipped_existing={}, tokens inserted={}, skipped={}{}",
                summary.humans_inserted,
                summary.humans_skipped_existing,
                summary.tokens_inserted,
                summary.tokens_skipped_existing,
                if summary.dry_run { " (dry-run; reverted)" } else { "" },
            );
            Ok(0)
        }
    }
}
