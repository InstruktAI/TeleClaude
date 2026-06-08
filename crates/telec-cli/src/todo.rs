//! `telec todo` subtree.
//!
//! Mirrors the v1 `telec.py` CLI_SURFACE entries for the `todo` command.
//! CRUD-style subcommands route through [`workflow::WorkflowService`];
//! orchestrator-level subcommands (`design`, `prepare`, `work`, …) stub
//! out with exit-code 2 so the v1 Python shim can pick them up during the
//! transition window.

use anyhow::{anyhow, Context, Result};
use clap::{Args, Subcommand};
use identity::Principal;
use shared::{ProjectId, Slug};
use similar::TextDiff;
use sqlx::Row;
use workflow::models::{ArtifactName, CreationMode, TodoKind};
use workflow::service::{CreateTodoArgs, TodoPatch};
use workflow::WorkflowService;

use crate::output;

/// Exit code used for "implementation deferred to v1 Python shim".
pub const EXIT_DEFERRED_TO_V1: i32 = 2;

/// Top-level `telec todo` args wrapper.
#[derive(Args, Debug)]
pub struct TodoArgs {
    #[command(subcommand)]
    pub command: TodoCommand,
}

#[derive(Subcommand, Debug)]
pub enum TodoCommand {
    /// Create a new todo backed by its required `input` artifact.
    Create(CreateArgs),
    /// List todo entries (source of truth for todo status).
    List(ListArgs),
    /// Run the creative state machine (deferred to v1).
    Design(DeferredSlugArgs),
    /// Deprecated alias for `telec todo design` (deferred to v1).
    CoCreate(DeferredSlugArgs),
    /// Remove a todo and its todo entry.
    Remove(SlugArgs),
    /// Move a todo to the icebox.
    Freeze(SlugArgs),
    /// Promote a todo from the icebox to the active todo list.
    Unfreeze(SlugArgs),
    /// Move a todo to delivered.
    Deliver(DeliverArgs),
    /// Run the Phase A (prepare) state machine (deferred to v1).
    Prepare(DeferredSlugArgs),
    /// Run the Phase B (work) state machine (deferred to v1).
    Work(DeferredSlugArgs),
    /// Run the Phase C (integrate) state machine (deferred to v1).
    Integrate(DeferredSlugArgs),
    /// Operator override: write the authoritative `lifecycle_phase`
    /// (deferred to v1).
    MarkPhase(DeferredSlugArgs),
    /// Re-evaluate evidence and align `lifecycle_phase` (deferred to v1).
    Reconcile(DeferredSlugArgs),
    /// Set dependencies for a work item in the todo list.
    SetDeps(SetDepsArgs),
    /// Fire-and-forget brain dump (deferred to v1).
    Dump(DeferredSlugArgs),
    /// Split a todo into child items (deferred to v1).
    Split(DeferredSlugArgs),
    /// Stamp a verdict or readiness marker (deferred to v1).
    Stamp(DeferredSlugArgs),
    /// Show the full state payload for a todo.
    Show(SlugArgs),
    /// Manage todo artifacts in the database.
    Artifacts(ArtifactsArgs),
}

#[derive(Args, Debug)]
pub struct CreateArgs {
    /// Todo slug (unique per project).
    pub slug: String,
    /// Comma-separated dependency slugs.
    #[arg(long)]
    pub after: Option<String>,
    /// Work item kind: feature | change | bug | task. Omit for kind-less intake.
    #[arg(long)]
    pub kind: Option<String>,
    /// Optional free-form description.
    #[arg(long)]
    pub description: Option<String>,
    /// Optional visual grouping label.
    #[arg(long)]
    pub group: Option<String>,
    /// Inline content for the required `input` artifact. Mutually exclusive
    /// with `--input-file`. Pass `-` to read from stdin. v2 refuses to
    /// create a todo without an input artifact (reviewer RV2).
    #[arg(long, conflicts_with = "input_file")]
    pub input: Option<String>,
    /// Path to a file whose contents seed the required `input` artifact.
    /// Mutually exclusive with `--input`.
    #[arg(long)]
    pub input_file: Option<std::path::PathBuf>,
}

#[derive(Args, Debug)]
pub struct SlugArgs {
    pub slug: String,
}

#[derive(Args, Debug)]
pub struct ListArgs {
    /// Include icebox entries in the listing.
    #[arg(long)]
    pub include_icebox: bool,
    /// Show only icebox entries.
    #[arg(long)]
    pub icebox_only: bool,
    /// Include delivered entries in the listing.
    #[arg(long)]
    pub include_delivered: bool,
    /// Show only delivered entries.
    #[arg(long)]
    pub delivered_only: bool,
    /// Emit results as JSON instead of a table.
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct SetDepsArgs {
    pub slug: String,
    /// Comma-separated dependency slugs (replaces existing edges verbatim).
    #[arg(long, default_value = "")]
    pub after: String,
}

#[derive(Args, Debug)]
pub struct DeliverArgs {
    pub slug: String,
    /// Commit hash to record (auto-detection is not implemented in v2; pass
    /// the hash explicitly).
    #[arg(long)]
    pub commit: Option<String>,
}

/// Slug placeholder used by subcommands that defer to v1.
///
/// Accepts any trailing arguments so the user gets the same exit-code 2
/// behavior whether they pass flags or not.
#[derive(Args, Debug)]
pub struct DeferredSlugArgs {
    /// Optional positional args (ignored — passed through to the v1 shim).
    #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
    pub args: Vec<String>,
}

#[derive(Args, Debug)]
pub struct ArtifactsArgs {
    #[command(subcommand)]
    pub command: ArtifactsCommand,
}

#[derive(Subcommand, Debug)]
pub enum ArtifactsCommand {
    /// List artifacts for a todo.
    List(SlugArgs),
    /// Read a todo artifact.
    Read(ArtifactNameArgs),
    /// Write a todo artifact.
    Write(ArtifactWriteArgs),
    /// Show a unified diff between two artifact versions.
    Diff(ArtifactDiffArgs),
    /// Remove a todo artifact and its version history.
    Remove(ArtifactNameArgs),
}

#[derive(Args, Debug)]
pub struct ArtifactNameArgs {
    pub slug: String,
    /// Artifact name (e.g. `prd`, `test-specs`, `implementation-plan`).
    pub name: String,
}

#[derive(Args, Debug)]
pub struct ArtifactWriteArgs {
    pub slug: String,
    pub name: String,
    /// Inline artifact content. Pass `-` to read from stdin.
    pub content: String,
}

#[derive(Args, Debug)]
pub struct ArtifactDiffArgs {
    pub slug: String,
    pub name: String,
    pub old_digest: String,
    pub new_digest: String,
}

/// Dispatch a parsed `telec todo` invocation against the workflow service.
pub async fn dispatch(
    args: TodoArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    match args.command {
        TodoCommand::Create(a) => create(a, service, project, principal).await,
        TodoCommand::List(a) => list(a, service, project).await,
        TodoCommand::Remove(a) => remove(a, service, project, principal).await,
        TodoCommand::Freeze(a) => freeze(a, service, project, principal).await,
        TodoCommand::Unfreeze(a) => unfreeze(a, service, project, principal).await,
        TodoCommand::Deliver(a) => deliver(a, service, project, principal).await,
        TodoCommand::SetDeps(a) => set_deps(a, service, project, principal).await,
        TodoCommand::Show(a) => show(a, service, project).await,
        TodoCommand::Artifacts(a) => dispatch_artifacts(a, service, project, principal).await,
        TodoCommand::Design(_) => deferred("design"),
        TodoCommand::CoCreate(_) => deferred("co-create"),
        TodoCommand::Prepare(_) => deferred("prepare"),
        TodoCommand::Work(_) => deferred("work"),
        TodoCommand::Integrate(_) => deferred("integrate"),
        TodoCommand::MarkPhase(_) => deferred("mark-phase"),
        TodoCommand::Reconcile(_) => deferred("reconcile"),
        TodoCommand::Dump(_) => deferred("dump"),
        TodoCommand::Split(_) => deferred("split"),
        TodoCommand::Stamp(_) => deferred("stamp"),
    }
}

async fn list(args: ListArgs, service: &WorkflowService, project: ProjectId) -> Result<i32> {
    // Translate v1 flag combinations to the storage service surface:
    // icebox_only and delivered_only widen the service result, then filter.
    let include_icebox = args.include_icebox || args.icebox_only;
    let include_delivered = args.include_delivered || args.delivered_only;
    let mut entries = service
        .list_roadmap(project, include_icebox, include_delivered)
        .await?;

    if args.icebox_only {
        entries.retain(|e| e.frozen);
    } else if args.delivered_only {
        entries.retain(|e| e.delivered_at.is_some());
    }

    if args.json {
        output::print_json(&entries)?;
    } else {
        println!("{}", output::render_todo_list(&entries));
    }
    Ok(0)
}

async fn create(
    args: CreateArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let after = parse_after(args.after.as_deref())?;
    let kind = args.kind.as_deref().map(parse_kind).transpose()?;
    let input_content = resolve_input_content(args.input.as_deref(), args.input_file.as_deref())?;
    let todo = service
        .create_todo(
            CreateTodoArgs {
                project,
                slug,
                kind,
                description: args.description,
                after,
                group: args.group,
                input_content,
                creation_mode: CreationMode::Pickup,
            },
            principal,
        )
        .await?;
    output::print_json(&todo)?;
    Ok(0)
}

/// Resolve the inline `--input` value (or `-` for stdin) and `--input-file`
/// path arguments into the input artifact content. v2 refuses creation when
/// neither flag is provided.
fn resolve_input_content(inline: Option<&str>, file: Option<&std::path::Path>) -> Result<String> {
    match (inline, file) {
        (Some(_), Some(_)) => Err(anyhow!("--input and --input-file are mutually exclusive")),
        (Some("-"), None) => {
            let mut buf = String::new();
            std::io::Read::read_to_string(&mut std::io::stdin(), &mut buf)
                .context("read input artifact from stdin")?;
            ensure_non_empty(buf)
        }
        (Some(inline), None) => ensure_non_empty(inline.to_owned()),
        (None, Some(path)) => {
            let content = std::fs::read_to_string(path)
                .with_context(|| format!("read input artifact from {}", path.display()))?;
            ensure_non_empty(content)
        }
        (None, None) => Err(anyhow!(
            "v2 requires an input artifact: pass --input <text> or --input-file <path>"
        )),
    }
}

fn ensure_non_empty(content: String) -> Result<String> {
    if content.trim().is_empty() {
        Err(anyhow!("input artifact content must not be empty"))
    } else {
        Ok(content)
    }
}

async fn remove(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    service.delete_todo(project, &slug, principal).await?;
    println!("removed todo {}", slug.as_str());
    Ok(0)
}

async fn freeze(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let entry = service
        .freeze_roadmap_entry(project, &slug, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn unfreeze(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let entry = service
        .unfreeze_roadmap_entry(project, &slug, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn deliver(
    args: DeliverArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let entry = service
        .deliver_roadmap_entry(project, &slug, args.commit, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn set_deps(
    args: SetDepsArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let after = parse_after(Some(&args.after))?;
    let patch = TodoPatch {
        after: Some(after),
        ..Default::default()
    };
    let todo = service
        .update_todo(project, &slug, patch, principal)
        .await?;
    output::print_json(&todo)?;
    Ok(0)
}

async fn show(args: SlugArgs, service: &WorkflowService, project: ProjectId) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let todo = service.get_todo(project, &slug).await?;
    output::print_json(&todo)?;
    Ok(0)
}

async fn dispatch_artifacts(
    args: ArtifactsArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    match args.command {
        ArtifactsCommand::List(a) => artifacts_list(a, service, project).await,
        ArtifactsCommand::Read(a) => artifacts_read(a, service, project).await,
        ArtifactsCommand::Write(a) => artifacts_write(a, service, project, principal).await,
        ArtifactsCommand::Diff(a) => artifacts_diff(a, service, project).await,
        ArtifactsCommand::Remove(a) => artifacts_remove(a, service, project, principal).await,
    }
}

async fn artifacts_list(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let artifacts = service.list_artifacts(project, &slug).await?;
    let names: Vec<&str> = artifacts
        .iter()
        .map(|a| artifact_name_label(a.name))
        .collect();
    output::print_json(&names)?;
    Ok(0)
}

async fn artifacts_read(
    args: ArtifactNameArgs,
    service: &WorkflowService,
    project: ProjectId,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let name = parse_artifact_name(&args.name)?;
    let artifact = service.read_artifact(project, &slug, name).await?;
    print!("{}", artifact.content);
    Ok(0)
}

async fn artifacts_write(
    args: ArtifactWriteArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let name = parse_artifact_name(&args.name)?;
    let content = if args.content == "-" {
        read_stdin_to_string()?
    } else {
        args.content
    };
    let artifact = service
        .write_artifact(project, &slug, name, content, principal)
        .await?;
    println!(
        "wrote artifact {} for {} (digest={})",
        artifact_name_label(artifact.name),
        slug.as_str(),
        artifact.digest
    );
    Ok(0)
}

async fn artifacts_diff(
    args: ArtifactDiffArgs,
    service: &WorkflowService,
    project: ProjectId,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let name = parse_artifact_name(&args.name)?;

    // Resolve the bigserial todo PK so we can query artifact_versions
    // directly. The service crate does not expose a per-version reader yet;
    // until it does, the CLI reaches into the pool with a scoped query.
    let pool = service.pool();
    let todo_pk: Option<i64> =
        sqlx::query_scalar("select id from workflow.todos where project_id = $1 and slug = $2")
            .bind(project)
            .bind(slug.as_str())
            .fetch_optional(pool)
            .await
            .context("look up todo for artifact diff")?;
    let Some(todo_pk) = todo_pk else {
        return Err(anyhow!("todo not found: {}", slug.as_str()));
    };

    let old_content = fetch_artifact_version(pool, todo_pk, name, &args.old_digest).await?;
    let new_content = fetch_artifact_version(pool, todo_pk, name, &args.new_digest).await?;

    let diff = TextDiff::from_lines(&old_content, &new_content);
    print!(
        "{}",
        diff.unified_diff().header(
            &format!(
                "{}@{}",
                artifact_name_label(name),
                short_digest(&args.old_digest)
            ),
            &format!(
                "{}@{}",
                artifact_name_label(name),
                short_digest(&args.new_digest)
            ),
        )
    );
    Ok(0)
}

async fn artifacts_remove(
    args: ArtifactNameArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let name = parse_artifact_name(&args.name)?;
    service
        .remove_artifact(project, &slug, name, principal)
        .await?;
    println!(
        "removed artifact {} for {}",
        artifact_name_label(name),
        slug.as_str()
    );
    Ok(0)
}

async fn fetch_artifact_version(
    pool: &sqlx::PgPool,
    todo_pk: i64,
    name: ArtifactName,
    digest: &str,
) -> Result<String> {
    let row = sqlx::query(
        "select content from workflow.artifact_versions
         where todo_id = $1 and name = $2 and digest = $3
         order by created_at desc
         limit 1",
    )
    .bind(todo_pk)
    .bind(name)
    .bind(digest)
    .fetch_optional(pool)
    .await
    .context("query artifact_versions")?;
    let row =
        row.ok_or_else(|| anyhow!("no artifact version with digest {digest} for {name:?}"))?;
    row.try_get::<String, _>("content")
        .context("decode artifact version content")
}

pub(crate) fn parse_after(raw: Option<&str>) -> Result<Vec<Slug>> {
    let Some(raw) = raw else {
        return Ok(Vec::new());
    };
    parse_after_values([raw])
}

pub(crate) fn parse_after_values<'a, I>(raw_values: I) -> Result<Vec<Slug>>
where
    I: IntoIterator<Item = &'a str>,
{
    raw_values
        .into_iter()
        .flat_map(|raw| raw.split(','))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(Slug::new)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| anyhow!("invalid dependency slug: {err}"))
}

pub(crate) fn parse_kind(raw: &str) -> Result<TodoKind> {
    match raw {
        "feature" => Ok(TodoKind::Feature),
        "change" => Ok(TodoKind::Change),
        "bug" => Ok(TodoKind::Bug),
        "task" => Ok(TodoKind::Task),
        other => Err(anyhow!(
            "unknown --kind {other:?}; expected feature|change|bug|task"
        )),
    }
}

fn parse_artifact_name(raw: &str) -> Result<ArtifactName> {
    // ArtifactName uses serde kebab-case; round-trip a JSON string.
    let json = format!("\"{}\"", raw.replace('"', "\\\""));
    serde_json::from_str::<ArtifactName>(&json).map_err(|_| {
        anyhow!(
            "unknown artifact name {raw:?}; expected one of input|prd|requirements|architecture|\
             test-specs|implementation-plan|bug|quality-checklist|design-spec|deferrals|\
             task-plan|\
             requirements-review-findings|architecture-review-findings|spec-review-findings|\
             plan-review-findings|review-findings"
        )
    })
}

fn artifact_name_label(name: ArtifactName) -> &'static str {
    match name {
        ArtifactName::Input => "input",
        ArtifactName::Prd => "prd",
        ArtifactName::Requirements => "requirements",
        ArtifactName::Architecture => "architecture",
        ArtifactName::TestSpecs => "test-specs",
        ArtifactName::ImplementationPlan => "implementation-plan",
        ArtifactName::Bug => "bug",
        ArtifactName::QualityChecklist => "quality-checklist",
        ArtifactName::DesignSpec => "design-spec",
        ArtifactName::Deferrals => "deferrals",
        ArtifactName::TaskPlan => "task-plan",
        ArtifactName::RequirementsReviewFindings => "requirements-review-findings",
        ArtifactName::ArchitectureReviewFindings => "architecture-review-findings",
        ArtifactName::SpecReviewFindings => "spec-review-findings",
        ArtifactName::PlanReviewFindings => "plan-review-findings",
        ArtifactName::ReviewFindings => "review-findings",
    }
}

fn short_digest(digest: &str) -> &str {
    if digest.len() > 12 {
        &digest[..12]
    } else {
        digest
    }
}

fn read_stdin_to_string() -> Result<String> {
    use std::io::Read;
    let mut buf = String::new();
    std::io::stdin()
        .read_to_string(&mut buf)
        .context("read content from stdin")?;
    Ok(buf)
}

fn deferred(subcommand: &str) -> Result<i32> {
    eprintln!(
        "telec todo {subcommand}: not implemented in v2-mvp (orchestrator-level); \
         falls back to v1 Python implementation."
    );
    Ok(EXIT_DEFERRED_TO_V1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_after_splits_on_comma() {
        let after = parse_after(Some("a, b ,c")).expect("parse");
        let names: Vec<&str> = after.iter().map(Slug::as_str).collect();
        assert_eq!(names, vec!["a", "b", "c"]);
    }

    #[test]
    fn parse_after_empty_returns_empty_vec() {
        assert!(parse_after(None).expect("parse").is_empty());
        assert!(parse_after(Some("")).expect("parse").is_empty());
    }

    #[test]
    fn parse_kind_accepts_canonical_values() {
        assert!(matches!(parse_kind("feature"), Ok(TodoKind::Feature)));
        assert!(matches!(parse_kind("change"), Ok(TodoKind::Change)));
        assert!(matches!(parse_kind("bug"), Ok(TodoKind::Bug)));
        assert!(matches!(parse_kind("task"), Ok(TodoKind::Task)));
    }

    #[test]
    fn parse_kind_rejects_unknown() {
        assert!(parse_kind("widget").is_err());
    }

    #[test]
    fn parse_artifact_name_round_trips_kebab_case() {
        assert!(matches!(
            parse_artifact_name("test-specs"),
            Ok(ArtifactName::TestSpecs)
        ));
        assert!(matches!(parse_artifact_name("prd"), Ok(ArtifactName::Prd)));
    }

    #[test]
    fn parse_artifact_name_rejects_unknown() {
        assert!(parse_artifact_name("bogus").is_err());
    }
}
